"""closa-only BGP community inspection helpers.

The community-tagging tests under tests/closa/ need to inspect the
``community`` attribute of BGP routes received by neighbor hosts.  Those
helpers live here rather than in the public
``tests/common/helpers/bgp_routing.py`` because they were added solely to
support the MSFT-internal community-tagging feature (community values
65525:21 / 65525:110 / 8075:* etc.) and per policy we may not modify the
public helper.

Public BGP route-injection / route-presence helpers
(``inject_routes``, ``route_present_on_host``, ``verify_route_on_neighbors``,
etc.) are *not* re-exported here — import them directly from
``tests.common.helpers.bgp_routing``.
"""

import logging

from tests.common.devices.eos import EosHost
from tests.common.devices.sonic import SonicHost
from tests.common.helpers.assertions import pytest_assert
from tests.common.utilities import wait_until

logger = logging.getLogger(__name__)

# Default convergence budget for community verification helpers
DEFAULT_BGP_COMMUNITY_CONVERGE_TIMEOUT = 120
DEFAULT_BGP_COMMUNITY_POLL_INTERVAL = 3


def _frr_route_communities(route_data):
    """Extract community strings from FRR/vtysh JSON route output.

    FRR JSON for ``show bgp ipv{4,6} unicast <prefix> json`` exposes
    communities under ``paths[*].community`` with the following shapes
    observed across SONiC/FRR versions:

      "community": {"string": "65525:110"}                       # single
      "community": {"string": "65525:21 65525:110",
                     "list": ["65525:21", "65525:110"]}           # multi (str list)
      "community": {"list": [{"string": "65525:21"}, ...]}        # multi (dict list)

    Normalises all three forms and returns the union of community strings
    across every path.
    """
    communities = set()
    for path_info in route_data.get("paths", []):
        comm_data = path_info.get("community", {}) or {}
        for comm_entry in comm_data.get("list", []) or []:
            if isinstance(comm_entry, str):
                if comm_entry:
                    communities.add(comm_entry)
            elif isinstance(comm_entry, dict):
                comm_str = comm_entry.get("string", "")
                if comm_str:
                    communities.add(comm_str)
        # Some FRR versions only populate ``community.string``; split by
        # whitespace because multiple communities are concatenated there.
        comm_string = comm_data.get("string", "")
        if comm_string:
            communities.update(s for s in comm_string.split() if s)
    return communities


def get_route_communities(host, prefix):
    """Extract the set of BGP community strings attached to a prefix.

    Supports EosHost (Arista vEOS), SonicHost, and MultiAsicSonicHost-like
    objects that expose ``get_route(prefix)`` returning FRR/vtysh JSON.

    Returns an empty set if the route is not found or on any error.
    """
    communities = set()
    try:
        if isinstance(host, EosHost):
            route_data = host.get_route(prefix)
            entries = route_data.get("vrfs", {}).get("default", {}).get("bgpRouteEntries", {})
            for path_info in entries.get(prefix, {}).get("bgpRoutePaths", []):
                detail = path_info.get("routeDetail", {})
                for comm in detail.get("communityList", []):
                    communities.add(comm)
        elif isinstance(host, SonicHost):
            communities.update(_frr_route_communities(host.get_route(prefix)))
        elif hasattr(host, "get_route"):
            communities.update(_frr_route_communities(host.get_route(prefix)))
        else:
            logger.warning("get_route_communities: unsupported host type %s", type(host))
    except Exception as e:
        logger.debug("get_route_communities(%s, %s) failed: %s",
                     getattr(host, "hostname", host), prefix, e)
    return communities


def check_communities_on_neighbors(nbrhosts, neighbor_list, prefix,
                                   expected, unexpected):
    """Polling target for wait_until. Returns True when ALL neighbors match."""
    for nbr_name in neighbor_list:
        host = nbrhosts[nbr_name]["host"]
        actual = get_route_communities(host, prefix)
        if not expected.issubset(actual):
            logger.info("check_communities: %s on %s missing %s (has %s)",
                        prefix, nbr_name, expected - actual, actual)
            return False
        if unexpected and unexpected.intersection(actual):
            logger.info("check_communities: %s on %s has unwanted %s",
                        prefix, nbr_name, unexpected.intersection(actual))
            return False
    return True


def verify_route_communities(nbrhosts, neighbor_list, prefix,
                             expected_communities=None, unexpected_communities=None,
                             timeout=DEFAULT_BGP_COMMUNITY_CONVERGE_TIMEOUT):
    """Assert that a route on ALL specified neighbors carries expected communities
    and does NOT carry unexpected communities. Polls until convergence or timeout.
    """
    expected = set(expected_communities or [])
    unexpected = set(unexpected_communities or [])

    ok = wait_until(timeout, DEFAULT_BGP_COMMUNITY_POLL_INTERVAL, 0,
                    check_communities_on_neighbors,
                    nbrhosts, neighbor_list, prefix, expected, unexpected)
    pytest_assert(
        ok,
        "Community check FAILED on {} for prefix {} after {}s. "
        "Expected present: {}, Expected absent: {}".format(
            neighbor_list, prefix, timeout, expected, unexpected)
    )
