import pytest
import logging
from tests.common.helpers.assertions import pytest_assert

pytestmark = [
    pytest.mark.disable_loganalyzer,
    pytest.mark.topology('any'),
    pytest.mark.skip_check_dut_health
]

logger = logging.getLogger(__name__)

CONTAINER_NAME = "aznsa"


def test_container_running(duthosts, enum_rand_one_per_hwsku_hostname):
    """Verify aznetsec-agent container is running."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    output = duthost.shell(
        f"docker ps --filter name={CONTAINER_NAME} --filter status=running -q",
        module_ignore_errors=True,
    )
    duthost.shell(f"docker logs {CONTAINER_NAME}", module_ignore_errors=True)
    duthost.shell(f"docker inspect {CONTAINER_NAME}", module_ignore_errors=True)
    pytest_assert(
        "stdout" in output,
        f"shell command failed: {output.get('msg', 'unknown error')}",
    )
    pytest_assert(
        output["stdout"].strip() != "",
        f"{CONTAINER_NAME} container is not running",
    )


def test_liveness(duthosts, enum_rand_one_per_hwsku_hostname):
    """Verify the aznetsec-agent liveness probe reports healthy."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    output = duthost.shell(
        f"docker exec {CONTAINER_NAME} /opt/aznetsec-agent livez",
        module_ignore_errors=True,
    )
    pytest_assert(
        "stdout" in output,
        f"shell command failed: {output.get('msg', 'unknown error')}",
    )
    pytest_assert(
        output["rc"] == 0,
        f"livez probe failed (rc={output.get('rc')}): "
        f"{output.get('stderr', '') or output.get('stdout', '')}",
    )
    stdout = output["stdout"].strip()
    logger.info(f"livez output: {stdout}")
    pytest_assert(
        "ok" in stdout.lower(),
        f"livez did not report ok: {stdout}",
    )
