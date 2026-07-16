import json
import uuid
import logging

import pytest

from tests.aznsa.aznsa_helpers import dump_aznsa_container_logs
from tests.common.helpers.assertions import pytest_assert
from tests.common.utilities import wait_until

pytestmark = [
    pytest.mark.disable_loganalyzer,
    pytest.mark.topology('any'),
    pytest.mark.skip_check_dut_health
]

logger = logging.getLogger(__name__)


@pytest.mark.usefixtures("aznsa_configured")
def test_event_reporting_e2e(
    duthosts, enum_rand_one_per_hwsku_hostname, listener
):
    """Verify aznsa detects a new process and reports it to the listener."""
    duthost = duthosts[enum_rand_one_per_hwsku_hostname]

    marker = "aznsa_probe_{}".format(uuid.uuid4().hex[:12])
    probe = "/tmp/{}".format(marker)
    duthost.shell(
        "printf '#!/bin/sh\\nsleep 1\\n' > {p} && chmod +x {p}".format(p=probe)
    )

    # Discard any events observed before the probe runs.
    listener.store.clear()
    duthost.shell(probe, module_ignore_errors=True)

    def _seen():
        return bool(listener.store.find(lambda e: marker in json.dumps(e)))

    found = wait_until(60, 3, 0, _seen)
    duthost.shell("rm -f {}".format(probe), module_ignore_errors=True)

    if not found:
        dump_aznsa_container_logs(duthost)

    pytest_assert(
        found,
        "aznsa did not report a process event containing marker '{}'. "
        "Received {} event(s).".format(marker, len(listener.store.all())),
    )
