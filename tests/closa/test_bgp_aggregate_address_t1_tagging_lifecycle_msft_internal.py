"""Test Group 3: Lifecycle operations preserve tier-based tagging.

Implements test cases TC 3.1 – TC 3.3 of
    docs/testplan/BGP-T1-Aggregation-Tier-Tagging-TestPlan.md

  TC 3.1 — BGP container restart preserves tagging.
  TC 3.2 — Config reload preserves tagging (with on-disk re-save in teardown).
  TC 3.3 — Rapid add/remove churn does not corrupt prefix-list state.
"""

import json
import logging
import time

import pytest

from tests.common.helpers.assertions import pytest_assert
from tests.common.helpers.bgp_routing import (
    route_present_on_host,
)
from tests.closa.bgp_community_helpers_msft_internal import (
    # Used inline in the TC 3.3 churn loop; keeps iteration number in failure msg
    check_communities_on_neighbors,
)
from tests.common.utilities import wait_until
from tests.closa.bgp_aggregate_prefix_list_helpers_msft_internal import (
    BGP_SETTLE_WAIT,
    verify_bgp_aggregate_cleanup,
)
from tests.closa.bgp_t1_tagging_helpers_msft_internal import (
    AggregateCfg,
    gcu_add_aggregate,
    # constants
    AGGR_V4,
    CONTRIB_V4,
    COMM_AGG_T1,
    PL_AGG_V4, PL_AGG_CONTRIB_V4,
    # primitives
    announce_contributing_from_t0,
    assert_dut_not_advertising,
    assert_no_stale_aggregate_rows,
    assert_prefix_list_is_placeholder_only,
    db_add_cmd_for,
    db_del_cmd_for,
    dut_t0_peer_ips,
    wait_communities_on_neighbors,
    wait_route_absent_on_neighbors,
)

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.topology("t1"),
]

# ---- TC 3.3 churn constants (aligned with stress test reference) ----
RAPID_CYCLE_ITERATIONS = 100
RAPID_CYCLE_CHECK_EVERY = 5
CYCLE_TIMEOUT = 30
CYCLE_INTERVAL = 2

# Convergence budget for restart / config-reload paths (BGP needs more time)
LIFECYCLE_CONVERGE_TIMEOUT = 240


# ============================================================================
# Per-test fixtures
# ============================================================================
@pytest.fixture
def save_after_rollback(duthosts, rand_one_dut_hostname):
    """Re-save config after rollback so the on-disk config_db.json matches the
    rolled-back (clean) state.  Same protection as
    tests/bgp/test_bgp_aggregate_address_resilience.py::setup_teardown, used
    here because TC 3.2 issues `config save -y` mid-test and a failure between
    save and per-test cleanup would otherwise persist the aggregate on disk.
    """
    yield
    duthost = duthosts[rand_one_dut_hostname]
    try:
        duthost.shell("sudo config save -y")
    except Exception as exc:
        logger.warning("Post-test 'config save -y' failed: %s", exc)


# ============================================================================
# Local helpers
# ============================================================================
def _all_bgp_neighbors_established(duthost, neighbor_ips):
    """Return True iff every IP in ``neighbor_ips`` is in Established state
    according to ``vtysh -c 'show bgp summary json'``.

    Avoids ``duthost.check_bgp_session_state`` (and the ``bgp_facts`` Ansible
    module) because the custom ``bgp_facts`` module is not resolvable in some
    sonic-mgmt environments (rootdir-dependent ``ansible.cfg`` library path).
    """
    try:
        raw = duthost.shell(
            'vtysh -c "show bgp summary json"',
            module_ignore_errors=True,
        ).get("stdout", "")
        data = json.loads(raw) if raw else {}
    except Exception as exc:
        logger.warning("Failed to read 'show bgp summary json': %s", exc)
        return False

    established = set()
    for af_block in data.values():
        if not isinstance(af_block, dict):
            continue
        peers = af_block.get("peers") or {}
        for ip, info in peers.items():
            if isinstance(info, dict) and info.get("state") == "Established":
                established.add(ip.lower())

    pending = [ip for ip in neighbor_ips if ip.lower() not in established]
    if pending:
        logger.debug("BGP neighbors not yet Established: %s", pending)
        return False
    return True


def _wait_bgp_sessions_established(duthost, neighbor_ips, timeout):
    """Block until every neighbor IP is in Established state on the DUT."""
    pytest_assert(
        wait_until(timeout, 5, 0,
                   _all_bgp_neighbors_established, duthost, neighbor_ips),
        "Not all BGP sessions re-established within {}s".format(timeout),
    )


def _bgp_neighbor_ips(duthost):
    """Return the list of BGP neighbor IPs from the DUT's running config.

    Uses ``sonic-db-cli`` directly to avoid the brittle Ansible
    ``config_facts`` module dependency (some sonic-mgmt environments cannot
    resolve it).  Returns the IP part of every ``BGP_NEIGHBOR|<ip>`` key.
    """
    out = duthost.shell(
        "sonic-db-cli CONFIG_DB KEYS 'BGP_NEIGHBOR|*'",
        module_ignore_errors=True,
    )
    raw = (out.get("stdout") or "").strip()
    if not raw:
        return []
    return [line.split("|", 1)[1] for line in raw.splitlines() if "|" in line]


def _assert_bgpd_startup_config_has_aggregate_prefix_lists(
    duthost, prefix, aggregate_prefix_list, contributing_prefix_list,
):
    """Assert bgpd.conf includes the aggregate template and rendered prefix-lists."""
    bgpd_conf = duthost.shell("sudo docker exec bgp cat /etc/frr/bgpd.conf")["stdout"]
    template_marker = "template: bgpd/bgpd.aggregate.conf.j2"
    pytest_assert(
        template_marker in bgpd_conf,
        "Rendered /etc/frr/bgpd.conf does not include {}".format(template_marker),
    )

    lines = [line.strip() for line in bgpd_conf.splitlines()]
    ipcmd = "ipv6" if ":" in prefix.split("/", 1)[0] else "ip"
    max_prefix_len = 128 if ipcmd == "ipv6" else 32

    checks = {
        "aggregate prefix-list": lambda line: (
            line.startswith("{} prefix-list {} ".format(ipcmd, aggregate_prefix_list)) and
            " permit {}".format(prefix) in line
        ),
        "contributing prefix-list": lambda line: (
            line.startswith("{} prefix-list {} ".format(ipcmd, contributing_prefix_list)) and
            " permit {} le {}".format(prefix, max_prefix_len) in line
        ),
        "aggregate-address": lambda line: (
            line == "aggregate-address {}".format(prefix) or
            line.startswith("aggregate-address {} ".format(prefix))
        ),
    }
    missing = [name for name, predicate in checks.items() if not any(predicate(line) for line in lines)]
    pytest_assert(
        not missing,
        "Rendered /etc/frr/bgpd.conf missing aggregate startup config: {}".format(missing),
    )


# ============================================================================
# TC 3.1 — BGP container restart preserves tagging
# ============================================================================
def test_aggregate_tag_survives_bgp_restart(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup, t0_announce_cleanup,
):
    """TC 3.1: after `systemctl restart bgp`, T2 still sees 65525:21 on the aggregate."""
    duthost = duthosts[rand_one_dut_hostname]
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]

    for c in CONTRIB_V4:
        t0_announce_cleanup(c)
        announce_contributing_from_t0(t0_host, c)

    aggr_cleanup(AGGR_V4)
    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=AGGR_V4,
        aggregate_prefix_list=PL_AGG_V4,
        contributing_prefix_list=PL_AGG_CONTRIB_V4,
    ))

    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, AGGR_V4,
        expected={COMM_AGG_T1},
        duthost=duthost,
        prefix_list_names=[PL_AGG_V4, PL_AGG_CONTRIB_V4],
    )

    # Restart the BGP container
    neighbor_ips = _bgp_neighbor_ips(duthost)
    duthost.shell("sudo systemctl restart bgp")
    _wait_bgp_sessions_established(duthost, neighbor_ips, LIFECYCLE_CONVERGE_TIMEOUT)
    _assert_bgpd_startup_config_has_aggregate_prefix_lists(
        duthost, AGGR_V4, PL_AGG_V4, PL_AGG_CONTRIB_V4,
    )

    # Tagging must survive
    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, AGGR_V4,
        expected={COMM_AGG_T1},
        timeout=LIFECYCLE_CONVERGE_TIMEOUT,
        duthost=duthost,
        prefix_list_names=[PL_AGG_V4, PL_AGG_CONTRIB_V4],
    )


# ============================================================================
# TC 3.2 — Config reload preserves tagging (with on-disk re-save in teardown)
# ============================================================================
def test_aggregate_tag_survives_config_reload(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup, t0_announce_cleanup,
    save_after_rollback,
):
    """TC 3.2: ``config save -y`` + ``config reload -y -f`` preserves tagging on T2
    and keeps the aggregate hidden from T0."""
    duthost = duthosts[rand_one_dut_hostname]
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]

    for c in CONTRIB_V4:
        t0_announce_cleanup(c)
        announce_contributing_from_t0(t0_host, c)

    aggr_cleanup(AGGR_V4)
    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=AGGR_V4,
        aggregate_prefix_list=PL_AGG_V4,
        contributing_prefix_list=PL_AGG_CONTRIB_V4,
    ))
    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, AGGR_V4,
        expected={COMM_AGG_T1},
        duthost=duthost,
        prefix_list_names=[PL_AGG_V4, PL_AGG_CONTRIB_V4],
    )

    duthost.shell("sudo config save -y")
    # `config_reload` is intentionally NOT imported from tests.common.config_reload
    # here because the simple shell command keeps the test self-contained and
    # mirrors what an operator would actually run.
    duthost.shell("sudo config reload -y -f")

    neighbor_ips = _bgp_neighbor_ips(duthost)
    _wait_bgp_sessions_established(duthost, neighbor_ips, LIFECYCLE_CONVERGE_TIMEOUT)

    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, AGGR_V4,
        expected={COMM_AGG_T1},
        timeout=LIFECYCLE_CONVERGE_TIMEOUT,
        duthost=duthost,
        prefix_list_names=[PL_AGG_V4, PL_AGG_CONTRIB_V4],
    )
    # Pair duthost so a failure dumps the DUT-side BGP table for the prefix
    # plus the first leaking T0 (with its community list).
    wait_route_absent_on_neighbors(
        nbrhosts, t1_neighbors.t0, AGGR_V4,
        timeout=LIFECYCLE_CONVERGE_TIMEOUT,
        duthost=duthost,
    )

    # DUT-authoritative leak check after reload.  Neighbor-side polling alone
    # would tolerate a transient SSH/eAPI hiccup as "absent", silently passing
    # a broken leak prevention.  Mirrors TC 2.1 / 2.2 step 4 of the testplan.
    assert_dut_not_advertising(
        duthost, dut_t0_peer_ips(duthost, family="ipv4"), AGGR_V4,
        timeout=LIFECYCLE_CONVERGE_TIMEOUT,
    )


# ============================================================================
# TC 3.3 — Rapid add/remove churn does not corrupt prefix-list state
# ============================================================================
def test_rapid_add_remove_churn(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    t0_announce_cleanup,
):
    """TC 3.3: 100 add/remove iterations via direct ``sonic-db-cli`` writes.

    Per testplan §CONFIG_DB Write Strategy this bypasses GCU to actually
    stress the bgpcfgd -> FRR write path; GCU's per-write overhead would
    dominate the loop.  Verification at each iteration uses real
    convergence signals (``check_communities_on_neighbors`` / route
    presence) — no blind ``time.sleep`` between iterations.
    """
    duthost = duthosts[rand_one_dut_hostname]
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]
    t2_names = t1_neighbors.t2

    # Pre-test setup: announce contributing routes so the aggregate has
    # something to summarize, and assert baseline prefix-list state.
    for c in CONTRIB_V4:
        t0_announce_cleanup(c)
        announce_contributing_from_t0(t0_host, c)

    assert_prefix_list_is_placeholder_only(duthost, PL_AGG_V4, "ipv4")
    assert_prefix_list_is_placeholder_only(duthost, PL_AGG_CONTRIB_V4, "ipv4")

    add_cmd = db_add_cmd_for(AGGR_V4, PL_AGG_V4, PL_AGG_CONTRIB_V4)
    del_cmd = db_del_cmd_for(AGGR_V4)

    t2_hosts = [nbrhosts[n]["host"] for n in t2_names]

    def _aggregate_absent_on_t2():
        return all(not route_present_on_host(h, AGGR_V4) for h in t2_hosts)

    try:
        for iteration in range(1, RAPID_CYCLE_ITERATIONS + 1):
            iter_start = time.perf_counter()

            add_cmd_start = time.perf_counter()
            duthost.shell(add_cmd, module_ignore_errors=True)
            add_cmd_elapsed = time.perf_counter() - add_cmd_start

            sampled_check = (iteration % RAPID_CYCLE_CHECK_EVERY == 0)
            add_check_elapsed = 0.0
            del_check_elapsed = 0.0

            if sampled_check:
                add_check_start = time.perf_counter()
                pytest_assert(
                    wait_until(
                        CYCLE_TIMEOUT, CYCLE_INTERVAL, 0,
                        check_communities_on_neighbors,
                        nbrhosts, t2_names, AGGR_V4, {COMM_AGG_T1}, set(),
                    ),
                    "Iteration {}: aggregate not tagged on T2 with {}".format(
                        iteration, COMM_AGG_T1,
                    ),
                )
                add_check_elapsed = time.perf_counter() - add_check_start

            del_cmd_start = time.perf_counter()
            duthost.shell(del_cmd, module_ignore_errors=True)
            del_cmd_elapsed = time.perf_counter() - del_cmd_start

            if sampled_check:
                del_check_start = time.perf_counter()
                pytest_assert(
                    wait_until(CYCLE_TIMEOUT, CYCLE_INTERVAL, 0, _aggregate_absent_on_t2),
                    "Iteration {}: aggregate not withdrawn from T2".format(iteration),
                )
                del_check_elapsed = time.perf_counter() - del_check_start

            iter_elapsed = time.perf_counter() - iter_start
            if sampled_check:
                logger.info(
                    "TC3.3 iteration %d/%d timing(s) [sampled]: add_cmd=%.3f, add_check=%.3f, "
                    "del_cmd=%.3f, del_check=%.3f, total=%.3f",
                    iteration,
                    RAPID_CYCLE_ITERATIONS,
                    add_cmd_elapsed,
                    add_check_elapsed,
                    del_cmd_elapsed,
                    del_check_elapsed,
                    iter_elapsed,
                )
            else:
                logger.debug(
                    "TC3.3 iteration %d/%d timing(s): add_cmd=%.3f, del_cmd=%.3f, total=%.3f",
                    iteration,
                    RAPID_CYCLE_ITERATIONS,
                    add_cmd_elapsed,
                    del_cmd_elapsed,
                    iter_elapsed,
                )
    finally:
        # Last-chance safety: remove the row if the loop exited mid-cycle
        duthost.shell(del_cmd, module_ignore_errors=True)

    time.sleep(BGP_SETTLE_WAIT)

    # Post-test invariants — drained back to baseline
    verify_bgp_aggregate_cleanup(duthost, AGGR_V4)
    assert_prefix_list_is_placeholder_only(duthost, PL_AGG_V4, "ipv4")
    assert_prefix_list_is_placeholder_only(duthost, PL_AGG_CONTRIB_V4, "ipv4")
    assert_no_stale_aggregate_rows(duthost)
