"""Local conftest for tests/closa/.

Re-exports the 5 t1-tagging fixtures from
``tests.closa.bgp_t1_tagging_helpers_msft_internal`` so the tests in this
directory can request them by parameter name without explicit per-file
imports (mirrors the pattern previously used in tests/bgp/conftest.py).

Also provides an autouse multi-ASIC skip: every test under tests/closa/
exercises FRR templates that are only rendered on single-ASIC frontends
(msft.general / msft.mgmt / SUPPRESS_PREFIX), so on multi-ASIC platforms
they have no useful coverage and would either fail or report nonsense.
"""

import pytest

from tests.closa.bgp_t1_tagging_helpers_msft_internal import (  # noqa: F401
    aggr_cleanup,
    require_t1_tagging_image,
    t0_announce_cleanup,
    t1_tagging_clean_config,
    t1_neighbors,
)


@pytest.fixture(autouse=True)
def _closa_skip_if_multi_asic(duthosts, rand_one_dut_hostname):
    """Skip every closa test on multi-ASIC testbeds.

    Equivalent to the previous conditional_mark YAML rule:
        is_multi_asic == True  ->  skip
    """
    duthost = duthosts[rand_one_dut_hostname]
    try:
        is_multi_asic = duthost.facts.get("num_asic", 1) > 1
    except Exception:
        is_multi_asic = getattr(duthost, "is_multi_asic", False)
    if is_multi_asic:
        pytest.skip("Skip for multi-ASIC testbed")
