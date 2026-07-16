"""Fixtures for end-to-end aznetsec-agent (aznsa) telemetry testing.

These fixtures stand up a self-signed HTTPS listener on the ptfhost, push the CA
certificate to the DUT so the container trusts the listener, and reconfigure the
running aznsa container to report telemetry to the listener via the
AZNSA_TELEMETRY_URL environment variable.
"""
import ipaddress
import json
import logging
import os

import pytest

from tests.aznsa.aznsa_helpers import CONTAINER_NAME, get_aznsa_container_image, is_aznsa_container_running
from tests.common.cert_utils import TlsCertificateGenerator
from tests.common.helpers.assertions import pytest_assert as pt_assert
from tests.common.utilities import wait_until

logger = logging.getLogger(__name__)

DUT_CERT_DIR = "/etc/sonic/aznsa/certs"
DUT_CA_CERT = "{}/ca.crt".format(DUT_CERT_DIR)

# Env var the container reads for the telemetry endpoint.
TELEMETRY_URL_ENV = "AZNSA_TELEMETRY_URL"

# Exporter mode required for the container to POST events to AZNSA_TELEMETRY_URL.
EXPORTER_ENV = "AZNSA_EXPORTER"
EXPORTER_MODE = "HTTP"

# Source of truth for the container's deployment parameters.
PARAMETERS_JSON = os.path.join(
    os.path.dirname(__file__), "..", "container_upgrade", "parameters.json"
)

# Listener assets deployed to the ptfhost.
LISTENER_SCRIPT = os.path.join(os.path.dirname(__file__), "aznsa_telemetry_listener.py")
# Base directory on the ptfhost under which a unique per-run work dir is created.
LISTENER_WORK_ROOT = "/tmp/aznsa_listener"


class PtfEventStore(object):
    """Read-only view of telemetry events collected by the ptfhost listener.

    Events are persisted on the ptfhost (one JSON object per line); this reads
    them back over SSH so the test process can inspect what the DUT reported.
    """

    def __init__(self, ptfhost, events_file):
        self._ptfhost = ptfhost
        self._events_file = events_file

    def all(self):
        out = self._ptfhost.shell(
            "cat {}".format(self._events_file),
            module_ignore_errors=True,
            verbose=False,
        )
        events = []
        for line in out.get("stdout", "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                logger.warning("Skipping malformed event line: %r", line)
        return events

    def find(self, predicate):
        return [e for e in self.all() if predicate(e)]

    def clear(self):
        self._ptfhost.shell(
            "truncate -s 0 {}".format(self._events_file),
            module_ignore_errors=True,
            verbose=False,
        )


class ListenerController(object):
    """Manage the lifecycle of the ptfhost HTTPS telemetry listener."""

    def __init__(self, ptfhost, work_dir):
        self._ptfhost = ptfhost
        self.script = "{}/listener.py".format(work_dir)
        self.server_crt = "{}/server.crt".format(work_dir)
        self.server_key = "{}/server.key".format(work_dir)
        self.events_file = "{}/events.jsonl".format(work_dir)
        self.control_file = "{}/control".format(work_dir)
        self.port_file = "{}/port".format(work_dir)
        self.pid_file = "{}/pid".format(work_dir)
        self.log_file = "{}/listener.log".format(work_dir)
        self.port = None
        self.store = PtfEventStore(ptfhost, self.events_file)

    def start(self):
        """Start the listener."""
        bind_port = self.port if self.port is not None else 0
        # Start healthy and remove any stale port file so readiness waits for
        # the new bind.
        self._ptfhost.shell(
            "rm -f {} {}".format(self.port_file, self.control_file),
            module_ignore_errors=True,
        )
        start = (
            "nohup python3 {script} --port {port} --certfile {crt} "
            "--keyfile {key} --events-file {events} --control-file {ctl} "
            "--port-file {portf} --pid-file {pidf} > {log} 2>&1 &".format(
                script=self.script,
                port=bind_port,
                crt=self.server_crt,
                key=self.server_key,
                events=self.events_file,
                ctl=self.control_file,
                portf=self.port_file,
                pidf=self.pid_file,
                log=self.log_file,
            )
        )
        self._ptfhost.shell(start, module_ignore_errors=True)

        if not wait_until(20, 2, 0, self._port_ready):
            log = self._ptfhost.shell(
                "cat {}".format(self.log_file), module_ignore_errors=True
            )
            pt_assert(
                False,
                "aznsa telemetry listener did not start on ptfhost. Log:\n"
                "{}".format(log.get("stdout", "") or log.get("stderr", "")),
            )

        self.port = int(
            self._ptfhost.shell("cat {}".format(self.port_file))["stdout"].strip()
        )
        logger.info("aznsa telemetry listener listening on ptfhost port %d", self.port)
        return self.port

    def stop(self):
        """Stop the listener."""
        self._ptfhost.shell(
            "kill $(cat {}) 2>/dev/null || true".format(self.pid_file),
            module_ignore_errors=True,
        )

        def _stopped():
            out = self._ptfhost.shell(
                "cat {}".format(self.pid_file), module_ignore_errors=True
            )
            pid = out.get("stdout", "").strip()
            if not pid:
                return True
            alive = self._ptfhost.shell(
                "kill -0 {} 2>/dev/null && echo up || echo down".format(pid),
                module_ignore_errors=True,
            )
            return alive.get("stdout", "").strip() == "down"

        wait_until(20, 2, 0, _stopped)
        logger.info("aznsa telemetry listener stopped on ptfhost")

    def fail(self, status=503):
        """Make the listener reject POSTs with an HTTP error without recording."""
        self._ptfhost.shell(
            "echo {} > {}".format(int(status), self.control_file),
            module_ignore_errors=True,
        )
        logger.info("aznsa telemetry listener now rejecting POSTs with HTTP %d", status)

    def heal(self):
        """Return the listener to accepting and recording POSTs (HTTP 200)."""
        self._ptfhost.shell(
            "rm -f {}".format(self.control_file), module_ignore_errors=True
        )
        logger.info("aznsa telemetry listener now accepting POSTs")

    def _port_ready(self):
        out = self._ptfhost.shell(
            "cat {}".format(self.port_file), module_ignore_errors=True
        )
        return bool(out.get("stdout", "").strip())


def _load_aznsa_params():
    """Return the aznetsec-agent docker run parameters from parameters.json."""
    with open(PARAMETERS_JSON) as f:
        data = json.load(f)
    return list(data["aznetsec-agent"]["parameters"])


def _format_url_host(host_ip):
    """Format a host for a URL authority, bracketing IPv6 addresses."""
    try:
        if isinstance(ipaddress.ip_address(host_ip), ipaddress.IPv6Address):
            return "[{}]".format(host_ip)
    except ValueError:
        pass
    return host_ip


def _assert_listener_reachable(duthost, host_ip, port):
    """Verify the DUT can open a TCP connection to the telemetry listener."""
    check = "timeout 5 bash -c '</dev/tcp/{}/{}'".format(host_ip, port)
    result = duthost.shell(check, module_ignore_errors=True)
    pt_assert(
        result.get("rc") == 0,
        "DUT cannot reach telemetry listener at {}:{} (rc={}). The aznsa "
        "container's telemetry POSTs will not arrive. Check routing/firewall "
        "between the DUT and the ptfhost.".format(host_ip, port, result.get("rc")),
    )
    logger.info("DUT can reach telemetry listener at %s:%d", host_ip, port)


def _recreate_container(duthost, image, extra_params):
    """Stop/remove and re-run the aznsa container with extra_params appended."""
    params = " ".join(_load_aznsa_params() + extra_params)

    duthost.shell("docker stop {}".format(CONTAINER_NAME), module_ignore_errors=True)
    duthost.shell("docker rm {}".format(CONTAINER_NAME), module_ignore_errors=True)
    run = "docker run -d {params} --name {name} {image}".format(
        params=params, name=CONTAINER_NAME, image=image
    )
    logger.info("Recreating aznsa container: %s", run)
    result = duthost.shell(run, module_ignore_errors=True)
    pt_assert(
        result.get("rc") == 0,
        "Failed to (re)run aznsa container: {}".format(
            result.get("stderr", result.get("stdout", ""))
        ),
    )
    pt_assert(
        wait_until(60, 3, 0, is_aznsa_container_running, duthost),
        "aznsa container did not reach running state after reconfigure",
    )


@pytest.fixture(scope="module")
def listener_host_ip(ptfhost):
    """Return the ptfhost management IP the DUT uses to reach the listener."""
    ptf_ip = ptfhost.mgmt_ip
    logger.info("aznsa telemetry listener host (ptfhost) IP: %s", ptf_ip)
    return ptf_ip


@pytest.fixture(scope="module")
def listener_certs(
    duthosts, enum_rand_one_per_hwsku_hostname, listener_host_ip, tmp_path_factory
):
    """Generate a self-signed cert chain and push the CA cert to the DUT."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    cert_dir = str(tmp_path_factory.mktemp("listener_certs"))

    generator = TlsCertificateGenerator(
        server_ip=listener_host_ip,
        dns_names=["localhost", "aznsa-telemetry-listener"],
        server_cn="aznsa-telemetry-listener",
    )
    generator.write_all(cert_dir)

    certs = {
        "cert_dir": cert_dir,
        "ca_crt": os.path.join(cert_dir, generator.ca_cert_name),
        "server_crt": os.path.join(cert_dir, generator.server_cert_name),
        "server_key": os.path.join(cert_dir, generator.server_key_name),
    }

    logger.info("Pushing CA cert to DUT at %s", DUT_CA_CERT)

    duthost.shell("mkdir -p {}".format(DUT_CERT_DIR))
    duthost.copy(src=certs["ca_crt"], dest=DUT_CA_CERT, mode="0644")

    yield certs

    duthost.shell("rm -rf {}".format(DUT_CERT_DIR), module_ignore_errors=True)


@pytest.fixture(scope="module")
def listener_workdir(ptfhost):
    """Provide a unique scratch dir on the ptfhost for one listener run."""
    ptfhost.shell("mkdir -p {}".format(LISTENER_WORK_ROOT))
    work_dir = ptfhost.shell(
        "mktemp -d {}/run.XXXXXX".format(LISTENER_WORK_ROOT)
    )["stdout"].strip()
    yield work_dir
    ptfhost.shell("rm -rf {}".format(work_dir), module_ignore_errors=True)


@pytest.fixture(scope="module")
def listener(ptfhost, listener_certs, listener_workdir, request):
    """Start the HTTPS telemetry listener on the ptfhost and collect events."""
    controller = ListenerController(ptfhost, listener_workdir)

    # Stage the listener script and server cert/key.
    ptfhost.copy(src=LISTENER_SCRIPT, dest=controller.script, mode="0755")
    ptfhost.copy(src=listener_certs["server_crt"], dest=controller.server_crt, mode="0644")
    ptfhost.copy(src=listener_certs["server_key"], dest=controller.server_key, mode="0600")

    # Register the stop immediately so it runs even if the listener never
    # becomes ready and the readiness assert in start() aborts setup.
    request.addfinalizer(controller.stop)

    controller.start()

    yield controller


@pytest.fixture(scope="module", autouse=True)
def aznsa_deployed(duthosts, enum_rand_one_per_hwsku_hostname):
    """Skip the module unless the aznsa container is already deployed.

    A cheap deployment gate shared by all tests; it avoids pulling in the
    telemetry listener setup just to discover the container is missing.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    image = get_aznsa_container_image(duthost)
    if image is None:
        pytest.skip(
            "aznsa container not deployed; deploy it via container_upgrade first"
        )
    return image


@pytest.fixture(scope="module")
def aznsa_configured(
    duthosts,
    enum_rand_one_per_hwsku_hostname,
    listener_host_ip,
    listener,
    aznsa_deployed,
    request,
):
    """Reconfigure the aznsa container to report telemetry to the listener."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    image = aznsa_deployed

    request.addfinalizer(lambda: _recreate_container(duthost, image, []))

    url = "https://{}:{}".format(_format_url_host(listener_host_ip), listener.port)
    extra_params = [
        "-e {}={}".format(EXPORTER_ENV, EXPORTER_MODE),
        "-e {}={}".format(TELEMETRY_URL_ENV, url),
    ]
    _recreate_container(duthost, image, extra_params)

    # Fail fast if the DUT cannot reach the ptfhost listener
    _assert_listener_reachable(duthost, listener_host_ip, listener.port)

    yield
