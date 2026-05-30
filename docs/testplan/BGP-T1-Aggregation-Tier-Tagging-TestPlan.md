# BGP T1 Aggregation Tier-Based Community Tagging Test Plan

- [Overview](#overview)
  - [Scope](#scope)
  - [Background: T1 Aggregation Strategy](#background-t1-aggregation-strategy)
- [Topology and Setup Configuration](#topology-and-setup-configuration)
  - [Testbed Topology](#testbed-topology)
  - [Prerequisites](#prerequisites)
  - [Community Tag Reference](#community-tag-reference)
  - [Route-Map / Prefix-List Reference](#route-map--prefix-list-reference)
- [Route Validation Approach](#route-validation-approach)
- [Test Cases](#test-cases)
  - [Test Group 1: T1→T2 Upstream — TO_TIER2 Aggregate Tagging and Contributing Suppression](#test-group-1-t1t2-upstream--to_tier2-aggregate-tagging-and-contributing-suppression)
  - [Test Group 2: T1→T0 Downstream — Aggregate Leak Prevention](#test-group-2-t1t0-downstream--aggregate-leak-prevention)
  - [Test Group 3: Lifecycle Operations with Community Verification](#test-group-3-lifecycle-operations-with-community-verification)

> **Note**: This plan only covers the T1 (`LeafRouter`) DUT side. The producer side of the suppression contract — `TO_TIER1_V4/V6` seq 100 on a `ToRRouter` / `BackEndToRRouter` DUT — is out of scope. The `TO_BGP_SENTINEL` / `TO_BGPMON_V6` outbound aggregate tagging is also out of scope here — it is already covered byte-for-byte by the bgpcfgd template unit tests (see [Out of Scope](#out-of-scope)).

---

## Overview

This test plan covers test scenarios for the **T1 aggregation tier-based community tagging** feature delivered by the FRR template changes in `dockers/docker-fpm-frr/frr/bgpd/templates/msft.general/{v4,v6}.{leaf.spine,leaf.tor.all,tor}/policy.conf.j2`. (The same feature also adds aggregate-tagging clauses to the `sentinels` / `msft.monitors` route-maps; their template-side correctness is verified by the bgpcfgd template UTs and is **out of scope** for this plan — see [Out of Scope](#out-of-scope).) These tests validate the route-map and community behavior as observed on T1's `T0` / `T2` neighbors.

### Scope

In this T1 deployment, instead of using `summary-only` aggregation (which would suppress contributing routes), the T1 (`LeafRouter`) advertises **both** the aggregate route and contributing routes upward to T2 (`SpineRouter`/`UpperSpineRouter`/`RegionalHub`/`AZNGHub`), each handled by distinct community-driven route-map rules. Downstream neighbors (T0 / `ToRRouter`) must NEVER see the synthetic aggregate, only the original contributing prefixes.

This tagging is implemented natively in the FRR template (no `vtysh` hot-patch required). The `aggregate-address-prefix-list` and `contributing-address-prefix-list` populated by `AggregateAddressMgr` (in `bgpcfgd`) drive the route-map matching at runtime; the template's placeholder prefix-lists (`127.0.0.1/32` / `::1/128`) keep the policy a no-op until the prefix-lists are populated.

### Background: T1 Aggregation Strategy

This design does NOT use `summary-only=true` on T1. Instead:

1. **Both aggregate and contributing routes are advertised upstream** to T2 / RH / AZNG / RWA neighbors.
2. **Aggregate routes are tagged** with `COMM_AGG_T1 = 65525:21` so that T2/RH can identify and prefer them.
3. **Contributing routes can be selectively suppressed** at T1 if and only if T0 has tagged them upstream with `COMM_SUPPRESS_ON_T1 = 65525:110`. T0 performs this tagging itself: its `TO_TIER1_V4/V6` route-map has a seq 100 entry that matches prefixes in `SUPPRESS_ON_T1_IPV{4,6}_PREFIX` and applies `set community 65525:110 additive`.
4. **Aggregate routes are denied toward T0** by an explicit deny on `AGGREGATE_ROUTES_V4/V6`, preventing aggregation leakage downstream.

| Scenario | Direction | Aggregate Community | Contributing Behavior |
|----------|-----------|---------------------|-----------------------|
| **T1 → T2 (upstream)** | out | `65525:21` (`COMM_AGG_T1`) | Permitted by catch-all unless tagged `65525:110` (`COMM_SUPPRESS_ON_T1`); seq 300 deny then drops it |
| **T1 → T0 (downstream)** | out | denied | Permitted by catch-all (T1 doesn't withhold contributing from T0) |
| **T0 → T1 (upstream)** | out | n/a (T0 doesn't aggregate) | Prefixes in `SUPPRESS_ON_T1_IPV{4,6}_PREFIX` are tagged `65525:110` (`COMM_SUPPRESS_ON_T1`); others go via catch-all untagged |

> The T1 → Sentinel / T1 → IPv6 BGPMon outbound tagging directions are not validated by this plan — see [Out of Scope](#out-of-scope) for the rationale (covered byte-for-byte by `src/sonic-bgpcfgd/tests/test_templates.py`).

---

## Topology and Setup Configuration

### Testbed Topology

Tests run on a **t1** topology. The DUT is the T1 (`LeafRouter`) device peering with T0 (`ToRRouter`) downstream and T2 (`SpineRouter`/`UpperSpineRouter`/`LowerSpineRouter`) upstream neighbors. No `BGP_SENTINELS` / `BGP_MONITORS` peer is required for any test case in this plan (Sentinel / BGPMon outbound tagging is validated at the template unit-test layer — see [Out of Scope](#out-of-scope)).

```
        [T2 - SpineRouter]            [T2 - SpineRouter]
        (upstream:                    (upstream:
         validates 65525:21            validates 65525:21
         on aggregate;                 on aggregate;
         injects 65525:110 from T0     validates contributing
         to test seq 300 deny)         visibility for catch-all)
              |                              |
         eBGP session                   eBGP session
         (route-map: TO_TIER2_V4/V6)
              |                              |
   +----------+------------------------------+----------+
   |               DUT (T1 - LeafRouter)                |
   |  Internal FRR template with                         |
   |  tier-based community tagging route-maps:           |
   |    TO_TIER2_V4/V6  (out → T2)                       |
   |    TO_TIER0_V4/V6  (out → T0)                       |
   |  Placeholder prefix-lists populated at runtime by   |
   |    AggregateAddressMgr from CONFIG_DB.              |
   +----------+------------------------------+----------+
              |                              |
         eBGP session                   eBGP session
         (route-map: TO_TIER0_V4/V6)
              |                              |
        [T0 - ToRRouter]              [T0 - ToRRouter]
        (downstream: originates       (downstream: originates
         contributing routes;          contributing routes;
         can tag 65525:110 to test     verifies aggregate
         suppression)                  is NOT received)
```

### Prerequisites

1. **Image baseline**: DUT MUST be running a SONiC image built from the **MSFT-internal `Networking-acs-buildimage` repo** (the corporate fork of `sonic-buildimage`). All FRR templates referenced by this plan (`msft.general/{v4,v6}.{leaf.spine,leaf.tor.all,tor}/policy.conf.j2`, `sentinels/policies.conf.j2`, `msft.monitors/policies.conf.j2`) and the placeholder prefix-lists / community-lists / route-maps they render exist **only** in that fork; standard public-image SONiC builds (e.g. `sonic-vs` from the upstream `sonic-buildimage`) render the plain `general/*` templates and will not satisfy any case in this plan — the entire suite MUST be skipped on those images. The production testbeds targeted by this plan are already provisioned with the internal image, so no extra image-swap is required; tests SHOULD detect the image flavor at session-startup (for example, by checking whether `vtysh -c "show route-map TO_TIER2_V4"` returns a non-empty result and whether `bgp community-list COMM_AGG_T1` exists) and `pytest.skip(...)` the module cleanly otherwise.
2. FRR template must include:
   - Placeholder prefix-lists `AGGREGATE_ROUTES_V4/V6` (`127.0.0.1/32` / `::1/128`)
   - Placeholder prefix-lists `AGGREGATE_CONTRIBUTING_ROUTES_V4/V6`
   - Placeholder prefix-lists `SUPPRESS_ON_T1_IPV4_PREFIX` / `SUPPRESS_ON_T1_IPV6_PREFIX` (T0 templates only — used by the T0 producer side, not directly verified by this plan)
   - `community-list standard COMM_AGG_T1 permit 65525:21`
   - `community-list standard COMM_SUPPRESS_ON_T1 permit 65525:110`
   - Route-map `TO_TIER2_V4/V6` with seq 100 / 200 / 300 / 10000
   - Route-map `TO_TIER0_V4/V6` with seq 400 deny aggregate
3. BGP sessions must be established with all T0 and T2 neighbors.
4. `AggregateAddressMgr` must be running and subscribing to `CONFIG_DB:BGP_AGGREGATE_ADDRESS`.
5. The `aggregate-address-prefix-list` / `contributing-address-prefix-list` field values used in CONFIG_DB MUST match the prefix-list names embedded in the FRR template (`AGGREGATE_ROUTES_V4/V6`, `AGGREGATE_CONTRIBUTING_ROUTES_V4/V6` on T1). Mismatched names create orphan prefix-lists with no route-map effect.
6. Test Cases 1.8–1.10 (T1→T2 suppression) and TC 3.3 (rapid churn) require ExaBGP (or a cooperating cEOS neighbor) capable of injecting routes with arbitrary BGP communities.

### DUT Role Detection

This plan is exclusively for `LeafRouter` DUTs in a `t1` topology, so the only role check needed is a defensive skip on non-`LeafRouter` images that happen to match `t1`. Use the same `config_facts` probe already in use across `sonic-mgmt-int` ([tests/copp/test_copp.py:371](../../tests/copp/test_copp.py#L371), [tests/common/helpers/drop_counters/drop_counters.py:138](../../tests/common/helpers/drop_counters/drop_counters.py#L138)):

```python
cfg_facts = duthost.config_facts(host=duthost.hostname, source="running")["ansible_facts"]
dut_type  = cfg_facts["DEVICE_METADATA"]["localhost"]["type"]   # expected: 'LeafRouter'
if dut_type != "LeafRouter":
    pytest.skip(f"This plan targets LeafRouter only; got dut_type={dut_type}")
```

A single session-scoped fixture (e.g. `require_t1_tagging_image`) keeps every test case free of repeated probing.

### Community Tag Reference

| Tag | Value | Set By | Matched By |
|-----|-------|--------|------------|
| `COMM_AGG_T1` | `65525:21` | T1 `TO_TIER2_V4/V6` seq 200 (also set on `TO_BGP_SENTINEL` / `TO_BGPMON_V6` — out of scope for this plan, see [Out of Scope](#out-of-scope)) | T2 / RH / AZNG — to identify aggregate origin |
| `COMM_SUPPRESS_ON_T1` | `65525:110` | T0 (`TO_TIER1_V4/V6` seq 100, on prefixes in `SUPPRESS_ON_T1_IPV{4,6}_PREFIX`) or any upstream operator | T1 (`TO_TIER2_V4/V6` seq 300 deny, with prefix-list AND community match) |

### Route-Map / Prefix-List Reference

| Object | Template | Direction | Purpose |
|--------|----------|-----------|---------|
| `TO_TIER2_V4` / `TO_TIER2_V6` | `msft.general/{v4,v6}.leaf.spine/policy.conf.j2` | out (T1→T2) | seq 100 deny `UPSTREAM_PREFIX`; seq 200 permit aggregate, set `65525:21`; seq 300 deny suppressed contributing; seq 10000 catch-all permit |
| `TO_TIER0_V4` / `TO_TIER0_V6` | `msft.general/{v4,v6}.leaf.tor.all/policy.conf.j2` | out (T1→T0) | seq 400 deny aggregate |
| `TO_TIER1_V4` / `TO_TIER1_V6` | `msft.general/{v4,v6}.tor/policy.conf.j2` | out (T0→T1) | seq 100 permit `SUPPRESS_ON_T1_IPV{4,6}_PREFIX`, set `65525:110` additive (i.e. T0 marks the contributing prefixes T1 should later suppress); seq 1000 catch-all permit — context only; the T0 producer side is out of scope for this plan |
| `AGGREGATE_ROUTES_V4` / `AGGREGATE_ROUTES_V6` | T1 templates | n/a | placeholder + runtime-populated; matched in seq 200 of `TO_TIER2_*` (and in `TO_BGP_SENTINEL` / `TO_BGPMON_V6` — both out of scope) |
| `AGGREGATE_CONTRIBUTING_ROUTES_V4/V6` | T1 templates | n/a | placeholder + runtime-populated; matched in seq 300 of `TO_TIER2_*` (with `COMM_SUPPRESS_ON_T1`) |

---

## Route Validation Approach

All test cases validate behavior by checking **routes and their community attributes as received by the DUT's neighbors** combined with **route-map static state on the DUT**. The feature is treated as a black box at the data path; route-map content is checked at the configuration plane to catch template/name regressions early.

### Neighbor Classification Convention

Tests in this plan classify `nbrhosts` entries in two layers. The general `endswith(<vm-suffix>)` style is already in use by [test_prefix_list_internal_only.py:293](../../tests/bgp/test_prefix_list_internal_only.py#L293) (which scopes by `endswith("T1")`); this plan applies the same idea to `"T0"` and `"T2"` suffixes:

- **Layer 1 — VM-name suffix** for layered neighbors:
  - `*T0` → downstream (`ToRRouter` / `BackEndToRRouter`)
  - `*T2` → upstream spine-tier (`SpineRouter` / `UpperSpineRouter` / `LowerSpineRouter`)
  - Example: `t0_neighbors = [n for n in nbrhosts.keys() if n.endswith('T0')]`
- **Layer 2 — `DEVICE_NEIGHBOR_METADATA[*]['type']`** for role-named neighbors that don't follow the suffix convention (`RegionalHub`, `AZNGHub`, etc.):
  ```python
  cfg = duthost.config_facts(host=duthost.hostname, source="running")["ansible_facts"]
  meta = cfg["DEVICE_NEIGHBOR_METADATA"]
  rh_names = [k for k, v in meta.items() if v["type"] == "RegionalHub"]
  rh_neighbors = [host for name, host in nbrhosts.items() if name in rh_names]
  ```
- Whenever a test below says **"on T2"**, it means **the union of**:
  - Layer-1 `*T2` `nbrhosts` entries, AND
  - Layer-2 entries whose `DEVICE_NEIGHBOR_METADATA` `type` is `SpineRouter` / `UpperSpineRouter` / `LowerSpineRouter` / `RegionalHub` / `AZNGHub`.
- Whenever a test says **"on T0"**, it means **Layer-1 `*T0` `nbrhosts` entries**, optionally augmented by Layer-2 `ToRRouter` / `BackEndToRRouter` if any such role-named entries exist.

### On T2 (Upstream) Neighbors — Verify Route Communities

1. **Aggregate route**: prefix received with community `65525:21`, NOT `65525:110`.
2. **Contributing routes**: received without DUT-added tags unless tagged at injection time.
3. **Suppressed contributing routes**: when injected with `65525:110` from T0, MUST NOT be received on T2.
4. **`UPSTREAM_PREFIX` loop check**: routes carrying community `8075:54000` must be denied (existing behavior, must remain intact).

### On T0 (Downstream) Neighbors — Verify Aggregate is Hidden

1. Aggregate route MUST NOT be received on T0 (`TO_TIER0_*` seq 400 deny).
2. All other routes the DUT advertises to T0 follow existing policy unchanged.

### Reading Communities on Neighbors

For every test case below that asserts "on T2: prefix received with community X", reuse the existing dual-NOS helper [`get_route_communities(host, prefix)`](../../tests/bgp/test_bgp_aggregate_address_community_tagging_msft_internal.py) and its polling wrapper [`check_communities_on_neighbors(nbrhosts, neighbor_list, prefix, expected, unexpected)`](../../tests/bgp/test_bgp_aggregate_address_community_tagging_msft_internal.py) (defined in the same file, lines 328–400). They already cover:

| Neighbor kind | Underlying command | JSON path |
|---|---|---|
| **cEOS** (Arista vEOS / `EosHost`) | `EosHost.get_route(prefix)` → `show ip bgp <prefix>` (or `show ipv6 bgp <prefix>`) with `output=json` — see [tests/common/devices/eos.py::EosHost.get_route](../../tests/common/devices/eos.py#L325) | `vrfs.default.bgpRouteEntries.<prefix>.bgpRoutePaths[*].routeDetail.communityList` |
| **SONiC** (FRR / `SonicHost`) | `vtysh -c "show ip bgp <prefix> json"` | `paths[*].community.list[*].string` |

Usage pattern proven by [test_bgp_aggregate_address_community_tagging_msft_internal.py:2547–2590](../../tests/bgp/test_bgp_aggregate_address_community_tagging_msft_internal.py#L2547-L2590):

```python
from tests.bgp.test_bgp_aggregate_address_community_tagging_msft_internal import (
    get_route_communities,
    check_communities_on_neighbors,
)

# Single-host single-shot read
actual = get_route_communities(nbrhosts[t2_name]["host"], AGGR_V4)
pytest_assert("65525:21" in actual,
              "Aggregate missing 65525:21 — got {}".format(actual))

# Multi-host polling assertion — preferred for any case with convergence latency
pytest_assert(
    wait_until(60, 2, 0, check_communities_on_neighbors,
               nbrhosts, t2_names, AGGR_V4,
               expected={"65525:21"}, unexpected={"65525:110"}),
    "Aggregate community state did not converge on T2 within 60s",
)
```

**Action item**: when this feature lands, lift `get_route_communities` / `check_communities_on_neighbors` from the MA/OOB test file into [tests/common/helpers/bgp_routing.py](../../tests/common/helpers/bgp_routing.py) (next to the already-shared `verify_route_on_neighbors`). This plan and the MA/OOB plan will both import the canonical version. **Do not copy the helper bodies into this plan's test files.**

### On the DUT — Static Configuration Checks

1. `vtysh -c "show running-config"` contains the expected placeholder `ip prefix-list` entries.
2. `vtysh -c "show route-map <name>"` returns the expected sequence of `permit` / `deny` clauses with the documented `match` and `set` actions.
3. `vtysh -c "show bgp community-list <name>"` returns the expected community values.

### Route-Map / Prefix-List Inspection Strategy

FRR's `show route-map X json` output is **not reliable across the FRR versions shipped in SONiC** (no in-repo test currently consumes it — the one docstring mention in [test_route_map_check.py](../../tests/route/test_route_map_check.py) explicitly falls back to text). This plan adopts the two patterns already proven in-repo, depending on the assertion granularity needed:

#### Pattern A — Token-presence grep (lightweight)

Use when a test only needs to know *whether a token is present anywhere in a named route-map* (e.g. "`AGGREGATE_ROUTES_V4` is referenced", "`65525:21` appears somewhere"). This is the style already in [test_bgp_aggregate_address_community_tagging_msft_internal.py](../../tests/bgp/test_bgp_aggregate_address_community_tagging_msft_internal.py) lines 226 and 607–608:

```python
# Single-token check (returns True / False via rc)
duthost.shell(
    "vtysh -c 'show route-map TO_TIER2_V4' 2>/dev/null | grep -q '65525:21 additive'",
    module_ignore_errors=False,  # rc != 0 fails the assertion
)
# Or capture and assert in Python — works equally well on multi-asic via `vtysh -n <asic>`
output = duthost.shell("vtysh -c 'show route-map TO_TIER2_V4'")["stdout"]
assert "AGGREGATE_ROUTES_V4" in output
assert "65525:21" in output
```

Applicable test cases: TG 1 runtime behavior verification (tagging + suppression).

#### Pattern B — Structured `show run` block walker (precise) — *deferred*

Used when a test must distinguish between sequence numbers, permit vs deny, or assert that a `match` / `set` lives in a *specific* clause. The state-machine reference implementation is [test_route_map_check.py::verify_v6_next_hop_from_run](../../tests/route/test_route_map_check.py#L38-L75) (split lines, match `^route-map (\S+) (permit|deny) (\d+)`, accumulate body until `exit`).

**No test case in this plan currently needs Pattern B** — every TG 1 / TG 2 / TG 3 assertion in this document is satisfied by Pattern A (token-presence) plus neighbor-side route reading. Pattern B is documented here only as the agreed-upon approach when a future structural-assertion case appears; the `find_route_map_clause` / `assert_route_map_clause` helpers should be added **at that time**, not pre-emptively, to keep the helper surface aligned with actual callers.

#### Multi-ASIC handling

T1 LeafRouters in production are frequently multi-ASIC. For **`show run` parsing**, use the shared helper `get_frr_running_configs(duthost) -> list[tuple[str, str]]` (returns `[(asic_label, running_config_text), ...]`; `asic_label` is the ASIC id as string, or `"default namespace"` for single-ASIC). This helper is lifted **as-is** from [test_route_map_check.py::get_run_configs](../../tests/route/test_route_map_check.py#L15-L34) into a shared location — recommended new home [tests/common/helpers/frr_utils.py](../../tests/common/helpers/frr_utils.py) (new file) or as an additive append to [tests/bgp/bgp_helpers.py](../../tests/bgp/bgp_helpers.py). `test_route_map_check.py` should be updated to import from the new location (single-line change).

For **other ad-hoc `vtysh` commands** (`show route-map X`, `show ip prefix-list Y`, `show ip bgp <prefix>`, …), each test handles multi-ASIC inline by checking `duthost.is_multi_asic` and prefixing with `vtysh -n <asic_id>` — there is no in-repo helper that wraps arbitrary `vtysh` commands per ASIC, and adding one is out of scope for this plan. Each assertion runs once per ASIC and aggregates failures, matching the style of `test_route_map_check.test_route_map_check`.

This is the only refactor required for the route-map / `show run` inspection path. `verify_v6_next_hop_from_run` stays in `test_route_map_check.py` (domain-specific to that test; not generalized).

#### CONFIG_DB Write Strategy (GCU vs `sonic-db-cli`)

All `BGP_AGGREGATE_ADDRESS` mutations in this plan use the canonical 2-segment key `BGP_AGGREGATE_ADDRESS|<prefix>` — the YANG model [sonic-bgp-aggregate-address.yang](../../../Networking-acs-buildimage/src/sonic-yang-models/yang-models/sonic-bgp-aggregate-address.yang) declares `key "aggregate-address"` as the sole list key, and bgpcfgd's [`key2prefix(key)`](../../../Networking-acs-buildimage/src/sonic-bgpcfgd/bgpcfgd/managers_aggregate_address.py#L198-L200) parses the prefix as `key.split("|")[-1]`. There is no `default` VRF segment. Two write paths are used in this plan, by design:

| Path | When to use | Rationale |
|------|------------|-----------|
| **GCU** — [`gcu_add_community_aggregate`](../../tests/bgp/test_bgp_aggregate_address_community_tagging_msft_internal.py) (JSON patch `op=add path=/BGP_AGGREGATE_ADDRESS/<prefix-encoded>`) | TG 1 and TG 3 functional cases (TC 3.1, TC 3.2); any test that needs YANG validation, checkpoint/rollback, or coordinated multi-row writes | Same audit trail as production config pushes; rolls back cleanly via `rollback_or_reload(duthost)`; catches schema regressions early. |
| **Direct CONFIG_DB** — `sonic-db-cli CONFIG_DB HSET '<key>' ...` / `DEL '<key>'` | TC 3.3 churn loop **only** | GCU adds ~6s of overhead per write (config-engine + YANG validation + checkpoint rewrite); `sonic-db-cli HSET` is ~0.02s, which is the only way to actually stress the bgpcfgd → FRR write path. The pattern is the one already proven by [test_7_3_rapid_add_remove_cycling](../../tests/bgp/test_bgp_aggregate_address_scale_stress.py#L862-L867). Bypassing GCU intentionally trades audit / rollback safety for the ability to exercise the convergence behavior the test is targeting. |

Do NOT mix paths within the same test case (e.g. GCU-add then `sonic-db-cli DEL`); the GCU checkpoint state will not reflect the deletion and `rollback_or_reload` will undo the wrong thing.

---

## Test Cases

### Test Group 1: T1→T2 Upstream — TO_TIER2 Aggregate Tagging and Contributing Suppression

**Objective**: Validate both halves of the T1→T2 outbound `TO_TIER2_V4/V6` policy:
- **Tagging (TC 1.1–1.7)**: `BGP_AGGREGATE_ADDRESS` writes via `AggregateAddressMgr` populate the runtime prefix-lists, which cause the aggregate route advertised to T2 to be tagged with `COMM_AGG_T1` (`65525:21`).
- **Suppression (TC 1.8–1.10)**: contributing routes that T0 marked with `COMM_SUPPRESS_ON_T1` (`65525:110`) are withheld from T2, while all other contributing traffic passes through unchanged via the catch-all.

#### Test Case 1.1: Aggregate route tagged with 65525:21 toward T2 (IPv4)
- **Config**: `summary-only=false`, `aggregate-address-prefix-list=AGGREGATE_ROUTES_V4`, `contributing-address-prefix-list=AGGREGATE_CONTRIBUTING_ROUTES_V4`, `bbr-required=false`
- **Steps**:
  1. On DUT: write `BGP_AGGREGATE_ADDRESS|10.100.0.0/16` to CONFIG_DB with above fields
  2. Announce contributing routes `10.100.1.0/24`, `10.100.2.0/24` from T0 (or ExaBGP at T0 position)
  3. Wait for aggregate convergence
  4. On T2: verify aggregate route `10.100.0.0/16` is received
  5. On T2: verify community `65525:21` is attached to the aggregate
  6. On T2: verify `65525:110` is NOT present on the aggregate
  7. On T2: verify the aggregate community attribute equals exactly `{65525:21}` plus whatever the route already carried; nothing else added by DUT

#### Test Case 1.2: Aggregate route tagged with 65525:21 toward T2 (IPv6)
- **Intent**: IPv6 dual of TC 1.1 — same assertions, symmetric coverage.
- **Config**: IPv6 aggregate `2001:db8:100::/48`, `aggregate-address-prefix-list=AGGREGATE_ROUTES_V6`, `contributing-address-prefix-list=AGGREGATE_CONTRIBUTING_ROUTES_V6`, `summary-only=false`, `bbr-required=false`
- **Steps**:
  1. On DUT: write `BGP_AGGREGATE_ADDRESS|2001:db8:100::/48` to CONFIG_DB with above fields
  2. Announce contributing IPv6 routes `2001:db8:100:1::/64`, `2001:db8:100:2::/64` from T0 (or ExaBGP at T0 position)
  3. Wait for aggregate convergence
  4. On T2: verify aggregate route `2001:db8:100::/48` is received
  5. On T2: verify community `65525:21` is attached to the aggregate
  6. On T2: verify `65525:110` is NOT present on the aggregate
  7. On T2: verify the aggregate community attribute equals exactly `{65525:21}` plus whatever the route already carried; nothing else added by DUT

#### Test Case 1.3: Contributing routes traverse to T2 by catch-all (IPv4)
- **Steps**:
  1. Setup same as TC 1.1
  2. On T2: verify each contributing route `10.100.1.0/24` / `10.100.2.0/24` IS received
  3. On T2: verify the contributing route does NOT carry `65525:21` (DUT only tags aggregate)
  4. On T2: verify the contributing route does NOT carry `65525:110` (no suppression injected)
  5. Confirm seq 10000 catch-all of `TO_TIER2_V4` is the path taken

#### Test Case 1.4: Contributing routes traverse to T2 by catch-all (IPv6)
- **Steps**:
  1. Setup same as TC 1.2
  2. On T2: verify each contributing route `2001:db8:100:1::/64` / `2001:db8:100:2::/64` IS received
  3. On T2: verify the contributing route does NOT carry `65525:21`
  4. On T2: verify the contributing route does NOT carry `65525:110`
  5. Confirm seq 10000 catch-all of `TO_TIER2_V6` is the path taken

#### Test Case 1.5: Aggregate prefix-list populated dynamically
- **Steps**:
  1. Before adding aggregate: `vtysh -c "show ip prefix-list AGGREGATE_ROUTES_V4"` returns only the placeholder `127.0.0.1/32`
  2. After adding aggregate (Test Case 1.1 config): same command returns placeholder PLUS `permit 10.100.0.0/16`
  3. After deleting the CONFIG_DB entry: returns only the placeholder again

#### Test Case 1.6: Multiple aggregates share the same prefix-list
- **Steps**:
  1. Add aggregate A `10.100.0.0/16` with `aggregate-address-prefix-list=AGGREGATE_ROUTES_V4`
  2. Add aggregate B `10.200.0.0/16` with the SAME prefix-list name
  3. On T2: verify both aggregates received with `65525:21`
  4. Remove aggregate A
  5. On T2: verify A withdrawn, B still tagged with `65525:21`
  6. On DUT: `show ip prefix-list AGGREGATE_ROUTES_V4` shows placeholder + `10.200.0.0/16` only

#### Test Case 1.7: Shared prefix-list returns to placeholder after all aggregates are removed
- **Intent**: Full-drain variant of TC 1.5 / TC 1.6 — after **every** aggregate sharing a prefix-list is removed, no orphan dynamic entries remain.
- **Steps**:
  1. Add aggregate A `10.100.0.0/16` with `aggregate-address-prefix-list=AGGREGATE_ROUTES_V4`
  2. Add aggregate B `10.200.0.0/16` with the SAME prefix-list name
  3. On T2: verify both aggregates are received with community `65525:21`
  4. On DUT: `show ip prefix-list AGGREGATE_ROUTES_V4` shows placeholder + `10.100.0.0/16` + `10.200.0.0/16`
  5. Remove aggregate A from CONFIG_DB
  6. Remove aggregate B from CONFIG_DB
  7. On T2: verify both aggregates are withdrawn (neither `10.100.0.0/16` nor `10.200.0.0/16` is received)
  8. On DUT: `show ip prefix-list AGGREGATE_ROUTES_V4` shows ONLY the placeholder `127.0.0.1/32` — no leftover dynamic entries
  9. On DUT: `show ip prefix-list AGGREGATE_CONTRIBUTING_ROUTES_V4` likewise shows ONLY the placeholder (paired prefix-list MUST drain in lockstep)
  10. On DUT: `redis-cli -n 4 KEYS 'BGP_AGGREGATE_ADDRESS|*'` returns empty (no stale CONFIG_DB rows)

#### Test Case 1.8: Contributing tagged 65525:110 is suppressed toward T2 (IPv4)
- **Config**: Aggregate `10.100.0.0/16` with both prefix-lists configured so that `10.100.1.0/24` falls into `AGGREGATE_CONTRIBUTING_ROUTES_V4`
- **Steps**:
  1. From T0/ExaBGP, announce `10.100.1.0/24` carrying community `65525:110`
  2. On DUT: verify `vtysh -c "show ip bgp 10.100.1.0/24"` displays `Community: 65525:110`
  3. On T2: verify `10.100.1.0/24` is NOT received
  4. On DUT: verify `show ip bgp neighbor <T2> advertised-routes` does NOT contain `10.100.1.0/24`

#### Test Case 1.9: Contributing tagged 65525:110 is suppressed toward T2 (IPv6)
- **Config**: IPv6 aggregate `2001:db8:100::/48` with both prefix-lists configured so that `2001:db8:100:1::/64` falls into `AGGREGATE_CONTRIBUTING_ROUTES_V6`
- **Steps**:
  1. From T0/ExaBGP, announce `2001:db8:100:1::/64` carrying community `65525:110`
  2. On DUT: verify `vtysh -c "show bgp ipv6 2001:db8:100:1::/64"` displays `Community: 65525:110`
  3. On T2: verify `2001:db8:100:1::/64` is NOT received
  4. On DUT: verify `show bgp ipv6 neighbor <T2> advertised-routes` does NOT contain `2001:db8:100:1::/64`

#### Test Case 1.10: Suppression requires both "is a tracked contributing prefix" AND "carries 65525:110"
- **Intent**: T1 withholds a contributing route from T2 only when **both** A (prefix is in `AGGREGATE_CONTRIBUTING_ROUTES_V4`) AND B (route carries `65525:110`) hold. This case covers the two reverse cells (F,T) and (T,F); (T,T) is TC 1.8 and (F,F) is TC 1.3.
- **Note**: ``AggregateAddressMgr`` renders the contributing prefix-list as ``permit <aggregate> le 32``, so any subnet within ``10.100.0.0/16`` (e.g. ``10.100.99.0/24``) is implicitly contributing. The (A=False) reverse case therefore uses a prefix **outside** every test aggregate, e.g. ``10.222.99.0/24``.
- **Config**: Aggregate `10.100.0.0/16` with both prefix-lists configured so that `10.100.1.0/24` falls into `AGGREGATE_CONTRIBUTING_ROUTES_V4`
- **Steps (A false, B true)**:
  1. From T0/ExaBGP, announce `10.222.99.0/24` (NOT a contributing prefix — outside `AGGREGATE_CONTRIBUTING_ROUTES_V4`) carrying community `65525:110`
  2. On DUT: verify `vtysh -c "show ip bgp 10.222.99.0/24"` displays `Community: 65525:110`
  3. On T2: verify `10.222.99.0/24` IS received, with `65525:110` preserved and no DUT-added `65525:21`
  4. On DUT: verify `show ip bgp neighbor <T2> advertised-routes` DOES contain `10.222.99.0/24`
- **Steps (A true, B false)**:
  5. From T0/ExaBGP, announce `10.100.1.0/24` (IS a contributing prefix) without `65525:110` (no community, or any unrelated community such as `65000:100`)
  6. On DUT: verify `vtysh -c "show ip bgp 10.100.1.0/24"` does NOT display `65525:110`
  7. On T2: verify `10.100.1.0/24` IS received, with the announced community set preserved and no DUT-added `65525:21` / `65525:110`
  8. On DUT: verify `show ip bgp neighbor <T2> advertised-routes` DOES contain `10.100.1.0/24`

---

### Test Group 2: T1→T0 Downstream — Aggregate Leak Prevention

**Objective**: Validate that `TO_TIER0_V4/V6` seq 400 deny prevents the synthetic aggregate from being advertised downstream to T0. This is critical to avoid attracting traffic for prefixes that the T1 cannot actually reach beyond what its T0s already know.

#### Test Case 2.1: Aggregate not advertised to T0 (IPv4)
- **Config**: Aggregate `10.100.0.0/16` with prefix-lists
- **Steps**:
  1. Add aggregate, announce contributing routes from T0
  2. On T0: verify `10.100.0.0/16` is NOT received from DUT
  3. On T0: verify the contributing routes (which T0 itself originated) are unchanged
  4. On DUT: `show ip bgp neighbor <T0> advertised-routes` does NOT contain `10.100.0.0/16`

#### Test Case 2.2: Aggregate not advertised to T0 (IPv6)
- **Intent**: IPv6 dual of TC 2.1 — same assertions, symmetric coverage.
- **Config**: IPv6 aggregate `2001:db8:100::/48` with prefix-lists
- **Steps**:
  1. Add aggregate, announce contributing routes from T0
  2. On T0: verify `2001:db8:100::/48` is NOT received from DUT
  3. On T0: verify the contributing routes (which T0 itself originated) are unchanged
  4. On DUT: `show bgp ipv6 neighbor <T0> advertised-routes` does NOT contain `2001:db8:100::/48`

#### Test Case 2.3: Other DUT-originated routes are unaffected
- **Steps**:
  1. With aggregate in place, verify DUT continues to advertise default route / loopback / non-aggregate prefixes to T0 normally
  2. Verify no syslog errors regarding `TO_TIER0_V4` route-map evaluation

---

### Test Group 3: Lifecycle Operations with Community Verification

**Objective**: Validate that aggregate lifecycle operations correctly preserve / restore the tier-based tagging, verified on T2 / T0 neighbors. (Basic add / remove behavior is already covered by TG 1 — TC 1.1 for tagging, TC 1.5 for prefix-list dynamic add/remove; this group focuses on operations that go beyond a single CONFIG_DB write.)

#### Test Case 3.1: BGP container restart preserves tagging
- **Steps**:
  1. Add aggregate, verify tagging on T2
  2. `systemctl restart bgp` on DUT
  3. Wait for BGP sessions to re-establish
  4. On T2: verify aggregate received with `65525:21`
  5. On DUT: `show ip prefix-list AGGREGATE_ROUTES_V4` contains placeholder + dynamic entry

#### Test Case 3.2: Config reload preserves tagging
- **Steps**:
  1. Add aggregate, `config save -y`
  2. `config reload -y -f`
  3. After convergence, on T2: verify `65525:21` on aggregate
  4. On T0: verify aggregate still NOT received
  5. **Teardown**: after `rollback_or_reload`, re-issue `config save -y` so the on-disk `config_db.json` matches the rolled-back (clean) state — same pattern as [test_bgp_aggregate_address_resilience.py setup_teardown](../../tests/bgp/test_bgp_aggregate_address_resilience.py). Skipping this leaves the aggregate persisted on disk if a previous run failed between `config save -y` and per-test cleanup.

#### Test Case 3.3: Rapid add/remove churn does not corrupt prefix-list state
- **Intent**: Stress the `BGP_AGGREGATE_ADDRESS` → `AggregateAddressMgr` → FRR write path under back-to-back add/remove, and prove that the new tier-tagging prefix-lists (`AGGREGATE_ROUTES_V4`, `AGGREGATE_CONTRIBUTING_ROUTES_V4`) return to baseline with no orphans. Pacing constants follow the reference implementation in [tests/bgp/test_bgp_aggregate_address_scale_stress.py::test_7_3_rapid_add_remove_cycling](../../tests/bgp/test_bgp_aggregate_address_scale_stress.py) (lines 829–935). **Do not invent new throttle numbers.**
- **Reused helpers / constants** (all defined in [tests/bgp/bgp_aggregate_helpers.py](../../tests/bgp/bgp_aggregate_helpers.py)):
  - `BGP_SETTLE_WAIT = 5` — used once after the loop completes (NOT between iterations).
  - `verify_bgp_aggregate_cleanup(duthost, prefix)` — asserts the aggregate is fully removed from FRR running-config.
  - `wait_until` from `tests.common.utilities`.
  - `check_communities_on_neighbors` from the (extracted) `tests.common.helpers.bgp_routing` module — used **directly** as the convergence signal; no new wrappers needed.

  > **Do NOT copy** the stress-test's `_wait_for_dut_ready` / `_check_dut_health` — those are **bound instance methods on `TestRapidAddRemoveCycling`**, not free functions. Pulling them in either requires copy-pasting ~80 lines of code (DRY violation) or a prerequisite refactor PR that moves them to module scope (out of this plan's minimal-impact scope). Use the lighter post-checks listed in the Post-test verification block instead.
- **Iteration count**: **100** (`RAPID_CYCLE_ITERATIONS` in the stress test). If budget requires fewer iterations on a slow testbed, parametrize via a fixture rather than hard-coding a different number here.
- **Pacing pattern (per iteration — no `time.sleep` between iterations)**:

  ```python
  CYCLE_TIMEOUT = 30   # seconds, per-iteration wait_until budget
  CYCLE_INTERVAL = 2   # seconds, polling interval
  AGGR_V4 = "10.100.0.0/16"
  db_key = f"BGP_AGGREGATE_ADDRESS|{AGGR_V4}"
  db_add_cmd = (
      f"sonic-db-cli CONFIG_DB HSET '{db_key}' "
      f"'bbr-required' 'false' 'summary-only' 'false' 'as-set' 'false' "
      f"'aggregate-address-prefix-list' 'AGGREGATE_ROUTES_V4' "
      f"'contributing-address-prefix-list' 'AGGREGATE_CONTRIBUTING_ROUTES_V4'"
  )
  db_del_cmd = f"sonic-db-cli CONFIG_DB DEL '{db_key}'"

  for iteration in range(1, RAPID_CYCLE_ITERATIONS + 1):
      duthost.shell(db_add_cmd, module_ignore_errors=True)
      pytest_assert(
          wait_until(CYCLE_TIMEOUT, CYCLE_INTERVAL, 0,
                     check_communities_on_neighbors,
                     nbrhosts, t2_names, AGGR_V4,
                     {"65525:21"}, set()),
          f"Iteration {iteration}: aggregate not received on T2 with 65525:21",
      )
      duthost.shell(db_del_cmd, module_ignore_errors=True)
      pytest_assert(
          wait_until(CYCLE_TIMEOUT, CYCLE_INTERVAL, 0,
                     lambda: all(not get_route_communities(nbrhosts[n]["host"], AGGR_V4)
                                 for n in t2_names)),
          f"Iteration {iteration}: aggregate not withdrawn from T2",
      )
  ```

  Notes on the chosen approach:
  - **Direct CONFIG_DB writes** (`sonic-db-cli HSET` / `DEL`) — measured at ~0.02s vs. ~6s for GCU; the GCU overhead would dominate and mask the convergence behavior being tested.
  - **No `time.sleep` between iterations** — pacing is provided by `wait_until` on a real convergence condition (route appears/disappears on T2). A blind sleep would either be too long (mask the bug) or too short (flaky on slow VS).
  - **`check_communities_on_neighbors` / `get_route_communities` are reused directly** — no `_aggregate_present_on_t2` / `_aggregate_absent_on_t2` shim is introduced. Both helpers come from the extracted `tests.common.helpers.bgp_routing` module.
  - **One settling wait at the end only** — a single `time.sleep(BGP_SETTLE_WAIT)` after the final iteration before the post-checks, matching the stress-test pattern (lines 591 / 791 / 827).
- **Pre-test setup**:
  1. Confirm BGP sessions are Established via `duthost.check_bgp_session_state` (same probe used everywhere in `sonic-mgmt-int`).
  2. Announce contributing routes from T0 (reuse the inject pattern from TC 1.8) so each `add` iteration actually has something to tag on T2.
  3. Confirm starting state: `show ip prefix-list AGGREGATE_ROUTES_V4` returns ONLY the placeholder.
- **Post-test verification (after the loop + single `BGP_SETTLE_WAIT`)**:
  4. `verify_bgp_aggregate_cleanup(duthost, AGGR_V4)` — FRR has no leftover `aggregate-address` command.
  5. `show ip prefix-list AGGREGATE_ROUTES_V4` returns ONLY the placeholder `127.0.0.1/32` (no orphan dynamic entries).
  6. `show ip prefix-list AGGREGATE_CONTRIBUTING_ROUTES_V4` returns ONLY the placeholder.
  7. `redis-cli -n 4 KEYS 'BGP_AGGREGATE_ADDRESS|*'` returns empty.
  8. On T2: the aggregate prefix is fully withdrawn (no leftover from the last iteration).

---

## Out of Scope

- Performance / scale testing (covered by `test_bgp_aggregate_address_scale_stress.py`)
- MA / OOB community tagging (covered by [BGP-Aggregate-Address.md](BGP-Aggregate-Address.md))
- **Sentinel / BGPMon outbound aggregate tagging** (`TO_BGP_SENTINEL` / `TO_BGPMON_V6`) — these route-maps are fully validated at the FRR template unit-test layer by [`src/sonic-bgpcfgd/tests/test_templates.py::test_sentinel_policies` and `test_monitors_policies`](../../../Networking-acs-buildimage/src/sonic-bgpcfgd/tests/test_templates.py), which do byte-for-byte comparison of the rendered config against [`tests/data/sentinels/policies.conf/result_leaf.conf`](../../../Networking-acs-buildimage/src/sonic-bgpcfgd/tests/data/sentinels/policies.conf/result_leaf.conf) and [`tests/data/msft.monitors/policies.conf/result_leaf.conf`](../../../Networking-acs-buildimage/src/sonic-bgpcfgd/tests/data/msft.monitors/policies.conf/result_leaf.conf). Those fixtures pin every `match ip address prefix-list AGGREGATE_ROUTES_V{4,6}` + `set community 65525:21 additive` clause and pin the **absence** of any suppression `deny` clause — covering the same positive (V4/V6 tagging) and negative (no `65525:110`-based suppression toward Sentinel/BGPMon) assertions that an end-to-end runtime case would. The remaining runtime path (AggregateAddressMgr → FRR prefix-list refresh) is already exercised by TG 1 on the T2 peer, which shares the same `AGGREGATE_ROUTES_V4/V6` prefix-list. End-to-end runtime verification on a real testbed would require introducing new ExaBGP receivers + JSON dump parsing on ptfhost for ~0 incremental coverage above the byte-diff and is therefore deferred.
- Public-image (non-MSFT) FRR template behavior — the route-maps and community values in this plan target the `msft.general` template family **rendered only by `Networking-acs-buildimage` (the MSFT-internal fork of `sonic-buildimage`)**. Standard upstream-image testbeds (e.g. `sonic-vs` from the public `sonic-buildimage`) are explicitly out of scope and the suite MUST `pytest.skip(...)` on them.

## Cross-Reference

- FRR template source: `dockers/docker-fpm-frr/frr/bgpd/templates/msft.general/{v4,v6}.{leaf.spine,leaf.tor.all,tor}/policy.conf.j2`, `sentinels/policies.conf.j2`, `msft.monitors/policies.conf.j2`
- Runtime population: `src/sonic-bgpcfgd/bgpcfgd/managers_aggregate_address.py` (`AggregateAddressMgr`)
- Template-rendering unit tests: `src/sonic-bgpcfgd/tests/test_templates.py` + `tests/data/{msft.general,sentinels,msft.monitors}/policies.conf/`
- IPv6 next-hop policy regression: `src/sonic-bgpcfgd/tests/test_ipv6_nexthop_global.py` (the `DENY_ALL_ROUTE_MAPS` whitelist does not carve out `FROM_BGPMON_V6`)
- Sister test plan (MA / OOB upstream): [BGP-Aggregate-Address.md](BGP-Aggregate-Address.md)
