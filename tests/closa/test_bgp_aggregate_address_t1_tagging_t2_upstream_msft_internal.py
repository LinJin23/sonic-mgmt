"""Test Group 1: T1 -> T2 upstream — TO_TIER2 aggregate tagging + contributing suppression.

Implements test cases TC 1.1 – TC 1.10 of
    docs/testplan/BGP-T1-Aggregation-Tier-Tagging-TestPlan.md

Each test runs against a single LeafRouter DUT on a t1 topology.  Per-test
state changes are wrapped by the module-scoped ``t1_tagging_clean_config``
checkpoint (rollback on module teardown) plus a function-scoped
``aggr_cleanup`` that removes any aggregate added during the test.
"""

import logging
import time

import pytest

from tests.common.helpers.assertions import pytest_assert
from tests.closa.bgp_community_helpers_msft_internal import (
    get_route_communities,
)
from tests.common.utilities import wait_until
from tests.closa.bgp_aggregate_prefix_list_helpers_msft_internal import (
    BGP_SETTLE_WAIT,
)
from tests.closa.bgp_t1_tagging_helpers_msft_internal import (
    AggregateCfg,
    gcu_add_aggregate,
    # constants
    AGGR_V4, AGGR_V4_SECOND, AGGR_V6,
    CONTRIB_V4, CONTRIB_V6,
    COMM_AGG_T1, COMM_SUPPRESS_ON_T1,
    NON_CONTRIB_V4,
    PL_AGG_V4, PL_AGG_V6,
    PL_AGG_CONTRIB_V4, PL_AGG_CONTRIB_V6,
    PLACEHOLDER_V4,
    ROUTE_CONVERGE_INTERVAL, ROUTE_CONVERGE_TIMEOUT,
    # primitives
    announce_contributing_from_t0,
    assert_dut_advertising,
    assert_dut_not_advertising,
    assert_no_stale_aggregate_rows,
    assert_prefix_list_contains,
    assert_prefix_list_excludes,
    assert_prefix_list_is_placeholder_only,
    db_remove_aggregate,
    dut_t2_peer_ips,
    get_prefix_list_entries,
    wait_communities_on_neighbors,
    wait_route_absent_on_neighbors,
    wait_route_present_on_neighbors,
)

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.topology("t1"),
]


# ============================================================================
# Local convenience wrappers
# ============================================================================
def _wait_dut_communities(duthost, prefix, expected, unexpected=None, timeout=None):
    """Poll until the DUT BGP route carries / lacks the requested communities.

    Specific to TC 1.10 -- inspects the DUT's own Loc-RIB community list
    (not a neighbor's view).  On failure dumps the DUT BGP table for the
    prefix.  Single-ASIC DUTs only (multi-ASIC is filtered out by
    conditional_mark).
    """
    unexpected = unexpected or set()

    def _check():
        actual = get_route_communities(duthost, prefix)
        return expected.issubset(actual) and not unexpected.intersection(actual)

    if wait_until(timeout or ROUTE_CONVERGE_TIMEOUT, ROUTE_CONVERGE_INTERVAL, 0, _check):
        return

    # Diagnostic: was the route ever in the DUT BGP table at all?
    af_cmd = "show bgp ipv6" if ":" in prefix else "show ip bgp"
    dut_view = duthost.shell(
        "vtysh -c '{} {}'".format(af_cmd, prefix),
        module_ignore_errors=True,
    ).get("stdout", "")
    pytest_assert(
        False,
        "DUT route {} did not converge to expected={}, unexpected={}; "
        "actual={}\n--- `vtysh -c '{} {}'`\n{}".format(
            prefix, expected, unexpected,
            get_route_communities(duthost, prefix),
            af_cmd, prefix, dut_view or "<empty>",
        ),
    )


# ============================================================================
# TC 1.1 / 1.2 — Aggregate route tagged with 65525:21 toward T2 (V4 + V6)
# ============================================================================
@pytest.mark.parametrize(
    "prefix,agg_pl,contrib_pl,contribs",
    [
        (AGGR_V4, PL_AGG_V4, PL_AGG_CONTRIB_V4, CONTRIB_V4),
        (AGGR_V6, PL_AGG_V6, PL_AGG_CONTRIB_V6, CONTRIB_V6),
    ],
    ids=["tc1_1_ipv4", "tc1_2_ipv6"],
)
def test_aggregate_tagged_on_t2(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup, t0_announce_cleanup,
    prefix, agg_pl, contrib_pl, contribs,
):
    """TC 1.1 / 1.2: T2 must receive the aggregate with 65525:21 and NOT 65525:110."""
    duthost = duthosts[rand_one_dut_hostname]
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]

    # Originate contributing routes from T0 so the aggregate becomes active
    for c in contribs:
        announce_contributing_from_t0(t0_host, c)
        t0_announce_cleanup(c)

    # Push the aggregate row to CONFIG_DB via GCU
    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=prefix,
        aggregate_prefix_list=agg_pl,
        contributing_prefix_list=contrib_pl,
    ))
    aggr_cleanup(prefix)

    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, prefix,
        expected={COMM_AGG_T1},
        unexpected={COMM_SUPPRESS_ON_T1},
    )


# ============================================================================
# TC 1.3 / 1.4 — Contributing routes traverse to T2 by catch-all (V4 + V6)
# ============================================================================
@pytest.mark.parametrize(
    "aggregate,agg_pl,contrib_pl,contribs",
    [
        (AGGR_V4, PL_AGG_V4, PL_AGG_CONTRIB_V4, CONTRIB_V4),
        (AGGR_V6, PL_AGG_V6, PL_AGG_CONTRIB_V6, CONTRIB_V6),
    ],
    ids=["tc1_3_ipv4", "tc1_4_ipv6"],
)
def test_contributing_traverse_catchall(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup, t0_announce_cleanup,
    aggregate, agg_pl, contrib_pl, contribs,
):
    """TC 1.3 / 1.4: contributing routes reach T2 untagged via the catch-all."""
    duthost = duthosts[rand_one_dut_hostname]
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]

    for c in contribs:
        announce_contributing_from_t0(t0_host, c)
        t0_announce_cleanup(c)

    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=aggregate,
        aggregate_prefix_list=agg_pl,
        contributing_prefix_list=contrib_pl,
    ))
    aggr_cleanup(aggregate)

    for c in contribs:
        wait_communities_on_neighbors(
            nbrhosts, t1_neighbors.t2, c,
            expected=set(),
            unexpected={COMM_AGG_T1, COMM_SUPPRESS_ON_T1},
        )


# ============================================================================
# TC 1.5 — Aggregate prefix-list populated / drained dynamically
# ============================================================================
def test_prefix_list_dynamic_populate(
    duthosts, rand_one_dut_hostname,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup,
):
    """TC 1.5: prefix-list shows placeholder → placeholder+entry → placeholder."""
    duthost = duthosts[rand_one_dut_hostname]

    # Before: placeholder only
    assert_prefix_list_is_placeholder_only(duthost, PL_AGG_V4, "ipv4")

    # Add aggregate
    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=AGGR_V4,
        aggregate_prefix_list=PL_AGG_V4,
        contributing_prefix_list=PL_AGG_CONTRIB_V4,
    ))
    aggr_cleanup(AGGR_V4)

    # After add: placeholder + dynamic entry
    pytest_assert(
        wait_until(
            ROUTE_CONVERGE_TIMEOUT, ROUTE_CONVERGE_INTERVAL, 0,
            lambda: AGGR_V4 in get_prefix_list_entries(duthost, PL_AGG_V4, "ipv4"),
        ),
        "Dynamic entry {} did not appear in {}".format(AGGR_V4, PL_AGG_V4),
    )

    # Remove aggregate (sonic-db-cli DEL: bypasses GCU's no-empty-table rule).
    # bgpcfgd picks up the CONFIG_DB notification and clears the dynamic
    # prefix-list entry the same way it would for a GCU `op=remove`.
    db_remove_aggregate(duthost, AGGR_V4)

    drained = wait_until(
        ROUTE_CONVERGE_TIMEOUT, ROUTE_CONVERGE_INTERVAL, 0,
        lambda: get_prefix_list_entries(duthost, PL_AGG_V4, "ipv4") == [PLACEHOLDER_V4],
    )
    if not drained:
        # Dump as much diagnostic state as possible so we don't need to repro
        actual_entries = get_prefix_list_entries(duthost, PL_AGG_V4, "ipv4")
        redis_keys = duthost.shell(
            "redis-cli -n 4 KEYS 'BGP_AGGREGATE_ADDRESS|*'",
            module_ignore_errors=True,
        ).get("stdout", "").strip()
        raw_pl = duthost.shell(
            "vtysh -c 'show ip prefix-list {}'".format(PL_AGG_V4),
            module_ignore_errors=True,
        ).get("stdout", "").strip()
        pytest_assert(
            False,
            "{pl} did not drain back to placeholder-only state.\n"
            "Expected: [{ph!r}]\n"
            "Actual entries (parsed): {act}\n"
            "BGP_AGGREGATE_ADDRESS rows in CONFIG_DB: {keys!r}\n"
            "Full `vtysh show ip prefix-list {pl}` output:\n{raw}".format(
                pl=PL_AGG_V4, ph=PLACEHOLDER_V4,
                act=actual_entries, keys=redis_keys, raw=raw_pl,
            ),
        )


# ============================================================================
# TC 1.6 — Multiple aggregates share the same prefix-list (mid-removal)
# ============================================================================
def test_multiple_aggregates_share_prefix_list(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup, t0_announce_cleanup,
):
    """TC 1.6: aggregate A and B share AGGREGATE_ROUTES_V4.

    After removing A, B must remain tagged and the prefix-list must contain
    only the placeholder + B.
    """
    duthost = duthosts[rand_one_dut_hostname]
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]

    # Originate one contributing per aggregate so both aggregates become active
    contribs = [CONTRIB_V4[0], "10.200.1.0/24"]
    for c in contribs:
        announce_contributing_from_t0(t0_host, c)
        t0_announce_cleanup(c)

    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=AGGR_V4,
        aggregate_prefix_list=PL_AGG_V4,
        contributing_prefix_list=PL_AGG_CONTRIB_V4,
    ))
    aggr_cleanup(AGGR_V4)
    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=AGGR_V4_SECOND,
        aggregate_prefix_list=PL_AGG_V4,
        contributing_prefix_list=PL_AGG_CONTRIB_V4,
    ))
    aggr_cleanup(AGGR_V4_SECOND)

    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, AGGR_V4,
        expected={COMM_AGG_T1}, unexpected=set(),
    )
    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, AGGR_V4_SECOND,
        expected={COMM_AGG_T1}, unexpected=set(),
    )

    # Remove A (sonic-db-cli DEL: see TC 1.5 for the GCU empty-table rationale)
    db_remove_aggregate(duthost, AGGR_V4)

    # A withdrawn on T2, B still tagged
    wait_route_absent_on_neighbors(nbrhosts, t1_neighbors.t2, AGGR_V4)
    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, AGGR_V4_SECOND,
        expected={COMM_AGG_T1}, unexpected=set(),
    )

    # DUT prefix-list: placeholder + B only (A removed)
    assert_prefix_list_excludes(duthost, PL_AGG_V4, AGGR_V4, "ipv4")
    assert_prefix_list_contains(duthost, PL_AGG_V4, AGGR_V4_SECOND, "ipv4")


# ============================================================================
# TC 1.7 — Shared prefix-list returns to placeholder after full drain
# ============================================================================
def test_shared_prefix_list_full_drain(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup, t0_announce_cleanup,
):
    """TC 1.7: after removing every aggregate, no orphan dynamic entries remain."""
    duthost = duthosts[rand_one_dut_hostname]
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]

    contribs = [CONTRIB_V4[0], "10.200.1.0/24"]
    for c in contribs:
        announce_contributing_from_t0(t0_host, c)
        t0_announce_cleanup(c)

    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=AGGR_V4,
        aggregate_prefix_list=PL_AGG_V4,
        contributing_prefix_list=PL_AGG_CONTRIB_V4,
    ))
    aggr_cleanup(AGGR_V4)
    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=AGGR_V4_SECOND,
        aggregate_prefix_list=PL_AGG_V4,
        contributing_prefix_list=PL_AGG_CONTRIB_V4,
    ))
    aggr_cleanup(AGGR_V4_SECOND)

    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, AGGR_V4,
        expected={COMM_AGG_T1}, unexpected=set(),
    )
    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, AGGR_V4_SECOND,
        expected={COMM_AGG_T1}, unexpected=set(),
    )

    db_remove_aggregate(duthost, AGGR_V4)
    db_remove_aggregate(duthost, AGGR_V4_SECOND)

    wait_route_absent_on_neighbors(nbrhosts, t1_neighbors.t2, AGGR_V4)
    wait_route_absent_on_neighbors(nbrhosts, t1_neighbors.t2, AGGR_V4_SECOND)

    time.sleep(BGP_SETTLE_WAIT)

    assert_prefix_list_is_placeholder_only(duthost, PL_AGG_V4, "ipv4")
    assert_prefix_list_is_placeholder_only(duthost, PL_AGG_CONTRIB_V4, "ipv4")
    assert_no_stale_aggregate_rows(duthost)


# ============================================================================
# TC 1.8 / 1.9 — Contributing tagged 65525:110 is suppressed toward T2 (V4 + V6)
# ============================================================================
@pytest.mark.parametrize(
    "aggregate,agg_pl,contrib_pl,suppressed",
    [
        (AGGR_V4, PL_AGG_V4, PL_AGG_CONTRIB_V4, CONTRIB_V4[0]),
        (AGGR_V6, PL_AGG_V6, PL_AGG_CONTRIB_V6, CONTRIB_V6[0]),
    ],
    ids=["tc1_8_ipv4", "tc1_9_ipv6"],
)
def test_suppression_when_tagged(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup, t0_announce_cleanup,
    aggregate, agg_pl, contrib_pl, suppressed,
):
    """TC 1.8 / 1.9: contributing routes carrying 65525:110 must NOT reach T2."""
    duthost = duthosts[rand_one_dut_hostname]
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]

    # Configure aggregate first so the contributing prefix-list matches it
    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=aggregate,
        aggregate_prefix_list=agg_pl,
        contributing_prefix_list=contrib_pl,
    ))
    aggr_cleanup(aggregate)

    # Inject contributing tagged with COMM_SUPPRESS_ON_T1 from T0
    # (community is applied on DUT-side inbound, see helper docstring)
    announce_contributing_from_t0(
        t0_host, suppressed, community=COMM_SUPPRESS_ON_T1, duthost=duthost,
    )
    t0_announce_cleanup(suppressed, COMM_SUPPRESS_ON_T1)

    # Pass duthost so failure dumps the DUT-side community (the critical
    # signal: if DUT view shows no 65525:110, T0 injection lost the tag).
    wait_route_absent_on_neighbors(nbrhosts, t1_neighbors.t2, suppressed, duthost=duthost)

    # Testplan TC 1.8 / 1.9 step 4: DUT-authoritative check.  Neighbor-side
    # polling alone would tolerate a transient SSH/eAPI hiccup as "absent",
    # silently passing a broken suppression.  advertised-routes reads the
    # DUT Adj-RIB-Out directly and is unaffected by neighbor-side flakiness.
    family = "ipv6" if ":" in suppressed else "ipv4"
    assert_dut_not_advertising(
        duthost, dut_t2_peer_ips(duthost, family=family), suppressed,
    )


# ============================================================================
# TC 1.10 — Suppression requires BOTH "in contributing prefix-list" AND "65525:110"
# ============================================================================
def test_suppression_requires_both_conditions(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup, t0_announce_cleanup,
):
    """TC 1.10: T1 suppresses only when prefix is contributing AND carries 65525:110.

    Covers two reverse cells of the (in-contrib-list, has-tag) truth table:
      (A=False, B=True):  NON_CONTRIB_V4 tagged 65525:110 — must traverse.
      (A=True,  B=False): CONTRIB_V4[0] without 65525:110 — must traverse.
    """
    duthost = duthosts[rand_one_dut_hostname]
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]
    # Both reverse cells use IPv4 prefixes.
    t2_peers_v4 = dut_t2_peer_ips(duthost, family="ipv4")

    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=AGGR_V4,
        aggregate_prefix_list=PL_AGG_V4,
        contributing_prefix_list=PL_AGG_CONTRIB_V4,
    ))
    aggr_cleanup(AGGR_V4)

    # Case (A=False, B=True): non-contributing prefix carrying 65525:110
    announce_contributing_from_t0(
        t0_host, NON_CONTRIB_V4, community=COMM_SUPPRESS_ON_T1, duthost=duthost,
    )
    t0_announce_cleanup(NON_CONTRIB_V4, COMM_SUPPRESS_ON_T1)
    _wait_dut_communities(
        duthost, NON_CONTRIB_V4,
        expected={COMM_SUPPRESS_ON_T1},
        unexpected={COMM_AGG_T1},
    )
    wait_route_present_on_neighbors(nbrhosts, t1_neighbors.t2, NON_CONTRIB_V4)
    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, NON_CONTRIB_V4,
        expected=set(),
        unexpected={COMM_AGG_T1},
    )
    # Testplan TC 1.10 step 4: DUT-authoritative check.
    assert_dut_advertising(duthost, t2_peers_v4, NON_CONTRIB_V4)

    # Case (A=True, B=False): contributing prefix WITHOUT 65525:110
    announce_contributing_from_t0(t0_host, CONTRIB_V4[0])  # no community
    t0_announce_cleanup(CONTRIB_V4[0])
    wait_route_present_on_neighbors(nbrhosts, t1_neighbors.t2, CONTRIB_V4[0])
    wait_communities_on_neighbors(
        nbrhosts, t1_neighbors.t2, CONTRIB_V4[0],
        expected=set(),
        unexpected={COMM_AGG_T1, COMM_SUPPRESS_ON_T1},
    )
    # Testplan TC 1.10 step 8: DUT-authoritative check.
    assert_dut_advertising(duthost, t2_peers_v4, CONTRIB_V4[0])
