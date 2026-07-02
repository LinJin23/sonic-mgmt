import json
import pytest
import logging
import os
import time

logger = logging.getLogger(__name__)

GEN_CERT_SCRIPT = os.path.join(
    os.path.dirname(__file__), "scripts", "gen-server-cert.sh"
)
REMOTE_SCRIPT_PATH = "/tmp/gen-server-cert.sh"
CONTAINER_NAME = "device-ops-agent"

# mTLS cert paths on the DUT (written by gen-server-cert.sh / SONiC PKI)
CA_CRT = "/etc/sonic/telemetry/dsmsroot.cer"
CLIENT_KEY_SRC = "/etc/sonic/telemetry/dsmsroot.key"
CLIENT_KEY_TMP = "/tmp/dsmsroot-test.key"

# gRPC target (agent listens on :50050 by default)
AGENT_ADDR = "127.0.0.1:50050"

# Image server settings
IMAGE_SERVER_PORT = 8199
IMAGE_VERSION = "202505.01"
IMAGE_MAJOR = IMAGE_VERSION.split(".")[0]
IMAGE_SERVE_ROOT = "/tmp/doa-test-server"
IMAGE_REL_PATH = "networkfirmware/SONiC-{}/sonic-mellanox-{}.bin".format(
    IMAGE_MAJOR, IMAGE_VERSION
)
FAKE_IMAGE_SIZE_KB = 256


def pytest_addoption(parser):
    parser.addoption(
        "--device-ops-agent-image",
        action="store",
        default=None,
        help="Full image URL for device-ops-agent"
    )
    parser.addoption(
        "--sonic-image-url",
        action="store",
        default=None,
        help="URL to a real SONiC image for upgrade tests. "
             "The image will be downloaded to vmhost and served via a "
             "local HTTP server to simulate production upgrade flow."
    )
    parser.addoption(
        "--sonic-image-version",
        action="store",
        default=None,
        help="Optional image version string (e.g. 202505.01) to pass to "
             "TriggerUpgrade. If not provided, the version is auto-detected "
             "from the downloaded image file."
    )
    parser.addoption(
        "--firmware-profile",
        action="store",
        default=None,
        help="Firmware profile string (e.g. SONiC-Arista-7050-LeafRouter) "
             "to pass to TriggerUpgrade. Determines the platform name and "
             "extension for the image filename the agent will request."
    )


# ---------------------------------------------------------------------------
# Module-scoped fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def generate_device_ops_agent_certs(
    duthosts, enum_rand_one_per_hwsku_hostname
):
    """Generate TLS certs for device-ops-agent on the DUT.

    Copies gen-server-cert.sh to the DUT and runs it to mint a fresh
    server certificate signed by the on-disk dsmsroot CA. Certs are
    written to /etc/sonic/telemetry which is already bind-mounted into
    the container.

    After minting, restarts the agent container so it picks up the new
    cert (the agent loads TLS certs once at process start; no hot-reload).
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    logger.info("Copying gen-server-cert.sh to DUT")
    duthost.copy(src=GEN_CERT_SCRIPT, dest=REMOTE_SCRIPT_PATH, mode="0755")

    logger.info("Running gen-server-cert.sh on DUT")
    cert_result = duthost.shell(
        "sudo bash {}".format(REMOTE_SCRIPT_PATH),
        module_ignore_errors=True,
    )
    if cert_result.get("rc", 1) != 0:
        pytest.fail(
            "gen-server-cert.sh failed: {}".format(
                cert_result.get("stderr", "")
            )
        )
    logger.info("Certs generated: %s", cert_result.get("stdout", ""))

    # Restart the agent container so it loads the freshly minted cert.
    # The cert is bind-mounted from /etc/sonic/telemetry (read-only),
    # so a container restart is sufficient — no image rebuild needed.
    logger.info("Restarting %s to pick up new TLS cert", CONTAINER_NAME)
    duthost.shell(
        "docker restart {}".format(CONTAINER_NAME),
        module_ignore_errors=True,
    )
    # Wait for the agent to become responsive with the new cert
    time.sleep(5)
    deadline = time.time() + 30
    while time.time() < deadline:
        check = duthost.shell(
            "docker ps --filter name={} --filter status=running -q".format(CONTAINER_NAME),
            module_ignore_errors=True,
        )
        if check.get("stdout", "").strip():
            break
        time.sleep(2)
    else:
        pytest.fail("{} did not come back up after cert restart".format(CONTAINER_NAME))

    yield


@pytest.fixture(scope="module", autouse=True)
def prepare_grpcurl_client_key(
    duthosts, enum_rand_one_per_hwsku_hostname,
    generate_device_ops_agent_certs,
):
    """Make the dsmsroot client key readable for grpcurl.

    dsmsroot.key is 0600 root:root. Copy to a temp path so grpcurl can
    read it without root.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    duthost.shell(
        "sudo cp {src} {dst} && sudo chmod 0644 {dst}".format(
            src=CLIENT_KEY_SRC, dst=CLIENT_KEY_TMP
        )
    )
    yield
    duthost.shell(
        "rm -f {}".format(CLIENT_KEY_TMP), module_ignore_errors=True
    )


@pytest.fixture(scope="module")
def check_grpcurl(duthosts, enum_rand_one_per_hwsku_hostname, ptfhost):
    """Ensure grpcurl is installed on the DUT.

    Strategy:
    1. If already on DUT, do nothing.
    2. Try to copy from PTF container (which typically has grpcurl pre-installed).
    3. Skip if grpcurl cannot be provisioned.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    # 1. Already installed on DUT?
    check = duthost.shell("which grpcurl", module_ignore_errors=True)
    if check["rc"] == 0:
        return

    # 2. Try copying from PTF container
    ptf_check = ptfhost.shell("which grpcurl", module_ignore_errors=True)
    if ptf_check["rc"] == 0:
        ptf_grpcurl_path = ptf_check["stdout"].strip()
        # Fetch from PTF to local (sonic-mgmt container)
        local_tmp = "/tmp/grpcurl_from_ptf"
        ptfhost.fetch(src=ptf_grpcurl_path, dest=local_tmp, flat=True)
        # Copy from local to DUT
        duthost.copy(src=local_tmp, dest="/usr/local/bin/grpcurl", mode="0755")
        os.remove(local_tmp)
        # Verify
        verify = duthost.shell("grpcurl --version", module_ignore_errors=True)
        if verify["rc"] == 0:
            return

    pytest.skip("grpcurl not available on DUT or PTF container")


@pytest.fixture(scope="module")
def check_gnoi_socket(duthosts, enum_rand_one_per_hwsku_hostname):
    """Skip tests if the gNOI UDS socket is not accessible from the DOA container.

    The device-ops-agent uses gNOI File.TransferToRemote via a Unix domain socket
    (default /var/run/gnmi/gnmi.sock). If the socket isn't mounted into the DOA
    container, preload/upgrade operations will fail immediately.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    result = duthost.shell(
        "docker exec {} test -S /var/run/gnmi/gnmi.sock".format(CONTAINER_NAME),
        module_ignore_errors=True,
    )
    if result["rc"] != 0:
        pytest.skip(
            "gNOI socket /var/run/gnmi/gnmi.sock not accessible in {} container; "
            "ensure the volume mount is configured".format(CONTAINER_NAME)
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def grpcurl(duthost, method, data=None):
    """Call a gRPC method on the device-ops-agent via mTLS.

    Returns the parsed JSON response dict on success.
    Raises AssertionError on gRPC failure.
    """
    result = grpcurl_raw(duthost, method, data)
    assert result["rc"] == 0, (
        "grpcurl {} failed (rc={}): {}".format(
            method, result["rc"],
            result.get("stderr", result.get("stdout", "")),
        )
    )
    stdout = result["stdout"].strip()
    if not stdout or stdout == "{}":
        return {}
    return json.loads(stdout)


def grpcurl_raw(duthost, method, data=None):
    """Call a gRPC method and return the raw shell result dict."""
    cmd = (
        "grpcurl"
        " -cacert {ca}"
        " -cert {cert}"
        " -key {key}"
    ).format(ca=CA_CRT, cert=CA_CRT, key=CLIENT_KEY_TMP)
    if data is not None:
        escaped = json.dumps(data).replace("'", "'\\''")
        cmd += " -d '{}'".format(escaped)
    cmd += " {} sonic.deviceops.v1.DeviceOps/{}".format(AGENT_ADDR, method)
    return duthost.shell(cmd, module_ignore_errors=True)


def poll_preload_status(duthost, target_states=None, timeout=120, interval=3):
    """Poll GetPreloadImageStatus until a terminal state is reached.

    Returns parsed OperationStatus JSON dict.
    Raises TimeoutError if deadline is exceeded.
    """
    if target_states is None:
        target_states = {"SUCCEEDED", "FAILED"}
    deadline = time.time() + timeout
    last_status = {}
    while time.time() < deadline:
        result = grpcurl_raw(duthost, "GetPreloadImageStatus", {})
        if result["rc"] == 0 and result["stdout"].strip():
            last_status = json.loads(result["stdout"])
            state = last_status.get("state", "")
            if state in target_states:
                return last_status
        time.sleep(interval)
    raise TimeoutError(
        "Preload status did not reach {} within {}s. Last: {}".format(
            target_states, timeout, last_status
        )
    )


def wait_for_no_inflight(duthost, timeout=120, interval=3):
    """Wait until no preload operation is in-flight (RUNNING/PENDING)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = grpcurl_raw(duthost, "GetPreloadImageStatus", {})
        if result["rc"] == 0:
            stdout = result["stdout"].strip()
            if not stdout or stdout == "{}":
                return
            status = json.loads(stdout)
            state = status.get("state", "")
            if state not in ("RUNNING", "PENDING"):
                return
        time.sleep(interval)
    raise TimeoutError(
        "Preload still in-flight after {}s".format(timeout)
    )


def _agent_supports_env_hosts(duthost):
    """Detect if the agent reads IMAGE_SERVER_HOSTS from env (PR 15973253+).

    Older agents require image_server_ips on the request and return
    'image_server_ips required' when it's missing. Newer agents return
    'IMAGE_SERVER_HOSTS' or 'no image servers configured' instead.
    """
    result = grpcurl_raw(duthost, "TriggerPreloadImage", {
        "image_version": "__detect__",
    })
    output = result.get("stderr", "") + result.get("stdout", "")
    # Old agent: "image_server_ips required"
    # New agent: "image_version required" (won't hit this) or
    #            "no image servers configured: set IMAGE_SERVER_HOSTS"
    if "image_server_ips required" in output:
        return False
    return True


# ---------------------------------------------------------------------------
# Agent container restart with IMAGE_SERVER_HOSTS
# ---------------------------------------------------------------------------

def _restart_agent_with_image_server_hosts(duthost, image_server_hosts, path_prefix="/networkfirmware/"):
    """Restart the device-ops-agent container with IMAGE_SERVER_HOSTS env set.

    After Dawei's PR 15973253, the agent sources image-server hosts from
    the IMAGE_SERVER_HOSTS env instead of from the gRPC request field.
    This helper restarts the agent with the correct env so tests can
    exercise the preload/upgrade workflows against the test HTTP server.
    """
    # Capture the current image tag so we can restart with the same image.
    # Use jq to avoid Ansible/Jinja2 conflicts with Go template syntax.
    inspect_result = duthost.shell(
        "docker inspect {} | python3 -c \"import sys,json; "
        "print(json.load(sys.stdin)[0]['Config']['Image'])\"".format(CONTAINER_NAME),
        module_ignore_errors=True,
    )
    if inspect_result.get("rc", 1) != 0 or not inspect_result["stdout"].strip():
        pytest.fail(
            "Cannot inspect running {} container to get image tag: {}".format(
                CONTAINER_NAME, inspect_result.get("stderr", "")
            )
        )
    image_tag = inspect_result["stdout"].strip()

    # Capture existing env vars we need to preserve
    env_result = duthost.shell(
        "docker inspect {} | python3 -c \"import sys,json; "
        "envs=json.load(sys.stdin)[0]['Config'].get('Env',[]); "
        "print('\\n'.join(envs))\"".format(CONTAINER_NAME),
        module_ignore_errors=True,
    )
    existing_env = {}
    if env_result.get("rc") == 0:
        for line in env_result["stdout"].strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                existing_env[k] = v

    # Capture existing volume mounts
    mounts_result = duthost.shell(
        "docker inspect {} | python3 -c \""
        "import sys,json; mounts=json.load(sys.stdin)[0].get('Mounts',[]); "
        "parts=[]; "
        "[parts.append('-v '+m['Source']+':'+m['Destination']"
        "+(':ro' if m.get('Mode')=='ro' else '')) for m in mounts]; "
        "print(' '.join(parts))\"".format(CONTAINER_NAME),
        module_ignore_errors=True,
    )
    volume_args = mounts_result["stdout"].strip() if mounts_result.get("rc") == 0 else ""

    # Override IMAGE_SERVER_HOSTS and PATH_PREFIX
    existing_env["IMAGE_SERVER_HOSTS"] = image_server_hosts
    existing_env["IMAGE_SERVER_PATH_PREFIX"] = path_prefix

    # Build env flags
    env_flags = " ".join(
        "-e {}='{}'".format(k, v) for k, v in existing_env.items()
        if k not in ("PATH", "HOME", "HOSTNAME")
    )

    # Stop and remove old container
    duthost.shell("docker rm -f {} || true".format(CONTAINER_NAME))

    # Start new container with same image, volumes, and updated env
    run_cmd = (
        "docker run -d --name {name} --restart unless-stopped --network host "
        "{volumes} {env} {image}"
    ).format(
        name=CONTAINER_NAME,
        volumes=volume_args,
        env=env_flags,
        image=image_tag,
    )
    logger.info("Restarting agent: %s", run_cmd)
    run_result = duthost.shell(run_cmd, module_ignore_errors=True)
    if run_result.get("rc", 1) != 0:
        pytest.fail(
            "Failed to restart {}: {}".format(
                CONTAINER_NAME, run_result.get("stderr", "")
            )
        )

    # Wait for agent to become healthy (gRPC responsive)
    time.sleep(5)
    deadline = time.time() + 30
    while time.time() < deadline:
        check = grpcurl_raw(duthost, "GetPreloadImageStatus", {})
        if check.get("rc") == 0:
            logger.info("Agent restarted and healthy with IMAGE_SERVER_HOSTS=%s", image_server_hosts)
            return
        time.sleep(2)
    pytest.fail("Agent did not become responsive within 30s after restart")


@pytest.fixture(scope="module")
def restart_agent_for_local_image_server(duthosts, enum_rand_one_per_hwsku_hostname, image_server):
    """Restart the agent with IMAGE_SERVER_HOSTS pointing at the local test HTTP server.

    On older agents that don't support IMAGE_SERVER_HOSTS, this is a no-op
    and yields False so tests know to pass image_server_ips on the request.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    if _agent_supports_env_hosts(duthost):
        _restart_agent_with_image_server_hosts(
            duthost, image_server["image_server_ip"]
        )
        yield True
    else:
        logger.info("Agent does not support IMAGE_SERVER_HOSTS env; skipping restart")
        yield False


@pytest.fixture(scope="module")
def restart_agent_for_real_image_server(duthosts, enum_rand_one_per_hwsku_hostname, real_image_server):
    """Restart the agent with IMAGE_SERVER_HOSTS pointing at vmhost HTTP server.

    On older agents, yields False so tests pass image_server_ips on the request.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    if _agent_supports_env_hosts(duthost):
        _restart_agent_with_image_server_hosts(
            duthost, real_image_server["image_server_ip"]
        )
        yield True
    else:
        logger.info("Agent does not support IMAGE_SERVER_HOSTS env; skipping restart")
        yield False


# ---------------------------------------------------------------------------
# Image server fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def image_server(duthosts, enum_rand_one_per_hwsku_hostname):
    """Start a temporary HTTP image server on the DUT.

    Serves a fake SONiC image at the URL path the preload workflow
    expects:  /networkfirmware/SONiC-<MAJOR>/sonic-mellanox-<VERSION>.bin

    Yields a dict with server metadata (port, version, sha256, pid).
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    target_dir = "{}/{}".format(
        IMAGE_SERVE_ROOT,
        os.path.dirname(IMAGE_REL_PATH),
    )
    target_file = "{}/{}".format(IMAGE_SERVE_ROOT, IMAGE_REL_PATH)

    # Create directory structure mirroring ANM repo layout
    duthost.shell("mkdir -p {}".format(target_dir))

    # Create a deterministic fake image
    duthost.shell(
        "head -c {size} < /dev/urandom > {path}".format(
            size=FAKE_IMAGE_SIZE_KB * 1024, path=target_file
        )
    )

    # Record sha256 for later verification
    sha_result = duthost.shell("sha256sum {}".format(target_file))
    sha256 = sha_result["stdout"].strip().split()[0]
    logger.info("Fake image sha256: %s", sha256)

    # Check port is free
    port_check = duthost.shell(
        "ss -lnt sport = :{} | tail -n +2".format(IMAGE_SERVER_PORT),
        module_ignore_errors=True,
    )
    if port_check.get("stdout", "").strip():
        pytest.fail(
            "Port {} already in use on DUT: {}".format(
                IMAGE_SERVER_PORT, port_check["stdout"]
            )
        )

    # Start HTTP server in background
    duthost.shell(
        "cd {root} && nohup python3 -m http.server"
        " --bind 0.0.0.0 {port}"
        " > /tmp/doa-test-httpd.log 2>&1 &"
        " echo $!".format(root=IMAGE_SERVE_ROOT, port=IMAGE_SERVER_PORT)
    )
    time.sleep(2)

    # Grab the PID
    pid_result = duthost.shell(
        "lsof -ti :{} || true".format(IMAGE_SERVER_PORT),
        module_ignore_errors=True,
    )
    pid = pid_result["stdout"].strip().split("\n")[0] if pid_result["stdout"].strip() else ""
    logger.info("Image server started: port=%s, pid=%s", IMAGE_SERVER_PORT, pid)

    # Sanity: verify the server responds
    curl_check = duthost.shell(
        "curl -sf -o /dev/null http://127.0.0.1:{}/{}".format(
            IMAGE_SERVER_PORT, IMAGE_REL_PATH
        ),
        module_ignore_errors=True,
    )
    if curl_check.get("rc", 1) != 0:
        pytest.fail(
            "Image server not responding at http://127.0.0.1:{}/{}".format(
                IMAGE_SERVER_PORT, IMAGE_REL_PATH
            )
        )

    yield {
        "port": IMAGE_SERVER_PORT,
        "version": IMAGE_VERSION,
        "sha256": sha256,
        "pid": pid,
        "image_server_ip": "127.0.0.1:{}".format(IMAGE_SERVER_PORT),
    }

    # Teardown: kill server, clean up files
    if pid:
        duthost.shell(
            "kill {} 2>/dev/null || true".format(pid),
            module_ignore_errors=True,
        )
    duthost.shell(
        "rm -rf {} /tmp/doa-test-httpd.log".format(IMAGE_SERVE_ROOT),
        module_ignore_errors=True,
    )


@pytest.fixture(scope="function")
def clean_preload_state(duthosts, enum_rand_one_per_hwsku_hostname):
    """Ensure no preload operation is in-flight before starting a test."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    wait_for_no_inflight(duthost, timeout=180)
    yield
    # Clean up downloaded file after each test
    duthost.shell(
        "sudo rm -f /tmp/sonic-mellanox-*.bin",
        module_ignore_errors=True,
    )


# ---------------------------------------------------------------------------
# Upgrade API helpers and fixtures
# ---------------------------------------------------------------------------

def poll_upgrade_status(duthost, target_states=None, timeout=300, interval=5):
    """Poll GetUpgradeStatus until a terminal state is reached.

    Returns parsed OperationStatus JSON dict.
    Raises TimeoutError if deadline is exceeded.
    """
    if target_states is None:
        target_states = {"SUCCEEDED", "FAILED"}
    deadline = time.time() + timeout
    last_status = {}
    while time.time() < deadline:
        result = grpcurl_raw(duthost, "GetUpgradeStatus", {})
        if result["rc"] == 0 and result["stdout"].strip():
            last_status = json.loads(result["stdout"])
            state = last_status.get("state", "")
            if state in target_states:
                return last_status
        time.sleep(interval)
    raise TimeoutError(
        "Upgrade status did not reach {} within {}s. Last: {}".format(
            target_states, timeout, last_status
        )
    )


def wait_for_no_upgrade_inflight(duthost, timeout=300, interval=5):
    """Wait until no upgrade operation is in-flight (RUNNING/PENDING)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = grpcurl_raw(duthost, "GetUpgradeStatus", {})
        if result["rc"] == 0:
            stdout = result["stdout"].strip()
            if not stdout or stdout == "{}":
                return
            status = json.loads(stdout)
            state = status.get("state", "")
            if state not in ("RUNNING", "PENDING"):
                return
        else:
            # If the method is unimplemented, there's nothing in-flight
            output = result.get("stderr", "") + result.get("stdout", "")
            if "Unimplemented" in output:
                return
        time.sleep(interval)
    raise TimeoutError(
        "Upgrade still in-flight after {}s".format(timeout)
    )


def _check_upgrade_api_supported(duthost):
    """Check if the agent supports the Upgrade API. Returns True/False."""
    result = grpcurl_raw(duthost, "GetUpgradeStatus", {})
    output = result.get("stderr", "") + result.get("stdout", "")
    if "Unimplemented" in output:
        return False
    return True


@pytest.fixture(scope="module")
def check_upgrade_api(duthosts, enum_rand_one_per_hwsku_hostname):
    """Skip upgrade tests if the agent doesn't support the Upgrade API."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    if not _check_upgrade_api_supported(duthost):
        pytest.skip(
            "Agent does not support Upgrade API (GetUpgradeStatus returned Unimplemented)"
        )


@pytest.fixture(scope="function")
def clean_upgrade_state(duthosts, enum_rand_one_per_hwsku_hostname):
    """Ensure no upgrade operation is in-flight before starting a test."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    wait_for_no_upgrade_inflight(duthost, timeout=300)
    yield


# ---------------------------------------------------------------------------
# Image path resolver (Python port of firmware.Resolve + imageurl.Resolve)
# ---------------------------------------------------------------------------

# Known vendors mapped from profile parsing
_KNOWN_VENDORS = {
    "arista", "mellanox", "cisco", "nokia",
    "celestica", "dellemc", "force10", "nexus",
    "broadcom", "marvell",
}

# Arista slim profiles (hardcoded, no new additions)
_ARISTA_SLIM_PROFILES = {
    "SONiC-Arista-7050-LeafRouter",
    "SONiC-Arista-7050-LeafRouter-SmallDisk",
    "SONiC-Arista-7050-LeafRouter-Storage-Backend",
    "SONiC-Arista-7050-ToRRouter",
    "SONiC-Arista-7050-ToRRouter-Storage",
    "SONiC-Arista-7050-ToRRouter-Storage-Backend",
    "SONiC-Arista-7060-LeafRouter",
    "SONiC-Arista-7060-ToRRouter",
    "SONiC-Arista-7060-ToRRouter-Storage",
}


def _parse_firmware_profile(firmware_profile):
    """Parse firmware profile into (vendor, sku, deployment).

    Mirrors Go firmware.ParseProfile logic.
    """
    if not firmware_profile:
        return "", "", ""

    s = firmware_profile
    s = s.removeprefix("SONiC-SiriusBuild-")
    s = s.removeprefix("SONiC-")

    segments = s.split("-")
    if not segments:
        return "", "", ""

    vendor = ""
    idx = 0

    first_lower = segments[0].lower()
    if first_lower in _KNOWN_VENDORS:
        vendor = first_lower
        idx = 1
    elif first_lower.startswith("8800") or first_lower.startswith("88"):
        vendor = "cisco"
    elif first_lower.startswith("nh"):
        vendor = "nokia"

    # Deployment keywords
    deployment_exact = {"bt0", "bt1", "ut2", "dual", "storage", "backend", "libra", "nebius"}
    deployment_last_only = {"lc", "sup"}
    deployment_substring = [
        "torrouter", "leafrouter", "spinerouter", "smartswitch", "filterleaf"
    ]

    sku_parts = []
    deploy_parts = []
    in_deployment = False
    last_idx = len(segments) - 1

    for i in range(idx, len(segments)):
        seg_lower = segments[i].lower()
        is_last = (i == last_idx)
        if not in_deployment:
            # Check if this segment starts deployment
            if seg_lower in deployment_exact:
                in_deployment = True
            elif is_last and seg_lower in deployment_last_only:
                in_deployment = True
            else:
                for kw in deployment_substring:
                    if kw in seg_lower:
                        in_deployment = True
                        break
        if in_deployment:
            deploy_parts.append(segments[i])
        else:
            sku_parts.append(segments[i])

    sku = "-".join(sku_parts)
    deployment = "-".join(deploy_parts)
    return vendor, sku, deployment


def _resolve_platform(vendor, sku, deployment, date):
    """Resolve platform name and extension from vendor/sku/deployment/date.

    Returns (platform_name, extension).
    Mirrors Go vendor handler logic.
    """
    sku_lower = sku.lower()
    deploy_lower = deployment.lower()

    if vendor == "mellanox":
        if "smartswitch" in sku_lower or "smartswitch" in deploy_lower:
            return "mellanox-smartswitch", "bin"
        return "mellanox", "bin"

    if vendor == "arista":
        if sku_lower.startswith("7280") or sku_lower.startswith("7800") or sku_lower.startswith("7808"):
            return "aboot-broadcom-dnx", "swi"
        # Check slim profiles
        profile_name = "SONiC-Arista-" + sku
        if deployment:
            profile_name += "-" + deployment
        if profile_name in _ARISTA_SLIM_PROFILES:
            if date >= "20201231":
                return "aboot-broadcom-slim", "swi"
            return "aboot-broadcom", "swi"
        return "aboot-broadcom", "swi"

    if vendor == "cisco":
        if "smartswitch" in deploy_lower and date < "20250510":
            return "cisco-8000-smartswitch", "bin"
        if "20220531" <= date < "20230531":
            return "cisco-8000-nosec", "bin"
        return "cisco-8000", "bin"

    if vendor == "nokia":
        if sku_lower.startswith("7215"):
            if date >= "20250510":
                return "marvell-prestera-armhf", "bin"
            return "marvell-armhf", "bin"
        return "broadcom-dnx", "bin"

    if vendor == "nexus":
        if sku_lower.startswith("n3164"):
            return "nbi-n3164-broadcom", "bin"
        if sku_lower.startswith("n3132gx"):
            return "nbi-broadcom", "bin"
        return "broadcom", "bin"

    if vendor in ("broadcom", "celestica", "dellemc", "force10"):
        # Celestica E1031 special case
        if vendor == "celestica" and sku_lower.startswith("e1031"):
            if date >= "20201231":
                return "broadcom-slim", "bin"
            return "broadcom", "bin"
        # Broadcom with aboot
        if vendor == "broadcom":
            has_aboot = "aboot" in sku_lower or "aboot" in deploy_lower
            has_dnx = "dnx" in sku_lower or "dnx" in deploy_lower
            has_slim = "slim" in sku_lower or "slim" in deploy_lower
            if has_aboot:
                if has_dnx:
                    return "aboot-broadcom-dnx", "swi"
                if has_slim:
                    return "aboot-broadcom-slim", "swi"
                return "aboot-broadcom", "swi"
            if has_dnx:
                return "broadcom-dnx", "bin"
            if has_slim:
                return "broadcom-slim", "bin"
        return "broadcom", "bin"

    # Default fallback (unknown vendor) -> mellanox
    return "mellanox", "bin"


def resolve_image_path(image_version, firmware_profile=""):
    """Resolve the relative HTTP path and filename for a SONiC image.

    Mirrors Go imageurl.Resolve logic.

    Args:
        image_version: e.g. "202505.01" or "SONiC.202505.01"
        firmware_profile: e.g. "SONiC-Arista-7050-LeafRouter"

    Returns:
        (rel_path, filename) where rel_path is like
        "SONiC-202505/sonic-aboot-broadcom-202505.01.swi"
    """
    version = image_version
    version = version.removeprefix("SONiC.")

    # Detect .azd suffix
    azd = version.endswith(".azd")
    if azd:
        version = version.removesuffix(".azd")

    # Extract date (everything before first dot)
    dot_idx = version.find(".")
    date = version[:dot_idx] if dot_idx >= 0 else version

    # Resolve platform
    vendor, sku, deployment = _parse_firmware_profile(firmware_profile)
    platform_name, extension = _resolve_platform(vendor, sku, deployment, date)

    # Construct filename
    suffix = ".azd" if azd else ""
    filename = "sonic-{}-{}{}.{}".format(platform_name, version, suffix, extension)

    rel_path = "SONiC-{}/{}".format(date, filename)
    return rel_path, filename


# ---------------------------------------------------------------------------
# Real image server fixture (hosted on vmhost, serves actual SONiC image)
# ---------------------------------------------------------------------------

REAL_IMAGE_SERVE_ROOT = "/tmp/doa-real-image-server"
REAL_IMAGE_SERVER_PORT = 8200


@pytest.fixture(scope="module")
def real_image_server(request, duthosts, enum_rand_one_per_hwsku_hostname, vmhost):
    """Download a real SONiC image to vmhost and serve it via HTTP.

    Requires --sonic-image-url and --firmware-profile CLI options.
    The image version is auto-detected from the image file itself
    (same as sonic-utilities get_binary_image_version).

    The image is served at the URL path the upgrade workflow expects:
      /networkfirmware/SONiC-<date>/<filename>

    The filename is determined by resolve_image_path(version, profile).
    The HTTP server runs on the vmhost so it survives DUT reboots during
    the upgrade workflow (W4).

    Yields a dict with server metadata (port, version, firmware_profile,
    sha256, pid, image_server_ip).
    """
    image_url = request.config.getoption("--sonic-image-url")
    image_version_opt = request.config.getoption("--sonic-image-version")
    firmware_profile = request.config.getoption("--firmware-profile") or ""

    if not image_url:
        pytest.skip(
            "Real image upgrade test requires --sonic-image-url option"
        )

    if not vmhost:
        pytest.skip("vmhost fixture not available in this testbed")

    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    # Download the real image to a temp location on vmhost first
    tmp_image_path = "/tmp/doa-downloaded-image"
    logger.info("Downloading real SONiC image to vmhost: %s", image_url)
    dl_result = vmhost.shell(
        "curl -fSL --retry 3 --retry-delay 5 -o {path} '{url}'".format(
            path=tmp_image_path, url=image_url
        ),
        module_ignore_errors=True,
    )
    if dl_result.get("rc", 1) != 0:
        pytest.fail(
            "Failed to download image from {}: {}".format(
                image_url, dl_result.get("stderr", "")
            )
        )

    # Determine image version: use --sonic-image-version if provided,
    # otherwise extract from the image file (same as sonic-utilities)
    if image_version_opt:
        image_version = image_version_opt
        logger.info("Using provided image version: %s", image_version)
    else:
        version_result = vmhost.shell(
            "cat -v {path} | grep -m 1 '^image_version' "
            "| sed -n 's/^image_version=\"\\(.*\\)\"$/\\1/p'".format(
                path=tmp_image_path
            ),
            module_ignore_errors=True,
        )
        if version_result.get("rc", 1) != 0 or not version_result["stdout"].strip():
            pytest.fail(
                "Failed to extract image_version from {}: {}".format(
                    image_url, version_result.get("stderr", "")
                )
            )
        image_version = version_result["stdout"].strip()
        logger.info("Extracted image version from image: %s", image_version)

    # Resolve the path the agent will request
    image_rel_path, image_filename = resolve_image_path(
        image_version, firmware_profile
    )
    # Full path under the HTTP server root: networkfirmware/<rel_path>
    rel_path = "networkfirmware/{}".format(image_rel_path)
    target_dir = "{}/{}".format(
        REAL_IMAGE_SERVE_ROOT, os.path.dirname(rel_path)
    )
    target_file = "{}/{}".format(REAL_IMAGE_SERVE_ROOT, rel_path)

    logger.info(
        "Resolved image path: rel_path=%s filename=%s",
        rel_path, image_filename,
    )

    # Create directory structure and move the image to the correct path
    vmhost.shell("mkdir -p {}".format(target_dir))
    vmhost.shell("mv {} {}".format(tmp_image_path, target_file))

    # Record sha256 for verification
    sha_result = vmhost.shell("sha256sum {}".format(target_file))
    sha256 = sha_result["stdout"].strip().split()[0]
    logger.info("Real image sha256: %s", sha256)

    # Check port is free on vmhost
    port_check = vmhost.shell(
        "ss -lnt sport = :{} | tail -n +2".format(REAL_IMAGE_SERVER_PORT),
        module_ignore_errors=True,
    )
    if port_check.get("stdout", "").strip():
        pytest.fail(
            "Port {} already in use on vmhost: {}".format(
                REAL_IMAGE_SERVER_PORT, port_check["stdout"]
            )
        )

    # Start HTTP server on vmhost in background
    vmhost.shell(
        "cd {root} && nohup python3 -m http.server"
        " --bind 0.0.0.0 {port}"
        " > /tmp/doa-real-httpd.log 2>&1 &"
        " echo $!".format(root=REAL_IMAGE_SERVE_ROOT, port=REAL_IMAGE_SERVER_PORT)
    )
    time.sleep(2)

    # Grab the PID on vmhost
    pid_result = vmhost.shell(
        "lsof -ti :{} || true".format(REAL_IMAGE_SERVER_PORT),
        module_ignore_errors=True,
    )
    pid = (
        pid_result["stdout"].strip().split("\n")[0]
        if pid_result["stdout"].strip()
        else ""
    )

    # Get vmhost IP reachable from DUT
    vmhost_ip = vmhost.mgmt_ip
    logger.info(
        "Real image server started on vmhost: ip=%s port=%s pid=%s",
        vmhost_ip, REAL_IMAGE_SERVER_PORT, pid,
    )

    # Sanity: verify the DUT can reach the image server on vmhost
    curl_check = duthost.shell(
        "curl -sf -o /dev/null http://{}:{}/{}".format(
            vmhost_ip, REAL_IMAGE_SERVER_PORT, rel_path
        ),
        module_ignore_errors=True,
    )
    if curl_check.get("rc", 1) != 0:
        pytest.fail(
            "DUT cannot reach image server at http://{}:{}/{}".format(
                vmhost_ip, REAL_IMAGE_SERVER_PORT, rel_path
            )
        )

    yield {
        "port": REAL_IMAGE_SERVER_PORT,
        "version": image_version,
        "firmware_profile": firmware_profile,
        "sha256": sha256,
        "pid": pid,
        "image_server_ip": "{}:{}".format(vmhost_ip, REAL_IMAGE_SERVER_PORT),
    }

    # Teardown: kill server on vmhost, clean up files
    if pid:
        vmhost.shell(
            "kill {} 2>/dev/null || true".format(pid),
            module_ignore_errors=True,
        )
    vmhost.shell(
        "rm -rf {} /tmp/doa-real-httpd.log".format(REAL_IMAGE_SERVE_ROOT),
        module_ignore_errors=True,
    )
