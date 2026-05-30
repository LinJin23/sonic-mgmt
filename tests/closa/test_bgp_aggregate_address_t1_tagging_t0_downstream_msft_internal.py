"""Test Group 2: T1 -> T0 downstream — aggregate leak prevention.

Implements test cases TC 2.1 – TC 2.3 of
    docs/testplan/BGP-T1-Aggregation-Tier-Tagging-TestPlan.md

These tests assert that the synthetic aggregate created on the T1 DUT is
NEVER advertised down to T0 neighbors, while all other DUT-originated
routes (default route / loopback / unrelated prefixes) continue to flow
normally.  Behavior on the T2 side is exercised by TG 1.
"""

import logging

import pytest

from tests.common.helpers.assertions import pytest_assert
from tests.closa.bgp_t1_tagging_helpers_msft_internal import (
    AggregateCfg,
    gcu_add_aggregate,
    # constants
    AGGR_V4, AGGR_V6,
    CONTRIB_V4, CONTRIB_V6,
    PL_AGG_V4, PL_AGG_V6,
    PL_AGG_CONTRIB_V4, PL_AGG_CONTRIB_V6,
    # primitives
    announce_contributing_from_t0,
    assert_dut_not_advertising,
    dut_t0_peer_ips,
    wait_route_absent_on_neighbors,
    wait_route_present_on_neighbors,
)

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.topology("t1"),
]


# ============================================================================
# TC 2.1 / 2.2 — Aggregate not advertised to T0 (V4 + V6)
# ============================================================================
@pytest.mark.parametrize(
    "aggregate,agg_pl,contrib_pl,contribs",
    [
        (AGGR_V4, PL_AGG_V4, PL_AGG_CONTRIB_V4, CONTRIB_V4),
        (AGGR_V6, PL_AGG_V6, PL_AGG_CONTRIB_V6, CONTRIB_V6),
    ],
    ids=["tc2_1_ipv4", "tc2_2_ipv6"],
)
def test_aggregate_not_advertised_to_t0(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup, t0_announce_cleanup,
    aggregate, agg_pl, contrib_pl, contribs,
):
    """TC 2.1 / 2.2: T0 must NOT receive the aggregate; contributing routes unchanged."""
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

    # Aggregate must NOT be received by any T0 neighbor.  Pair duthost so
    # the failure message dumps the DUT-side BGP table for the prefix and
    # the first leaking T0 (with its community list) -- distinguishes a
    # transient neighbor SSH/eAPI hiccup from a real leak.
    wait_route_absent_on_neighbors(
        nbrhosts, t1_neighbors.t0, aggregate, duthost=duthost,
    )

    # Testplan TC 2.1 / 2.2 step 4: DUT-authoritative check.  Neighbor-side
    # polling alone would tolerate a transient SSH/eAPI hiccup as "absent",
    # silently passing a broken leak prevention.  advertised-routes reads
    # the DUT Adj-RIB-Out directly and is unaffected by neighbor flakiness.
    family = "ipv6" if ":" in aggregate else "ipv4"
    assert_dut_not_advertising(
        duthost, dut_t0_peer_ips(duthost, family=family), aggregate,
    )

    # The contributing routes that T0 itself originated must remain visible on
    # every other T0 neighbor that has visibility into them (sanity: at minimum
    # the originating T0 still has them in its own BGP table — checked via
    # route_present_on_host on the originator).
    for c in contribs:
        wait_route_present_on_neighbors(
            nbrhosts, [t1_neighbors.t0[0]], c,
        )


# ============================================================================
# TC 2.3 — Other DUT-originated routes (loopback / default) are unaffected
# ============================================================================
def test_other_routes_unaffected(
    duthosts, rand_one_dut_hostname, nbrhosts,
    t1_tagging_clean_config, t1_neighbors,
    aggr_cleanup, t0_announce_cleanup,
):
    """TC 2.3: with the aggregate in place, the DUT still advertises its
    Loopback0 prefix to T0 (proxy for "non-aggregate routes unaffected").

    Implementation note: we read the DUT Loopback0 IPv4 address via
    ``sonic-cfggen`` shell (avoids the brittle Ansible ``config_facts``
    module).  Only presence is checked, not community.
    """
    duthost = duthosts[rand_one_dut_hostname]

    # Discover Loopback0 IPv4 prefix from the DUT via sonic-cfggen
    out = duthost.shell(
        "sonic-cfggen -d -v 'LOOPBACK_INTERFACE.keys() | list'",
        module_ignore_errors=True,
    )
    raw_keys = (out.get("stdout") or "").strip()
    loopback_prefix = None
    # raw_keys is a Python-list repr like:
    #   "[('Loopback0',), ('Loopback0', '10.1.0.32/32'), ...]"
    # Find the first entry that names Loopback0 with an IPv4 /XX address.
    for token in raw_keys.split(","):
        token = token.strip().strip("[]() '\"")
        if "/" in token and "." in token and ":" not in token:
            loopback_prefix = token.split("/")[0] + "/32"
            break
    pytest_assert(
        loopback_prefix is not None,
        "DUT has no Loopback0 IPv4 address — cannot probe for non-aggregate "
        "routes (sonic-cfggen output was: {!r})".format(raw_keys),
    )

    # Originate one contributing so the aggregate activates
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]
    for c in CONTRIB_V4:
        announce_contributing_from_t0(t0_host, c)
        t0_announce_cleanup(c)

    gcu_add_aggregate(duthost, AggregateCfg(
        prefix=AGGR_V4,
        aggregate_prefix_list=PL_AGG_V4,
        contributing_prefix_list=PL_AGG_CONTRIB_V4,
    ))
    aggr_cleanup(AGGR_V4)

    # Aggregate is hidden from T0 (re-asserts TC 2.1 invariant)
    wait_route_absent_on_neighbors(
        nbrhosts, t1_neighbors.t0, AGGR_V4, duthost=duthost,
    )

    # Loopback continues to flow to T0
    wait_route_present_on_neighbors(nbrhosts, t1_neighbors.t0, loopback_prefix)
