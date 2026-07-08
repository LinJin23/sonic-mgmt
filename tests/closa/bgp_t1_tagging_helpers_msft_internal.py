"""Shared helpers for BGP T1 Aggregation Tier-Based Community Tagging tests.

Implements the framework described in
    docs/testplan/BGP-T1-Aggregation-Tier-Tagging-Impl-Framework.md

Reuse policy
------------
All non-trivial behavior is sourced from the canonical helpers below; this
module only adds what is genuinely new to the tier-tagging feature:
  - feature constants (community values, route-map / prefix-list names,
    test prefixes, convergence budgets)
  - DUT image / role gates (session-scoped fixtures)
  - neighbor classification (Layer-1 VM-name suffix + Layer-2
    DEVICE_NEIGHBOR_METADATA)
  - cEOS-based contributing-route injection helpers
  - small prefix-list / CONFIG_DB inspection utilities
  - sonic-db-cli command builders used by the TC 3.3 churn loop

``AggregateCfg`` and ``gcu_add_aggregate`` are re-exported from the closa
wrapper ``bgp_aggregate_prefix_list_helpers_msft_internal`` (a self-
contained closa-local copy extended with the two ``*_prefix_list`` fields
tier-tagging needs).

Canonical helpers reused from:
  - tests.closa.bgp_aggregate_prefix_list_helpers_msft_internal
                                              (extended AggregateCfg /
                                                gcu_add_aggregate +
                                                self-contained copy of
                                                BGP_SETTLE_WAIT etc.)
  - tests.closa.bgp_community_helpers_msft_internal
                                              (get_route_communities,
                                                check_communities_on_neighbors,
                                                verify_route_communities)
  - tests.common.helpers.bgp_routing          (route_present_on_host)
  - tests.common.gcu_utils                    (checkpoint API)
  - tests.common.utilities                    (wait_until)
  - tests.common.helpers.assertions           (pytest_assert)
"""

import logging
import json
import re
import time
from types import SimpleNamespace

import pytest

# AggregateCfg / BGP_SETTLE_WAIT / gcu_add_aggregate come from the
# closa wrapper (extended AggregateCfg with prefix-list fields).
from tests.closa.bgp_aggregate_prefix_list_helpers_msft_internal import (  # noqa: F401
    AggregateCfg,
    BGP_AGGREGATE_ADDRESS,
    BGP_SETTLE_WAIT,
    gcu_add_aggregate,
)
from tests.common.helpers.assertions import pytest_assert
from tests.common.utilities import wait_until  # noqa: F401  (re-exported)

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS — testplan §Community Tag Reference / §Route-Map Reference
# ============================================================================

# Community values applied / matched by the tier-tagging route-maps
COMM_AGG_T1 = "65525:21"          # T1 tags aggregate toward T2/RH/AZNG
COMM_SUPPRESS_ON_T1 = "65525:110"  # T0 tags contributing routes T1 must suppress

# Route-map names rendered by msft.general/{v4,v6}.leaf.{spine,tor.all} templates
# (only V4 is consumed -- used by the image-gate check below; V6 template
# renders the same prefix-list reference so checking V4 alone is sufficient)
RM_TO_TIER2_V4 = "TO_TIER2_V4"

# Prefix-list names matched at runtime by AggregateAddressMgr
PL_AGG_V4 = "AGGREGATE_ROUTES_V4"
PL_AGG_V6 = "AGGREGATE_ROUTES_V6"
PL_AGG_CONTRIB_V4 = "AGGREGATE_CONTRIBUTING_ROUTES_V4"
PL_AGG_CONTRIB_V6 = "AGGREGATE_CONTRIBUTING_ROUTES_V6"

# Placeholder entries the FRR template renders by default; the suite asserts
# the prefix-list returns to exactly these values after every aggregate is
# removed.
PLACEHOLDER_V4 = "127.0.0.1/32"
PLACEHOLDER_V6 = "::1/128"

# Test prefixes (TEST-NET / doc-only; never collide with production prefixes)
AGGR_V4 = "10.100.0.0/16"
AGGR_V4_SECOND = "10.200.0.0/16"
AGGR_V6 = "2001:db8:100::/48"
CONTRIB_V4 = ["10.100.1.0/24", "10.100.2.0/24"]
CONTRIB_V6 = ["2001:db8:100:1::/64", "2001:db8:100:2::/64"]
# TC 1.10 (A=False, B=True): prefix outside AGGREGATE_CONTRIBUTING_ROUTES_V4.
# Must NOT fall under any test aggregate -- ``AggregateAddressMgr`` populates
# the contributing prefix-list as ``permit <agg> le 32``, so any subnet
# within AGGR_V4 (10.100.0.0/16) or AGGR_V4_SECOND (10.200.0.0/16) would
# still match.  10.222.99.0/24 is outside both aggregates and therefore is
# truly "not contributing" for the TO_TIER2_V4 seq 300 AND check.
NON_CONTRIB_V4 = "10.222.99.0/24"

# Convergence budgets aligned with bgp_aggregate_helpers / stress test
ROUTE_CONVERGE_TIMEOUT = 60
ROUTE_CONVERGE_INTERVAL = 2


# ============================================================================
# IMAGE / ROLE GATE
# ============================================================================

def _has_t1_tagging_image(duthost):
    """Return True iff DUT image renders the TIER2 route-map referencing
    the AGGREGATE_ROUTES_V4 prefix-list (i.e. it is built from the
    MSFT-internal Networking-acs-buildimage fork).
    """
    out = duthost.shell(
        "vtysh -c 'show route-map {}' 2>/dev/null".format(RM_TO_TIER2_V4),
        module_ignore_errors=True,
    ).get("stdout", "")
    return PL_AGG_V4 in out


@pytest.fixture(scope="module")
def require_t1_tagging_image(duthosts, rand_one_dut_hostname):
    """Skip cleanly when DUT image does not render the tier-tagging template.

    Scope is `module` rather than `session` because the underlying
    ``rand_one_dut_hostname`` fixture is module-scoped (see
    tests/conftest.py); a session-scoped fixture cannot depend on a
    module-scoped one (ScopeMismatch).  The cost is one extra `vtysh`
    invocation per test module, which is trivial.

    DUT role is *not* checked separately: when the DUT is not a
    ``LeafRouter`` the MSFT-internal templates skip rendering
    ``TO_TIER2_V4`` entirely, so this image check is sufficient.
    """
    duthost = duthosts[rand_one_dut_hostname]
    if not _has_t1_tagging_image(duthost):
        pytest.skip(
            "DUT image does not render {} / {} - this plan targets the "
            "MSFT-internal Networking-acs-buildimage only".format(
                RM_TO_TIER2_V4, PL_AGG_V4
            )
        )


# ============================================================================
# NEIGHBOR CLASSIFICATION — testplan §Neighbor Classification Convention
# ============================================================================

_T2_LAYER2_TYPES = {
    "SpineRouter", "UpperSpineRouter", "LowerSpineRouter",
    "RegionalHub", "AZNGHub",
}
_T0_LAYER2_TYPES = {"ToRRouter", "BackEndToRRouter"}


def _load_var_json(duthost, table):
    """Read a CONFIG_DB table as a dict via ``sonic-cfggen --var-json <TABLE>``.

    Returns ``{}`` on missing/invalid JSON.  Used here rather than
    ``duthost.config_facts(...)`` because the Ansible ``config_facts`` module
    is environment-fragile in some sonic-mgmt containers; ``sonic-cfggen``
    ships on every SONiC image.
    """
    import json as _json_local
    raw = duthost.shell(
        "sonic-cfggen -d --var-json {}".format(table),
        module_ignore_errors=True,
    ).get("stdout", "").strip()
    if not raw or raw in ("None", "null"):
        return {}
    try:
        return _json_local.loads(raw) or {}
    except (ValueError, TypeError) as exc:
        logger.warning("failed to parse %s JSON: %s", table, exc)
        return {}


def classify_neighbors(duthost, nbrhosts):
    """Return ``(t0_names, t2_names)`` — both sorted lists of VM names.

    Layer 1: VM-name suffix ``endswith('T0' | 'T2')`` (same convention as
             tests/bgp/test_prefix_list_internal_only.py:293).
    Layer 2: ``DEVICE_NEIGHBOR_METADATA[*]['type']`` for role-named neighbors
             (RegionalHub, AZNGHub, etc.).
    """
    meta = _load_var_json(duthost, "DEVICE_NEIGHBOR_METADATA")

    t0 = {n for n in nbrhosts if n.endswith("T0")}
    t2 = {n for n in nbrhosts if n.endswith("T2")}
    for name, info in meta.items():
        if name not in nbrhosts or not isinstance(info, dict):
            continue
        nbr_type = info.get("type")
        if nbr_type in _T2_LAYER2_TYPES:
            t2.add(name)
        elif nbr_type in _T0_LAYER2_TYPES:
            t0.add(name)

    return sorted(t0), sorted(t2)


@pytest.fixture(scope="module")
def t1_neighbors(duthosts, rand_one_dut_hostname, nbrhosts):
    """Return a SimpleNamespace ``(t0, t2, all)`` of neighbor VM names."""
    duthost = duthosts[rand_one_dut_hostname]
    t0, t2 = classify_neighbors(duthost, nbrhosts)
    pytest_assert(t0, "No T0 neighbors found in nbrhosts (need at least one)")
    pytest_assert(t2, "No T2 neighbors found in nbrhosts (need at least one)")
    return SimpleNamespace(t0=t0, t2=t2, all=t0 + t2)


# ============================================================================
# AGGREGATE CRUD
# ============================================================================
# Test modules call ``bgp_aggregate_helpers.gcu_add_aggregate`` directly with
# an ``AggregateCfg`` (re-exported above); the two ``*_prefix_list`` fields
# default to "" and are only set by tier-tagging tests.


def db_remove_aggregate(duthost, prefix):
    """Delete a BGP_AGGREGATE_ADDRESS row directly via ``sonic-db-cli DEL``.

    Why not GCU ``op=remove``:
        GCU's apply-patch rejects any operation that leaves a CONFIG_DB
        table empty (validation rule: "given patch is not valid because it
        will result in empty tables which is not allowed in ConfigDb").
        When a test adds a single aggregate and then tries to remove it,
        GCU therefore raises -- even though bgpcfgd handles a direct DEL
        cleanly via the CONFIG_DB subscription path.

    The TC 3.3 churn loop already uses the same ``sonic-db-cli DEL`` pattern
    by design (see testplan section "CONFIG_DB Write Strategy"); this helper
    extends that approach to all the cleanup paths in TG 1.

    Returns the raw shell result for debug purposes; never raises.
    """
    cmd = "sonic-db-cli CONFIG_DB DEL 'BGP_AGGREGATE_ADDRESS|{}'".format(prefix)
    return duthost.shell(cmd, module_ignore_errors=True)


# ============================================================================
# CONTRIBUTING ROUTE INJECTION FROM T0 (cEOS)
# ============================================================================
# T0 neighbors on a t1 topology are Arista cEOS.  EOS BGP requires that a
# prefix be in the RIB before `network <prefix>` will inject it into BGP.
# We therefore stage a Null0 static route before the BGP `network` command,
# and use Arista's `network <prefix> route-map <name>` syntax to attach an
# optional community to the announcement.
#
# Pattern lifted from
#   tests/bgp/test_ipv6_nlri_over_ipv4.py    (eos_config with `parents=`)
#   tests/bgp/test_4-byte_asn_community.py   (router bgp <asn> mode)
# both of which use EosHost.eos_config(...) for neighbor-side BGP config.
#
# The route-map and prefix-list names are keyed off the prefix so concurrent
# injections of multiple prefixes do not stomp on each other.

_EOS_ASN_CACHE = {}
_DUT_ASN_CACHE = {}
_EOS_BGP_VRF_CACHE = {}


def _af_for_prefix(prefix):
    return "ipv6" if ":" in prefix else "ipv4"


def _get_eos_bgp_vrf(host):
    """Return the EOS BGP VRF context for this neighbor host, if any.

    Priority:
      1) ``host.bgp_vrf`` set by nbrhosts on converged multi-VRF peers.
      2) Fallback parse from ``show running-config section bgp``.

    Returns ``None`` for default/global BGP context.
    """
    key = getattr(host, "hostname", str(host))
    if key in _EOS_BGP_VRF_CACHE:
        return _EOS_BGP_VRF_CACHE[key]

    vrf = getattr(host, "bgp_vrf", None)
    if vrf:
        _EOS_BGP_VRF_CACHE[key] = vrf
        return vrf

    try:
        result = host.eos_command(commands=["show running-config section bgp"])
        text = result.get("stdout", [""])[0] if isinstance(result, dict) else str(result)
    except Exception:
        text = host.shell("show running-config section bgp").get("stdout", "")

    match = re.search(r"^\s*vrf\s+(\S+)\s*$", text, re.MULTILINE)
    vrf = match.group(1) if match else None
    _EOS_BGP_VRF_CACHE[key] = vrf
    return vrf


def _eos_null0_route_cmd(host, prefix, is_v4, withdraw=False):
    """Build EOS static Null0 command, VRF-scoped when host has bgp_vrf.

    On converged (multi-VRF) peers, BGP config is scoped under
    ``router bgp <prime_asn> -> vrf <logical>`` by EosHost wrappers.
    The contributing route must exist in the same VRF RIB, otherwise
    ``network <prefix>`` will not originate. For stock peers, keep the
    existing global/default-VRF command.
    """
    pl_kw = "ip" if is_v4 else "ipv6"
    vrf = _get_eos_bgp_vrf(host)
    action = "no " if withdraw else ""
    if vrf:
        return "{}{} route vrf {} {} Null0".format(action, pl_kw, vrf, prefix)
    return "{}{} route {} Null0".format(action, pl_kw, prefix)


def _get_eos_bgp_asn(host):
    """Return the local BGP ASN of an Arista cEOS host (cached per hostname)."""
    key = getattr(host, "hostname", str(host))
    if key in _EOS_ASN_CACHE:
        return _EOS_ASN_CACHE[key]
    try:
        result = host.eos_command(commands=["show running-config section bgp"])
        text = result.get("stdout", [""])[0] if isinstance(result, dict) else str(result)
    except Exception:
        # Fallback: try the generic shell-style command interface
        text = host.shell("show running-config section bgp")["stdout"]
    match = re.search(r"router bgp (\d+)", text)
    asn = match.group(1) if match else None
    pytest_assert(
        asn is not None,
        "Could not determine BGP ASN of {} from `show running-config section bgp`".format(key),
    )
    _EOS_ASN_CACHE[key] = asn
    return asn


def _get_dut_bgp_asn(duthost):
    """Return the DUT's local BGP ASN from ``DEVICE_METADATA|localhost`` (cached).

    Required for ``router bgp <asn>`` in our vtysh batches: under FRR
    ``router bgp`` without an ASN is *only* tolerated when exactly one
    BGP instance exists and no VRFs are configured -- otherwise the whole
    ``vtysh -c ... -c ...`` batch aborts mid-way, skipping the route-map
    attachment and the subsequent ``clear bgp ... in`` refreshes.
    """
    key = getattr(duthost, "hostname", str(duthost))
    if key in _DUT_ASN_CACHE:
        return _DUT_ASN_CACHE[key]
    meta = _load_var_json(duthost, "DEVICE_METADATA")
    asn = (meta.get("localhost") or {}).get("bgp_asn")
    pytest_assert(
        asn,
        "Could not determine DUT local BGP ASN from DEVICE_METADATA|localhost",
    )
    _DUT_ASN_CACHE[key] = str(asn)
    return _DUT_ASN_CACHE[key]


def announce_contributing_from_t0(t0_host, prefix, community=None,
                                  duthost=None):
    """Inject one contributing route from a T0 cEOS neighbor.

    Args:
        t0_host: cEOS host object (``nbrhosts[name]["host"]``).
        prefix:  IPv4 or IPv6 prefix string, e.g. ``"10.100.1.0/24"``.
        community: optional ``"asn:value"`` community string; when set, the
            community is applied to the route on the DUT-side inbound
            (see below for the rationale).
        duthost: required when ``community`` is set.  The community is
            attached on the DUT's inbound route-map for the T0 peer, NOT
            on cEOS T0's outbound side.

    Why community injection happens on the DUT-inbound side:
        Originally we tried to attach the community on cEOS T0 with
        ``network <prefix> route-map <RM>`` or per-neighbor outbound
        route-maps.  Neither worked reliably in the sonic-mgmt t1
        testbed:
          * ``network <prefix> route-map <RM>`` -- EOS treats <RM> as an
            origination filter (decides whether the prefix enters BGP
            table); it does NOT apply ``set community`` to the announce.
          * per-neighbor ``neighbor X.X.X.X route-map <RM> out`` is
            silently overridden by the topology's pre-existing
            outbound peer-group route-map (which adds ``8075:8823``
            instead of our community).
        Both routes leave the DUT seeing the route without
        ``COMM_SUPPRESS_ON_T1``, so the TIER2 seq 300 deny never fires.

        The test's semantic requirement is **"DUT receives the
        contributing prefix carrying community 65525:110"** -- where the
        community originally got attached is irrelevant to the
        suppression behavior we are validating.  Applying it on the
        DUT-inbound route-map for the T0 peer satisfies the requirement
        and uses only DUT-side vtysh commands (which we know work
        reliably).

    Idempotent: re-announcing the same (prefix, community) leaves both
    cEOS and the DUT in the same state.
    """
    af = _af_for_prefix(prefix)
    is_v4 = af == "ipv4"
    af_clause = "ipv4" if is_v4 else "ipv6"

    asn = _get_eos_bgp_asn(t0_host)
    bgp_vrf = _get_eos_bgp_vrf(t0_host)

    logger.info(
        "T0 %s announce %s%s",
        getattr(t0_host, "hostname", t0_host),
        prefix,
        " community={} (applied on DUT inbound)".format(community) if community else "",
    )

    # 1. Null0 static so the prefix is in RIB
    t0_host.eos_config(lines=[_eos_null0_route_cmd(t0_host, prefix, is_v4=is_v4)])

    # 2. `network` under the BGP address-family (origin into BGP table)
    parents = ["router bgp {}".format(asn)]
    if bgp_vrf:
        parents.append("vrf {}".format(bgp_vrf))
    parents.append("address-family {}".format(af_clause))
    t0_host.eos_config(
        lines=["network {}".format(prefix)],
        parents=parents,
    )

    # 3. Community injection (DUT-side inbound) -- see docstring for rationale.
    if community:
        pytest_assert(
            duthost is not None,
            "announce_contributing_from_t0(community=...) requires duthost: "
            "the community is applied on the DUT inbound route-map.",
        )
        _dut_inject_inbound_community(duthost, prefix, community)


def _dut_peer_ips_for_types(duthost, type_set, is_v4):
    """Return DUT-side BGP peer IPs whose neighbor metadata ``type`` is in ``type_set``.

    Joins ``BGP_NEIGHBOR`` (peer IP → ``name``) and
    ``DEVICE_NEIGHBOR_METADATA`` (``name`` → ``type``); filters by address
    family.  Single-ASIC DUTs only (multi-ASIC is filtered out by
    conditional_mark).
    """
    bgp_neighbor = _load_var_json(duthost, "BGP_NEIGHBOR")
    metadata = _load_var_json(duthost, "DEVICE_NEIGHBOR_METADATA")

    peer_ips = []
    for peer_ip, attrs in bgp_neighbor.items():
        if not isinstance(attrs, dict):
            continue
        nbr_name = attrs.get("name")
        nbr_meta = metadata.get(nbr_name) if nbr_name else None
        nbr_type = nbr_meta.get("type") if isinstance(nbr_meta, dict) else None
        if nbr_type not in type_set:
            continue
        is_v6 = ":" in peer_ip
        if is_v4 == is_v6:
            continue
        peer_ips.append(peer_ip)
    return sorted(set(peer_ips))


def _dut_t0_peer_ips(duthost, is_v4):
    """Return DUT's BGP peer IPs whose remote-end is a T0 (any T0 cEOS).

    Single-ASIC DUTs only (multi-ASIC is filtered out by conditional_mark).
    """
    return _dut_peer_ips_for_types(duthost, _T0_LAYER2_TYPES, is_v4)


def dut_t0_peer_ips(duthost, family="ipv4"):
    """Public wrapper: DUT-side BGP peer IPs for T0 neighbors of the given family."""
    return _dut_peer_ips_for_types(
        duthost, _T0_LAYER2_TYPES, is_v4=(family == "ipv4"),
    )


def dut_t2_peer_ips(duthost, family="ipv4"):
    """Public: DUT-side BGP peer IPs for T2-tier neighbors
    (SpineRouter / UpperSpine / LowerSpine / RegionalHub / AZNGHub).
    """
    return _dut_peer_ips_for_types(
        duthost, _T2_LAYER2_TYPES, is_v4=(family == "ipv4"),
    )


def _dut_inject_inbound_community(duthost, prefix, community):
    """Apply ``set community ... additive`` on the DUT's inbound route-map(s)
    for every T0 BGP peer.

    Attaches the route-map to *all* T0 peers (not just the one specific
    cEOS T0 that originated the route) -- that's why no T0 host handle is
    needed.  This is semantically safe: only the T0 that actually
    advertised the prefix will trigger the match, others see the route-map
    but get no match.

    Uses vtysh ``configure terminal`` directly -- no GCU, since these
    additions are out-of-band and per-test ephemeral.

    Single-ASIC DUTs only (multi-ASIC is filtered out by conditional_mark).
    """
    is_v4 = ":" not in prefix
    pl_kw = "ip" if is_v4 else "ipv6"

    peer_ips = _dut_t0_peer_ips(duthost, is_v4=is_v4)
    if not peer_ips:
        pytest_assert(
            False,
            "Could not derive any DUT-side T0 BGP peer IPs (af={})".format(
                "ipv4" if is_v4 else "ipv6",
            ),
        )

    rm_name = "TIER_INJECT_IN_{}".format(
        prefix.replace(".", "_").replace(":", "_").replace("/", "_")
    )
    pl_name = "TIER_INJECT_PL_{}".format(
        prefix.replace(".", "_").replace(":", "_").replace("/", "_")
    )
    af_clause = "ipv4 unicast" if is_v4 else "ipv6 unicast"
    dut_asn = _get_dut_bgp_asn(duthost)

    cmds = [
        "configure terminal",
        "{} prefix-list {} seq 5 permit {}".format(pl_kw, pl_name, prefix),
        "route-map {} permit 5".format(rm_name),
        "match {} address prefix-list {}".format(pl_kw, pl_name),
        "set community {} additive".format(community),
        "exit",
        "route-map {} permit 10".format(rm_name),
        "exit",
    ]
    # Attach the route-map to each T0 peer (inbound).  Under FRR neighbor
    # scope must live inside the matching address-family for IPv6 to take
    # effect; we use the same pattern for IPv4 for symmetry.
    for peer_ip in peer_ips:
        cmds += [
            "router bgp {}".format(dut_asn),
            "address-family {}".format(af_clause),
            "neighbor {} route-map {} in".format(peer_ip, rm_name),
            "exit",
            "exit",
        ]
    cmd_str = " ".join("-c '{}'".format(c) for c in cmds)
    duthost.shell("vtysh {}".format(cmd_str), module_ignore_errors=False)

    # Use BGP route-refresh (no `soft`) so this works even when inbound
    # soft-reconfiguration is not enabled on the peer.
    for peer_ip in peer_ips:
        duthost.shell(
            "vtysh -c 'clear bgp {} in'".format(peer_ip),
            module_ignore_errors=True,
        )


def withdraw_contributing_from_t0(t0_host, prefix, community=None, duthost=None):
    """Undo a previous :func:`announce_contributing_from_t0` call.

    Removes the BGP ``network`` statement and the Null0 static route on
    cEOS T0, plus (if community was set) tears down the DUT-side inbound
    route-map / prefix-list that was attached.  ``module_ignore_errors=True``
    on every call so cleanup is best-effort and never raises in fixture
    teardown.
    """
    af = _af_for_prefix(prefix)
    is_v4 = af == "ipv4"
    af_clause = "ipv4" if is_v4 else "ipv6"

    asn = _EOS_ASN_CACHE.get(getattr(t0_host, "hostname", str(t0_host)))
    bgp_vrf = _get_eos_bgp_vrf(t0_host)
    if asn is None:
        try:
            asn = _get_eos_bgp_asn(t0_host)
        except Exception as exc:
            logger.warning("withdraw: could not resolve ASN on %s: %s", t0_host, exc)
            return

    logger.info(
        "T0 %s withdraw %s%s",
        getattr(t0_host, "hostname", t0_host),
        prefix,
        " community={} (cleanup DUT-side inbound route-map)".format(community) if community else "",
    )

    # 1. Tear down DUT-side inbound community injection (mirror of announce)
    if community and duthost is not None:
        _dut_cleanup_inbound_community(duthost, prefix)

    # 2. Remove BGP network statement on T0 cEOS
    parents = ["router bgp {}".format(asn)]
    if bgp_vrf:
        parents.append("vrf {}".format(bgp_vrf))
    parents.append("address-family {}".format(af_clause))
    t0_host.eos_config(
        lines=["no network {}".format(prefix)],
        parents=parents,
        module_ignore_errors=True,
    )

    # 3. Remove the Null0 static route on T0 cEOS
    t0_host.eos_config(
        lines=[_eos_null0_route_cmd(t0_host, prefix, is_v4=is_v4, withdraw=True)],
        module_ignore_errors=True,
    )


def _dut_cleanup_inbound_community(duthost, prefix):
    """Undo what :func:`_dut_inject_inbound_community` set up.

    Detaches the inbound route-map from every T0 peer on the DUT, deletes
    the route-map and prefix-list, and triggers a route refresh inbound to
    re-evaluate routes without the tag.

    Single-ASIC DUTs only (multi-ASIC is filtered out by conditional_mark).
    """
    is_v4 = ":" not in prefix
    pl_kw = "ip" if is_v4 else "ipv6"

    rm_name = "TIER_INJECT_IN_{}".format(
        prefix.replace(".", "_").replace(":", "_").replace("/", "_")
    )
    pl_name = "TIER_INJECT_PL_{}".format(
        prefix.replace(".", "_").replace(":", "_").replace("/", "_")
    )

    try:
        peer_ips = _dut_t0_peer_ips(duthost, is_v4=is_v4)
    except Exception as exc:
        logger.warning(
            "withdraw: cannot derive T0 peer IPs on DUT: %s; skipping route-map "
            "detach (route-map will be reaped by t1_tagging_clean_config rollback)",
            exc,
        )
        return

    af_clause = "ipv4 unicast" if is_v4 else "ipv6 unicast"
    dut_asn = _get_dut_bgp_asn(duthost)
    cmds = ["configure terminal"]
    for peer_ip in peer_ips:
        cmds += [
            "router bgp {}".format(dut_asn),
            "address-family {}".format(af_clause),
            "no neighbor {} route-map {} in".format(peer_ip, rm_name),
            "exit",
            "exit",
        ]
    cmds += [
        "no route-map {} permit 5".format(rm_name),
        "no route-map {} permit 10".format(rm_name),
        "no {} prefix-list {}".format(pl_kw, pl_name),
    ]
    cmd_str = " ".join("-c '{}'".format(c) for c in cmds)
    duthost.shell("vtysh {}".format(cmd_str), module_ignore_errors=True)

    for peer_ip in peer_ips:
        duthost.shell(
            "vtysh -c 'clear bgp {} in'".format(peer_ip),
            module_ignore_errors=True,
        )


# ============================================================================
# PREFIX-LIST STATE INSPECTION (TC 1.5 / 1.6 / 1.7, TG3 post-checks)
# ============================================================================
# Multi-ASIC-safe `vtysh -c "show run"` wrapper.  Mirrors the function in
# tests/route/test_route_map_check.py::get_run_configs (~15 LOC); kept
# private here to avoid cross-suite churn for a single caller.  Promote to
# tests/common/helpers/frr_utils.py only when a third caller appears.
def _get_frr_running_configs(duthost):
    results = []
    if getattr(duthost, "is_multi_asic", False):
        for asic_id in range(len(duthost.asics)):
            out = duthost.command(
                'vtysh -n {} -c "show run"'.format(asic_id)
            ).get("stdout", "")
            results.append((str(asic_id), out))
    else:
        out = duthost.command('vtysh -c "show run"').get("stdout", "")
        results.append(("default namespace", out))
    return results


def get_prefix_list_entries(duthost, name, family="ipv4"):
    """Return list of prefix strings present in the named prefix-list.

    Parses ``vtysh -c "show run"`` so it is multi-ASIC safe.  When the DUT
    has multiple ASICs the entries from all namespaces are concatenated;
    callers that care about per-ASIC isolation should use
    :func:`_get_frr_running_configs` directly.
    """
    cfg_word = "ip" if family == "ipv4" else "ipv6"
    needle = "{} prefix-list {} ".format(cfg_word, name)
    rows = []
    for _asic, run_text in _get_frr_running_configs(duthost):
        for line in run_text.splitlines():
            stripped = line.strip()
            if stripped.startswith(needle):
                # last whitespace-separated token is the prefix
                rows.append(stripped.split()[-1])
    return rows


def assert_prefix_list_is_placeholder_only(duthost, name, family="ipv4"):
    """Assert the named prefix-list contains exactly the placeholder entry."""
    expected = PLACEHOLDER_V4 if family == "ipv4" else PLACEHOLDER_V6
    entries = get_prefix_list_entries(duthost, name, family)
    pytest_assert(
        entries == [expected],
        "prefix-list {} expected only [{}], got {}".format(name, expected, entries),
    )


def assert_prefix_list_contains(duthost, name, prefix, family="ipv4"):
    """Assert ``prefix`` is among the dynamic entries of the named prefix-list."""
    entries = get_prefix_list_entries(duthost, name, family)
    pytest_assert(
        prefix in entries,
        "prefix-list {} expected to contain {}, got {}".format(name, prefix, entries),
    )


def assert_prefix_list_excludes(duthost, name, prefix, family="ipv4"):
    """Assert ``prefix`` is NOT among the entries of the named prefix-list."""
    entries = get_prefix_list_entries(duthost, name, family)
    pytest_assert(
        prefix not in entries,
        "prefix-list {} expected to exclude {}, got {}".format(name, prefix, entries),
    )


# ============================================================================
# NEIGHBOR-SIDE ROUTE POLLING (shared by all 3 test modules)
# ============================================================================
# These wrap ``check_communities_on_neighbors`` / ``route_present_on_host``
# from tests/common/helpers/bgp_routing.py with a uniform ``wait_until``
# polling loop and standardised failure messages.  Use these helpers from
# test modules instead of rolling per-module copies; for DUT-authoritative
# leak / advertise checks pair them with
# ``assert_dut_{not_,}advertising`` below.

def _route_present_on(host, prefix):
    """Cheap presence probe via the canonical EOS/SONiC dispatcher."""
    from tests.common.helpers.bgp_routing import route_present_on_host
    return route_present_on_host(host, prefix)


def wait_route_present_on_neighbors(nbrhosts, neighbor_names, prefix,
                                    timeout=None):
    """Poll until EVERY neighbor in ``neighbor_names`` sees ``prefix``."""
    pytest_assert(
        wait_until(
            timeout or ROUTE_CONVERGE_TIMEOUT,
            ROUTE_CONVERGE_INTERVAL,
            0,
            lambda: all(
                _route_present_on(nbrhosts[n]["host"], prefix)
                for n in neighbor_names
            ),
        ),
        "Route {} expected to be present on all of {}".format(prefix, neighbor_names),
    )


def wait_route_absent_on_neighbors(nbrhosts, neighbor_names, prefix,
                                   timeout=None, duthost=None):
    """Poll until EVERY neighbor in ``neighbor_names`` has no path for ``prefix``.

    When ``duthost`` is supplied, a failure also dumps the DUT-side BGP
    table for the prefix and the first neighbor that still has it (with
    that neighbor's community list).  This distinguishes:
      * DUT never saw / suppressed the route -> dump empty on DUT side too.
      * DUT has the route but failed to suppress -> dump shows the route
        and downstream peer still sees it; engineer can inspect community
        to confirm the suppression input.

    Use this from suppression / leak-prevention tests; on TC 1.8/1.9 in
    particular the community list of the leaking neighbor immediately
    tells you whether the cEOS T0 injection carried 65525:110 through
    to the DUT.
    """
    from tests.closa.bgp_community_helpers_msft_internal import get_route_communities

    def _absent():
        return all(
            not get_route_communities(nbrhosts[n]["host"], prefix)
            and not _route_present_on(nbrhosts[n]["host"], prefix)
            for n in neighbor_names
        )

    if wait_until(timeout or ROUTE_CONVERGE_TIMEOUT,
                  ROUTE_CONVERGE_INTERVAL, 0, _absent):
        return

    msg = "Route {} expected to be absent on all of {}".format(prefix, neighbor_names)
    if duthost is not None:
        af_cmd = "show bgp ipv6" if ":" in prefix else "show ip bgp"
        try:
            dut_view = duthost.shell(
                "vtysh -c '{} {}'".format(af_cmd, prefix),
                module_ignore_errors=True,
            ).get("stdout", "")
        except Exception as exc:
            dut_view = "<dump failed: {}>".format(exc)
        leaking = None
        for n in neighbor_names:
            comms = get_route_communities(nbrhosts[n]["host"], prefix)
            if comms or _route_present_on(nbrhosts[n]["host"], prefix):
                leaking = (n, comms)
                break
        msg += (
            "\n--- DUT view of {} (`{} {}`):\n{}\n"
            "--- First neighbor with route: {}\n"
            "    community set on that neighbor: {}".format(
                prefix, af_cmd, prefix, dut_view,
                leaking[0] if leaking else "<none>",
                leaking[1] if leaking else "<none>",
            )
        )
    pytest_assert(False, msg)


def wait_communities_on_neighbors(nbrhosts, neighbor_names, prefix,
                                  expected, unexpected=None, timeout=None,
                                  duthost=None, prefix_list_names=None):
    """Poll until every neighbor carries ``expected`` and lacks ``unexpected``.

    When ``duthost`` is supplied, a convergence failure dumps real evidence
    instead of just stating expectations:

      * DUT-side ``show {ip|bgp ipv6} bgp <prefix>`` -- whether the DUT
        actually built / kept the aggregate, and which inputs it has.
      * DUT running BGP config snippet for ``aggregate-address`` and any
        prefix-list names passed via ``prefix_list_names`` (e.g.
        ``PL_AGG_V4`` / ``PL_AGG_CONTRIB_V4``) -- catches the case where
        bgpcfgd failed to re-render the route-map after a restart.
      * Per-neighbor community set actually observed -- shows whether the
        route arrived without the expected tag, or did not arrive at all.

    The dump is best-effort (every shell is ``module_ignore_errors``); a
    secondary failure inside the dump never masks the original assertion.
    """
    from tests.closa.bgp_community_helpers_msft_internal import (
        check_communities_on_neighbors,
        get_route_communities,
    )

    unexpected = unexpected or set()
    if wait_until(
        timeout or ROUTE_CONVERGE_TIMEOUT,
        ROUTE_CONVERGE_INTERVAL,
        0,
        check_communities_on_neighbors,
        nbrhosts, neighbor_names, prefix, expected, unexpected,
    ):
        return

    msg = "Route {} on {} did not converge to expected={}, unexpected={}".format(
        prefix, neighbor_names, expected, unexpected,
    )

    if duthost is not None:
        af_cmd = "show bgp ipv6" if ":" in prefix else "show ip bgp"
        try:
            dut_view = duthost.shell(
                "vtysh -c '{} {}'".format(af_cmd, prefix),
                module_ignore_errors=True,
            ).get("stdout", "")
        except Exception as exc:
            dut_view = "<dump failed: {}>".format(exc)

        # Aggregate-address + (optional) prefix-list snippets from running BGP.
        grep_terms = ["aggregate-address {}".format(prefix.split('/')[0])]
        for pl in (prefix_list_names or []):
            if pl:
                grep_terms.append("prefix-list {}".format(pl))
                grep_terms.append("match ip address prefix-list {}".format(pl))
                grep_terms.append("match ipv6 address prefix-list {}".format(pl))
        grep_expr = "|".join(grep_terms)
        try:
            run_cfg = duthost.shell(
                "show runningconfiguration bgp | grep -E -i '{}' || true"
                .format(grep_expr),
                module_ignore_errors=True,
            ).get("stdout", "")
        except Exception as exc:
            run_cfg = "<dump failed: {}>".format(exc)

        # Per-neighbor community sets (what each downstream actually sees).
        per_neighbor = []
        for n in neighbor_names:
            try:
                actual = get_route_communities(nbrhosts[n]["host"], prefix)
            except Exception as exc:
                actual = "<get_route_communities failed: {}>".format(exc)
            per_neighbor.append("    {}: {}".format(n, actual))

        msg += (
            "\n--- DUT view of {prefix} (`{cmd} {prefix}`):\n{dut_view}\n"
            "--- DUT running BGP config (aggregate / prefix-list / route-map):\n"
            "{run_cfg}\n"
            "--- Per-neighbor community sets actually observed:\n{per_nbr}"
        ).format(
            prefix=prefix, cmd=af_cmd,
            dut_view=dut_view or "<empty>",
            run_cfg=run_cfg or "<empty>",
            per_nbr="\n".join(per_neighbor) or "<none>",
        )
    pytest_assert(False, msg)


# ============================================================================
# DUT-SIDE ADVERTISED-ROUTES CHECK (testplan TC 1.8/1.9/1.10 step 4,
#                                   TC 2.1/2.2 step 4, TC 3.2 absence check)
# ============================================================================
# Neighbor-side polling helpers (route_present_on_host / get_route_communities
# in tests/common/helpers/bgp_routing.py) silently swallow exceptions and
# return False / empty -- so a transient SSH / eAPI failure on a T2 / T0
# neighbor is indistinguishable from a real absence, which can let a
# suppression test pass spuriously.
#
# The DUT-side `show {ip|bgp ipv6} bgp neighbors <peer> advertised-routes`
# command is authoritative for what the DUT actually places in its
# Adj-RIB-Out for each peer (i.e. exactly what the outbound TIER2 route-map
# decides).  Failures here represent real DUT problems and are surfaced
# rather than swallowed.

def _adv_routes_cmd(peer_ip):
    is_v6 = ":" in peer_ip
    family = "ipv6" if is_v6 else "ipv4"
    return ("vtysh -c 'show bgp {} neighbors {} advertised-routes json'"
            .format(family, peer_ip))


def dut_advertises_to_peer(duthost, peer_ip, prefix):
    """Return True iff DUT is currently advertising ``prefix`` to ``peer_ip``.

    Parses the JSON form of
        show {ip|bgp ipv6} bgp neighbors <peer> advertised-routes
    which reports the DUT's Adj-RIB-Out for that peer.

    Raises on shell / JSON failures: unlike neighbor-side polling, this
    runs on the DUT and a failure here means a real DUT problem (not
    transient neighbor SSH flakiness) and MUST be surfaced rather than
    silently treated as "absent".
    """
    out = duthost.shell(_adv_routes_cmd(peer_ip))["stdout"].strip()
    if not out:
        return False
    data = json.loads(out)
    advertised = data.get("advertisedRoutes", {}) or {}
    return prefix in advertised


def assert_dut_not_advertising(duthost, peer_ips, prefix,
                               timeout=None, interval=None):
    """Assert DUT is NOT advertising ``prefix`` to ANY peer in ``peer_ips``.

    Polls advertised-routes JSON until convergence; on timeout, fails with
    the list of peers that still see the route in DUT Adj-RIB-Out so the
    failing peer-group / route-map is obvious.
    """
    pytest_assert(peer_ips, "No peer IPs supplied -- cannot verify advertised-routes")
    timeout = timeout or ROUTE_CONVERGE_TIMEOUT
    interval = interval or ROUTE_CONVERGE_INTERVAL

    leaked = []

    def _none_advertised():
        leaked[:] = [
            ip for ip in peer_ips
            if dut_advertises_to_peer(duthost, ip, prefix)
        ]
        return not leaked

    if wait_until(timeout, interval, 0, _none_advertised):
        return
    pytest_assert(
        False,
        "DUT is still advertising {} to peer(s) {} after {}s "
        "(advertised-routes check)".format(prefix, leaked, timeout),
    )


def assert_dut_advertising(duthost, peer_ips, prefix,
                           timeout=None, interval=None):
    """Assert DUT IS advertising ``prefix`` to ALL peers in ``peer_ips``."""
    pytest_assert(peer_ips, "No peer IPs supplied -- cannot verify advertised-routes")
    timeout = timeout or ROUTE_CONVERGE_TIMEOUT
    interval = interval or ROUTE_CONVERGE_INTERVAL

    missing = []

    def _all_advertised():
        missing[:] = [
            ip for ip in peer_ips
            if not dut_advertises_to_peer(duthost, ip, prefix)
        ]
        return not missing

    if wait_until(timeout, interval, 0, _all_advertised):
        return
    pytest_assert(
        False,
        "DUT is NOT advertising {} to peer(s) {} after {}s "
        "(advertised-routes check)".format(prefix, missing, timeout),
    )


# ============================================================================
# CONFIG_DB DRAIN CHECK (TC 1.7 + TG3 post-checks)
# ============================================================================
def assert_no_stale_aggregate_rows(duthost):
    """Assert there are zero BGP_AGGREGATE_ADDRESS rows in CONFIG_DB."""
    keys = duthost.shell(
        "redis-cli -n 4 KEYS '{}|*'".format(BGP_AGGREGATE_ADDRESS)
    )["stdout"].strip()
    pytest_assert(
        keys == "",
        "Stale CONFIG_DB rows under {}: {}".format(BGP_AGGREGATE_ADDRESS, keys),
    )


# ============================================================================
# CHURN PRIMITIVES (TC 3.3 only)
# ============================================================================
# Direct sonic-db-cli writes; per testplan §CONFIG_DB Write Strategy this
# bypasses GCU to actually stress the bgpcfgd -> FRR write path.

def db_add_cmd_for(prefix, agg_pl, contrib_pl,
                   bbr_required=False, summary_only=False, as_set=False):
    """Build the ``sonic-db-cli HSET`` command line to add an aggregate row."""
    key = "{}|{}".format(BGP_AGGREGATE_ADDRESS, prefix)
    return (
        "sonic-db-cli CONFIG_DB HSET '{}' "
        "'bbr-required' '{}' 'summary-only' '{}' 'as-set' '{}' "
        "'aggregate-address-prefix-list' '{}' "
        "'contributing-address-prefix-list' '{}'"
    ).format(
        key,
        "true" if bbr_required else "false",
        "true" if summary_only else "false",
        "true" if as_set else "false",
        agg_pl,
        contrib_pl,
    )


def db_del_cmd_for(prefix):
    """Build the ``sonic-db-cli DEL`` command line to remove an aggregate row."""
    return "sonic-db-cli CONFIG_DB DEL '{}|{}'".format(BGP_AGGREGATE_ADDRESS, prefix)


# ============================================================================
# Module-scoped baseline fixture (used by all 3 test modules)
# ============================================================================
def _purge_aggregate_table(duthost):
    """Delete every BGP_AGGREGATE_ADDRESS row directly via sonic-db-cli.

    Used at module start so:
      * the GCU checkpoint we take reflects a truly empty BGP_AGGREGATE_ADDRESS
        table (not whatever a previous half-failed test run left behind);
      * the initial ``assert_prefix_list_is_placeholder_only`` in TC 1.5 / 1.7
        sees a clean state regardless of prior runs.

    Cannot use ``gcu_remove_aggregate`` here: GCU rejects an
    ``op=remove`` patch when it would leave a CONFIG_DB table empty
    ("given patch is not valid because it will result in empty tables").
    Direct ``sonic-db-cli DEL`` bypasses that validation; bgpcfgd
    handles the resulting CONFIG_DB notification cleanly.
    """
    keys_out = duthost.shell(
        "sonic-db-cli CONFIG_DB KEYS 'BGP_AGGREGATE_ADDRESS|*'",
        module_ignore_errors=True,
    ).get("stdout", "").strip()
    if not keys_out:
        return
    prefixes = [k.split("|", 1)[1] for k in keys_out.splitlines() if "|" in k]
    logger.info("Purging %d stale BGP_AGGREGATE_ADDRESS rows: %s", len(prefixes), prefixes)
    for prefix in prefixes:
        db_remove_aggregate(duthost, prefix)


@pytest.fixture(scope="module")
def t1_tagging_clean_config(duthosts, rand_one_dut_hostname,
                            require_t1_tagging_image):
    """Take a GCU checkpoint at module start; rollback + delete on module exit.

    Before checkpointing, **purge any stale BGP_AGGREGATE_ADDRESS rows**
    left by a previous half-failed test run.  Without this step, a single
    previous failure can permanently poison every subsequent run because
    the GCU checkpoint then captures the polluted state.

    Combined with the per-test ``aggr_cleanup`` fixture, this gives every
    test a clean slate without paying the cost of a full ``config_reload``
    between cases.
    """
    from tests.common.gcu_utils import (
        create_checkpoint, delete_checkpoint, rollback_or_reload,
    )
    duthost = duthosts[rand_one_dut_hostname]

    # Pre-cleanup: drop any stale aggregate rows from prior runs
    _purge_aggregate_table(duthost)

    create_checkpoint(duthost)
    # Brief settle to ensure the checkpoint reflects steady BGP state.
    time.sleep(BGP_SETTLE_WAIT)
    try:
        yield
    finally:
        # Post-cleanup: purge again before rollback in case a test left rows
        # the checkpoint did not know about (e.g. direct sonic-db-cli HSET).
        _purge_aggregate_table(duthost)
        try:
            rollback_or_reload(duthost, fail_on_rollback_error=False)
        finally:
            delete_checkpoint(duthost)


# ============================================================================
# Per-test cleanup fixtures (shared by all 3 test modules)
# ============================================================================
# These ride on top of the module-scoped ``t1_tagging_clean_config`` rollback
# but kick in *per test* so a single failing case doesn't leak state into the
# next.  Re-exported via ``tests/bgp/conftest.py`` so test modules can use
# them by parameter name without importing.

@pytest.fixture
def aggr_cleanup(duthosts, rand_one_dut_hostname):
    """Best-effort removal of any aggregate prefix added during the test.

    Tests record prefixes by calling the yielded ``track(prefix)`` function.
    Cleanup runs even on test failure; the module-scoped
    ``t1_tagging_clean_config`` rollback is the ultimate safety net.

    Uses ``db_remove_aggregate`` (sonic-db-cli DEL) rather than a GCU
    ``op=remove`` patch so we are not silently blocked by GCU's
    no-empty-table rule when the test only added a single aggregate.
    """
    duthost = duthosts[rand_one_dut_hostname]
    tracked = []
    yield tracked.append
    for prefix in tracked:
        db_remove_aggregate(duthost, prefix)


@pytest.fixture
def t0_announce_cleanup(nbrhosts, t1_neighbors,
                        duthosts, rand_one_dut_hostname):
    """Best-effort withdrawal of any T0-side announcements made during the test.

    Tests record ``(prefix, community=None)`` via the yielded ``track``
    function.  Cleanup passes ``duthost`` through to
    ``withdraw_contributing_from_t0`` so DUT-side inbound route-map /
    prefix-list pieces (added by community injections) are torn down too.
    """
    t0_host = nbrhosts[t1_neighbors.t0[0]]["host"]
    duthost = duthosts[rand_one_dut_hostname]
    tracked = []
    yield lambda prefix, community=None: tracked.append((t0_host, prefix, community))
    for host, prefix, community in tracked:
        try:
            withdraw_contributing_from_t0(host, prefix, community, duthost=duthost)
        except Exception as exc:
            logger.warning("Cleanup: failed to withdraw %s: %s", prefix, exc)
