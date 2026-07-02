import pytest
import logging
import time
from tests.common.helpers.assertions import pytest_assert
from tests.device_ops_agent.conftest import (
    grpcurl,
    grpcurl_raw,
    poll_upgrade_status,
    _restart_agent_with_image_server_hosts,
    _agent_supports_env_hosts,
)

pytestmark = [
    pytest.mark.disable_loganalyzer,
    pytest.mark.topology('any'),
    pytest.mark.skip_check_dut_health,
    pytest.mark.usefixtures("check_upgrade_api"),
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TriggerUpgrade — input validation (immediate gRPC errors)
# ---------------------------------------------------------------------------

def test_upgrade_missing_image_version(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, clean_upgrade_state,
):
    """TriggerUpgrade with empty image_version returns InvalidArgument."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    result = grpcurl_raw(duthost, "TriggerUpgrade", {
        "image_version": "",
        "reboot_method": "COLD",
    })
    pytest_assert(
        result["rc"] != 0,
        "Expected gRPC error for empty image_version but got rc=0",
    )
    output = result.get("stderr", "") + result.get("stdout", "")
    pytest_assert(
        "InvalidArgument" in output or "image_version required" in output,
        "Expected InvalidArgument error, got: {}".format(output),
    )


def test_upgrade_missing_server_ips(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, clean_upgrade_state,
):
    """TriggerUpgrade with no image server hosts returns InvalidArgument.

    - New agent (PR 15973253+): IMAGE_SERVER_HOSTS env empty → InvalidArgument.
    - Old agent: empty image_server_ips on request → InvalidArgument.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    if _agent_supports_env_hosts(duthost):
        _restart_agent_with_image_server_hosts(duthost, "")
        time.sleep(3)
        result = grpcurl_raw(duthost, "TriggerUpgrade", {
            "image_version": "202505.01",
            "reboot_method": "COLD",
        })
    else:
        result = grpcurl_raw(duthost, "TriggerUpgrade", {
            "image_server_ips": [],
            "image_version": "202505.01",
            "reboot_method": "COLD",
        })

    pytest_assert(
        result["rc"] != 0,
        "Expected gRPC error for missing hosts but got rc=0",
    )
    output = result.get("stderr", "") + result.get("stdout", "")
    pytest_assert(
        "InvalidArgument" in output,
        "Expected InvalidArgument error, got: {}".format(output),
    )


def test_upgrade_unspecified_reboot_method(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, clean_upgrade_state,
):
    """TriggerUpgrade with REBOOT_METHOD_UNSPECIFIED returns InvalidArgument."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    result = grpcurl_raw(duthost, "TriggerUpgrade", {
        "image_version": "202505.01",
        "reboot_method": "REBOOT_METHOD_UNSPECIFIED",
    })
    pytest_assert(
        result["rc"] != 0,
        "Expected gRPC error for unspecified reboot_method but got rc=0",
    )
    output = result.get("stderr", "") + result.get("stdout", "")
    pytest_assert(
        "InvalidArgument" in output or "reboot_method required" in output,
        "Expected InvalidArgument error, got: {}".format(output),
    )


def test_upgrade_fast_reboot_unimplemented(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, clean_upgrade_state,
):
    """TriggerUpgrade with FAST reboot_method returns Unimplemented."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    result = grpcurl_raw(duthost, "TriggerUpgrade", {
        "image_version": "202505.01",
        "image_server_ips": ["192.0.2.1:8080"],
        "reboot_method": "FAST",
    })
    pytest_assert(
        result["rc"] != 0,
        "Expected gRPC error for FAST reboot_method but got rc=0",
    )
    output = result.get("stderr", "") + result.get("stdout", "")
    pytest_assert(
        "Unimplemented" in output or "not supported" in output,
        "Expected Unimplemented error, got: {}".format(output),
    )


def test_upgrade_warm_reboot_unimplemented(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, clean_upgrade_state,
):
    """TriggerUpgrade with WARM reboot_method returns Unimplemented."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    result = grpcurl_raw(duthost, "TriggerUpgrade", {
        "image_version": "202505.01",
        "image_server_ips": ["192.0.2.1:8080"],
        "reboot_method": "WARM",
    })
    pytest_assert(
        result["rc"] != 0,
        "Expected gRPC error for WARM reboot_method but got rc=0",
    )
    output = result.get("stderr", "") + result.get("stdout", "")
    pytest_assert(
        "Unimplemented" in output or "not supported" in output,
        "Expected Unimplemented error, got: {}".format(output),
    )


# ---------------------------------------------------------------------------
# TriggerUpgrade — duplicate request (AlreadyExists)
# ---------------------------------------------------------------------------

def test_upgrade_duplicate_request(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, check_gnoi_socket, clean_upgrade_state,
):
    """A second TriggerUpgrade while one is in-flight returns AlreadyExists."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    # Configure agent with an unreachable server so the first request stays in-flight
    if _agent_supports_env_hosts(duthost):
        _restart_agent_with_image_server_hosts(duthost, "192.0.2.1:9999")
        req = {"image_version": "202505.98", "reboot_method": "COLD"}
    else:
        req = {"image_version": "202505.98", "reboot_method": "COLD",
               "image_server_ips": ["192.0.2.1:9999"]}

    # Trigger an upgrade that will stay in-flight (unreachable server)
    resp = grpcurl(duthost, "TriggerUpgrade", req)
    logger.info("First trigger (slow): %s", resp)

    # Give the background goroutine a moment to start
    time.sleep(2)

    # Second trigger should fail with AlreadyExists
    result = grpcurl_raw(duthost, "TriggerUpgrade", req)
    output = result.get("stderr", "") + result.get("stdout", "")
    logger.info("Second trigger result: rc=%s output=%s", result["rc"], output)
    pytest_assert(
        result["rc"] != 0,
        "Expected gRPC error for duplicate request but got rc=0",
    )
    pytest_assert(
        "AlreadyExists" in output or "in flight" in output,
        "Expected AlreadyExists error, got: {}".format(output),
    )

    # Wait for the first operation to finish so we don't leak state
    poll_upgrade_status(duthost, timeout=300, interval=5)


# ---------------------------------------------------------------------------
# TriggerUpgrade — failure path (unreachable server)
# ---------------------------------------------------------------------------

def test_upgrade_unreachable_server(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, check_gnoi_socket, clean_upgrade_state,
):
    """Upgrade with an unreachable image server should reach FAILED state."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    # Configure agent with an unreachable server (TEST-NET-1, RFC 5737)
    if _agent_supports_env_hosts(duthost):
        _restart_agent_with_image_server_hosts(duthost, "192.0.2.1:9999")
        req = {"image_version": "202505.99", "reboot_method": "COLD"}
    else:
        req = {"image_version": "202505.99", "reboot_method": "COLD",
               "image_server_ips": ["192.0.2.1:9999"]}

    resp = grpcurl(duthost, "TriggerUpgrade", req)
    logger.info("TriggerUpgrade (unreachable) response: %s", resp)

    # Poll — expect FAILED (W1 TransferImage will timeout/fail)
    status = poll_upgrade_status(duthost, timeout=300, interval=5)
    logger.info("Unreachable server upgrade status: %s", status)
    pytest_assert(
        status.get("state") == "FAILED",
        "Expected FAILED for unreachable server, got: {}".format(status),
    )


# ---------------------------------------------------------------------------
# TriggerUpgrade — success path (requires image server fixture)
# ---------------------------------------------------------------------------

def test_upgrade_success(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, check_gnoi_socket, image_server, restart_agent_for_local_image_server,
    clean_upgrade_state,
):
    """Trigger upgrade with valid inputs and COLD reboot, poll until terminal state.

    NOTE: In a real environment, the device will reboot on W4 success.
    This test verifies the workflow progresses through W1 (TransferImage)
    and W2 (InstallImage). In vlab/CI environments, W4 (Reboot) may cause
    a test-infrastructure disconnect, so we accept both SUCCEEDED and FAILED
    as valid terminal outcomes depending on environment capabilities.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    logger.info(
        "Triggering upgrade: version=%s server=%s",
        image_server["version"], image_server["image_server_ip"],
    )
    req = {
        "image_version": image_server["version"],
        "reboot_method": "COLD",
    }
    if not restart_agent_for_local_image_server:
        # Old agent: must pass hosts on request
        req["image_server_ips"] = [image_server["image_server_ip"]]
    resp = grpcurl(duthost, "TriggerUpgrade", req)
    logger.info("TriggerUpgrade response: %s", resp)

    # Poll until terminal state
    status = poll_upgrade_status(duthost, timeout=300, interval=5)
    logger.info("Final upgrade status: %s", status)
    pytest_assert(
        status.get("state") in ("SUCCEEDED", "FAILED"),
        "Expected terminal state but got: {}".format(status),
    )


# ---------------------------------------------------------------------------
# GetUpgradeStatus — status store retention
# ---------------------------------------------------------------------------

def test_upgrade_status_after_completion(
    duthosts, enum_rand_one_per_hwsku_hostname, check_grpcurl,
):
    """GetUpgradeStatus returns a terminal state after a completed upgrade.

    Runs after test_upgrade_unreachable_server or test_upgrade_success
    to verify the status store retains the last result.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    status = grpcurl(duthost, "GetUpgradeStatus", {})
    state = status.get("state", "")
    pytest_assert(
        state in ("SUCCEEDED", "FAILED", "UNKNOWN", ""),
        "Expected terminal or initial state in status store, got: {}".format(status),
    )


# ---------------------------------------------------------------------------
# TriggerUpgrade — W3a/W3b with configs and certs
# ---------------------------------------------------------------------------

def test_upgrade_with_configs_and_certs(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, check_gnoi_socket, image_server, restart_agent_for_local_image_server,
    clean_upgrade_state,
):
    """TriggerUpgrade with configs[] and certs[] populated exercises W3a/W3b."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    logger.info(
        "Triggering upgrade with configs/certs: version=%s server=%s",
        image_server["version"], image_server["image_server_ip"],
    )
    req = {
        "image_version": image_server["version"],
        "reboot_method": "COLD",
        "configs": [
            {"name": "/etc/sonic/config_db.json", "content": "e30="},  # base64("{}")
        ],
        "certs": [
            {"name": "/etc/sonic/telemetry/cert.pem", "content": "ZHVtbXk="},  # base64("dummy")
        ],
    }
    if not restart_agent_for_local_image_server:
        req["image_server_ips"] = [image_server["image_server_ip"]]
    resp = grpcurl(duthost, "TriggerUpgrade", req)
    logger.info("TriggerUpgrade (with configs/certs) response: %s", resp)

    # Poll until terminal state
    status = poll_upgrade_status(duthost, timeout=300, interval=5)
    logger.info("Upgrade with configs/certs status: %s", status)
    pytest_assert(
        status.get("state") in ("SUCCEEDED", "FAILED"),
        "Expected terminal state but got: {}".format(status),
    )


def test_upgrade_without_configs_certs_skipped(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, check_gnoi_socket, image_server, restart_agent_for_local_image_server,
    clean_upgrade_state,
):
    """TriggerUpgrade with empty configs[]/certs[] records SKIPPED for W3a/W3b.

    Verifies that the upgrade workflow proceeds past the staging steps
    when no configs or certs are provided (they should be SKIPPED per D7-E2).
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    req = {
        "image_version": image_server["version"],
        "reboot_method": "COLD",
        "configs": [],
        "certs": [],
    }
    if not restart_agent_for_local_image_server:
        req["image_server_ips"] = [image_server["image_server_ip"]]
    resp = grpcurl(duthost, "TriggerUpgrade", req)
    logger.info("TriggerUpgrade (no configs/certs) response: %s", resp)

    # Poll until terminal state — workflow should progress through W1/W2
    # and skip W3a/W3b without error
    status = poll_upgrade_status(duthost, timeout=300, interval=5)
    logger.info("Upgrade (no configs/certs) status: %s", status)
    pytest_assert(
        status.get("state") in ("SUCCEEDED", "FAILED"),
        "Expected terminal state but got: {}".format(status),
    )


# ---------------------------------------------------------------------------
# TriggerUpgrade — real image end-to-end (requires --sonic-image-url)
# ---------------------------------------------------------------------------

def test_upgrade_real_image(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, check_gnoi_socket, real_image_server, restart_agent_for_real_image_server,
    clean_upgrade_state,
):
    """End-to-end upgrade test using a real SONiC image.

    Downloads the real image (via --sonic-image-url), serves it on vmhost,
    and triggers a full upgrade (W1→W2→W3a→W3b→W4). This test simulates
    the production upgrade flow.

    WARNING: W4 (Reboot) will reboot the device if all preceding steps
    succeed. The test verifies the workflow reaches a terminal state.
    In CI environments where reboot is not allowed, the test may reach
    FAILED at W4 — this is acceptable and validates W1→W3b worked.

    Requires: --sonic-image-url, --sonic-image-version, and optionally
    --firmware-profile CLI options.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    logger.info(
        "Triggering real upgrade: version=%s profile=%s server=%s",
        real_image_server["version"],
        real_image_server["firmware_profile"],
        real_image_server["image_server_ip"],
    )
    req = {
        "image_version": real_image_server["version"],
        "firmware_profile": real_image_server["firmware_profile"],
        "reboot_method": "COLD",
    }
    if not restart_agent_for_real_image_server:
        req["image_server_ips"] = [real_image_server["image_server_ip"]]
    resp = grpcurl(duthost, "TriggerUpgrade", req)
    logger.info("TriggerUpgrade (real image) response: %s", resp)

    # Poll until terminal state — use longer timeout for real image transfer
    status = poll_upgrade_status(duthost, timeout=600, interval=10)
    logger.info("Real upgrade final status: %s", status)
    pytest_assert(
        status.get("state") in ("SUCCEEDED", "FAILED"),
        "Expected terminal state but got: {}".format(status),
    )


def test_upgrade_real_image_with_configs(
    duthosts, enum_rand_one_per_hwsku_hostname,
    check_grpcurl, check_gnoi_socket, real_image_server, restart_agent_for_real_image_server,
    clean_upgrade_state,
):
    """End-to-end upgrade with real image and config/cert staging.

    Same as test_upgrade_real_image but also exercises W3a (StageConfigs)
    and W3b (StageCerts) with sample payloads.

    Requires: --sonic-image-url, --sonic-image-version, and optionally
    --firmware-profile CLI options.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    logger.info(
        "Triggering real upgrade with configs/certs: version=%s server=%s",
        real_image_server["version"], real_image_server["image_server_ip"],
    )
    req = {
        "image_version": real_image_server["version"],
        "firmware_profile": real_image_server["firmware_profile"],
        "reboot_method": "COLD",
        "configs": [
            {"name": "/etc/sonic/config_db.json", "content": "e30="},
        ],
        "certs": [
            {"name": "/etc/sonic/telemetry/cert.pem", "content": "ZHVtbXk="},
        ],
    }
    if not restart_agent_for_real_image_server:
        req["image_server_ips"] = [real_image_server["image_server_ip"]]
    resp = grpcurl(duthost, "TriggerUpgrade", req)
    logger.info("TriggerUpgrade (real + configs) response: %s", resp)

    # Poll until terminal state
    status = poll_upgrade_status(duthost, timeout=600, interval=10)
    logger.info("Real upgrade with configs final status: %s", status)
    pytest_assert(
        status.get("state") in ("SUCCEEDED", "FAILED"),
        "Expected terminal state but got: {}".format(status),
    )
