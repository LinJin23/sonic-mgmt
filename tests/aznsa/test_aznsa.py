import pytest
import logging
from tests.aznsa.aznsa_helpers import CONTAINER_NAME, dump_aznsa_container_logs, is_aznsa_container_running
from tests.common.helpers.assertions import pytest_assert

pytestmark = [
    pytest.mark.disable_loganalyzer,
    pytest.mark.topology('any'),
    pytest.mark.skip_check_dut_health
]

logger = logging.getLogger(__name__)


def test_container_running(duthosts, enum_rand_one_per_hwsku_hostname):
    """Verify aznetsec-agent container is running."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]
    running = is_aznsa_container_running(duthost)
    if not running:
        dump_aznsa_container_logs(duthost)
    pytest_assert(
        running,
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
