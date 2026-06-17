# Role-Based Feature-Test Matrix — Implementation Design

**SONiC Qualification Team**

| Field | Value |
|-------|-------|
| Authors | Ying Xie, Storm Liang, Zhaohui Sun |
| Branch | 202511 |
| ADO | [#37549391](https://msazure.visualstudio.com/One/_workitems/edit/37549391) |
| Status | Implementation Complete (Phase 1–2: T0/T1/DualToR) |

---

## 1. Problem Statement

The SONiC orchagent crash on Cisco-8101 dualtor (202505) exposed a systemic gap: there is no authoritative mapping of which tests must run on which platform. Without this, hundreds of test skips silently accumulated across releases with no gate to block release progression.

Today, skip exceptions are embedded in scattered pytest markers and `conditional_mark` YAML — no single document or configuration says *"feature X is required on HWSKU Y."*

**Goal:** Create a single source-of-truth YAML configuration that defines exactly which test cases should run on each HWSKU, and a validation tool that compares nightly results against this definition to detect coverage gaps.

---

## 2. Current Landscape (202511, 30-day window)

**Scale:** 99 features × 29 HWSKUs × 22 topologies × 1,596 unique test cases

| Topology Group | Vendors | HWSKUs | Key HWSKUs |
|---------------|---------|--------|------------|
| T0 | Arista, Mellanox | 8 | 7060CX-32S, SN2700, SN4600C, 7050CX3-32S |
| T1 | Cisco, Arista, Mellanox | 9 | 8102-C64, 7060CX-32S, SN4700-O32 |
| DualToR | Cisco, Arista, Mellanox | 4 | Cisco-8101C01, 7050CX3-32S, 7260CX3, SN4700 |

> **Note:** T0, T1, and DualToR are all implemented. T2 topology is planned for a future phase.

**Known Platform Exceptions (T1):**

| Feature / Scope | Cisco | Arista | Mellanox |
|----------------|-------|--------|----------|
| vxlan, vnet | ✅ | ❌ n/a | ✅ |
| qos.voq (VOQ watchdog) | ✅ | ❌ n/a | ❌ n/a |
| bfd | ✅ | ❌ n/a | ❌ n/a |
| acl (egress) | ✅ | ❌ n/a | ✅ |
| everflow (egress) | ✅ | ❌ n/a | ✅ |
| platform_tests.mellanox | ❌ n/a | ❌ n/a | ✅ |
| nvgre_hash | ✅ | ❌ n/a | ✅ |

---

## 3. Implementation: Role-Based Feature Set Architecture

### 3.1 Core Concept: Roles and Composable YAML Files

Instead of a monolithic per-HWSKU matrix, we use a **role-based composition** model. Each HWSKU is assigned a **role**, and each role loads a set of YAML files that together define the expected test coverage. This architecture covers **T0, T1, and DualToR** topologies.

```
┌─────────────────────────────────────────────────────────────────────┐
│                      role_based_feature.yaml                         │
│                                                                     │
│  ── T1 Topology ──                                                  │
│  t1_smart_ha_voq:  (Cisco)                                          │
│    - t1_general_feature_set.yaml                                     │
│    - t1_smart.yaml                                                   │
│    - t1_dualtor_ha.yaml                                              │
│    - t1_dualtor_voq.yaml                                             │
│                                                                     │
│  t1_smart:  (Mellanox)                                               │
│    - t1_general_feature_set.yaml                                     │
│    - t1_smart.yaml                                                   │
│    - t0_t1_dualtor_platform_mnlx.yaml                                │
│                                                                     │
│  t1_general:  (Arista)                                               │
│    - t1_general_feature_set.yaml                                     │
│                                                                     │
│  ── T0 Topology ──                                                  │
│  t0_smart:  (Mellanox)                                               │
│    - t0_general_feature_set.yaml                                     │
│    - t0_smart.yaml                                                   │
│    - t0_t1_dualtor_platform_mnlx.yaml                                │
│                                                                     │
│  t0_general:  (Arista)                                               │
│    - t0_general_feature_set.yaml                                     │
│                                                                     │
│  ── DualToR Topology ──                                             │
│  dualtor_smart_ha_voq:  (Cisco)                                      │
│    - dualtor_general_feature_set.yaml                                │
│    - dualtor_smart.yaml                                              │
│    - t1_dualtor_ha.yaml                                              │
│    - t1_dualtor_voq.yaml                                             │
│                                                                     │
│  dualtor_smart:  (Mellanox)                                          │
│    - dualtor_general_feature_set.yaml                                │
│    - dualtor_smart.yaml                                              │
│    - t0_t1_dualtor_platform_mnlx.yaml                                │
│                                                                     │
│  dualtor_general:  (Arista)                                          │
│    - dualtor_general_feature_set.yaml                                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Role Assignment Rules:** The dryrun script determines a HWSKU's role based on vendor and topology:

**T1:**
- **Cisco** → `t1_smart_ha_voq` (general + smart + HA + VOQ features)
- **Mellanox** → `t1_smart` (general + smart + Mellanox platform tests)
- **Arista** → `t1_general` (general features only)

**T0:**
- **Mellanox** → `t0_smart` (general + smart + Mellanox platform tests)
- **Arista** → `t0_general` (general features only)

**DualToR:**
- **Cisco** → `dualtor_smart_ha_voq` (general + smart + HA + VOQ)
- **Mellanox** → `dualtor_smart` (general + smart + Mellanox platform)
- **Arista** → `dualtor_general` (general features only)

### 3.2 Role Definition File

**`role_based_feature.yaml`** — the entry point that maps roles to their constituent YAML files:

```yaml
# T1 roles
t1_smart_ha_voq:
    - t1_general_feature_set.yaml
    - t1_smart.yaml
    - t1_dualtor_ha.yaml
    - t1_dualtor_voq.yaml

t1_smart:
    - t1_general_feature_set.yaml
    - t1_smart.yaml
    - t0_t1_dualtor_platform_mnlx.yaml

t1_general:
    - t1_general_feature_set.yaml

# T0 roles
t0_smart:
    - t0_general_feature_set.yaml
    - t0_smart.yaml
    - t0_t1_dualtor_platform_mnlx.yaml

t0_general:
    - t0_general_feature_set.yaml

# DualToR roles
dualtor_smart_ha_voq:
    - dualtor_general_feature_set.yaml
    - dualtor_smart.yaml
    - t1_dualtor_ha.yaml
    - t1_dualtor_voq.yaml

dualtor_smart:
    - dualtor_general_feature_set.yaml
    - dualtor_smart.yaml
    - t0_t1_dualtor_platform_mnlx.yaml

dualtor_general:
    - dualtor_general_feature_set.yaml
```

> **Shared files:** `t1_dualtor_ha.yaml`, `t1_dualtor_voq.yaml`, and `t0_t1_dualtor_platform_mnlx.yaml` are shared across topologies. The Mellanox platform tests file is used by T0, T1, and DualToR Mellanox roles alike.

### 3.3 Feature Set YAML Files

Each feature set YAML file defines features and their expected test modules/cases. Three entry types are supported:

| Entry Type | Meaning | Example |
|-----------|---------|---------|
| `feature: all` | ALL modules in this feature are expected to run | `acms: all` |
| Plain string | A specific module or class expected to run entirely | `- bgp.test_bgp_fact` |
| Module with skip | A module expected to run, EXCEPT certain classes/methods | `- module: X`<br>`  skip:`<br>`    - TestClassY` |

**`t1_general_feature_set.yaml`** — the foundation, cases expected on ALL 9 HWSKUs (63 features, ~842 expected cases):

```yaml
metadata:
  description: General T1 - cases ran by ALL 9 HWSKUs (smart cases excluded)
  branch: '202511'
  test_branch: internal-202511
  count: 657
  includes:
  - t1_platform_tests.yaml
  - t1_generic_config_updater.yaml
  - t1_qos.yaml
features:
  acl:
    - module: acl.test_acl.TestAclWithPortToggle
      skip:
        - test_egress_unmatched_forwarded
    - module: acl.test_acl.TestAclWithReboot
      skip:
        - test_egress_unmatched_forwarded
    - module: acl.test_acl.TestBasicAcl
      skip:
        - test_egress_unmatched_forwarded
    - module: acl.test_acl.TestIncrementalAcl
      skip:
        - test_egress_unmatched_forwarded
    - acl.test_stress_acl.test_acl_add_del_stress
  acms: all
  arp:
    - arp.test_arpall
    - arp.test_neighbor_mac
    - arp.test_neighbor_mac_noptf
  bgp:
    - bgp.test_bgp_allow_list
    - bgp.test_bgp_bbr
    - bgp.test_bgp_fact
    - bgp.test_bgp_session
    # ... (41 total BGP modules)
  everflow:
    - module: everflow.test_everflow_ipv6
      skip:
        - TestEgressEverflowIPv6
    - everflow.test_everflow_per_interface
    - module: everflow.test_everflow_testbed
      skip:
        - TestEverflowV4EgressAclEgressMirror
        - TestEverflowV4EgressAclIngressMirror
        - TestEverflowV4IngressAclEgressMirror
        - TestEverflowV4IngressAclIngressMirror.test_everflow_frwd_with_bkg_trf
        - TestEverflowV4IngressAclIngressMirror.test_everflow_fwd_recircle_port_queue_check
        - TestEverflowV4IngressAclIngressMirror.test_everflow_multi_binding_acl
  # ... 63 features total
```

> **Key Design:** Egress ACL/everflow cases are skipped in `t1_general` because Arista doesn't support them. They are added back via `t1_smart.yaml` for Cisco and Mellanox.

**`t1_smart.yaml`** — platform-specific features that Cisco and Mellanox run but Arista does not:

```yaml
metadata:
  description: Smart T1 - platform-specific features per design table
  branch: '202511'

features:
  acl:
    - acl.test_acl.TestAclWithPortToggle.test_egress_unmatched_forwarded
    - acl.test_acl.TestAclWithReboot.test_egress_unmatched_forwarded
    - acl.test_acl.TestBasicAcl.test_egress_unmatched_forwarded
    - acl.test_acl.TestIncrementalAcl.test_egress_unmatched_forwarded
  everflow:
    - everflow.test_everflow_ipv6.TestEgressEverflowIPv6
    - everflow.test_everflow_testbed.TestEverflowV4EgressAclEgressMirror
    # ...
  fib:
    - fib.test_fib.test_nvgre_hash
  vxlan:
    - vxlan.test_vnet_bgp_route_precedence.Test_VNET_BGP_route_Precedence
    - vxlan.test_vnet_decap.test_vnet_decap
    # ... 13 vxlan modules total
```

**`t1_dualtor_ha.yaml`** — Cisco-only HA/BFD features (shared by T1 and DualToR Cisco roles):

```yaml
metadata:
  description: HA features - BFD (Cisco only, shared across T1 and DualToR)

features:
  bfd:
    - bfd.test_bfd
```

**`t1_dualtor_voq.yaml`** — Cisco-only VOQ features (shared by T1 and DualToR Cisco roles):

```yaml
metadata:
  description: VOQ features - QoS VOQ watchdog (Cisco only, shared across T1 and DualToR)

features:
  qos:
    - qos.test_oq_watchdog
    - qos.test_voq_watchdog
```

**`t0_t1_dualtor_platform_mnlx.yaml`** — Mellanox-only platform tests (shared across all topologies):

```yaml
metadata:
  description: Mellanox platform tests (shared by T0, T1, and DualToR Mellanox roles)

features:
  platform_tests:
    - platform_tests.mellanox.check_sysfs
    - platform_tests.mellanox.test_thermal_control
    # ... Mellanox-specific platform tests
```

### 3.4 HWSKU-Specific Expected Skips (`skip_on`)

Some test cases legitimately skip on certain HWSKUs but run on others — this is **expected behavior**, not a gap. For example, `testPfcStormWithSharedHeadroomOccupancy` requires shared headroom pool support which only Mellanox provides.

The `skip_on` construct marks these cases so the dryrun tool does not flag them as unexpected skips:

```yaml
qos:
  - module: qos.test_qos_sai
    skip:
      - TestQosSai.testIPIPQosSaiDscpToPgMapping    # skip on ALL HWSKUs
    skip_on:
      - case: TestQosSai.testPfcStormWithSharedHeadroomOccupancy
        vendor: [Cisco, Arista]
        reason: Shared headroom not supported on non-Mellanox platforms
      - case: TestQosSai.testSomeOtherCase
        hwsku: [Cisco-8102-C64]
        reason: Known limitation on 8102
```

**Syntax:**

| Field | Type | Description |
|-------|------|-------------|
| `case` | string | Method/class suffix relative to the module (same format as `skip` entries) |
| `vendor` | list | Vendor prefixes to match (e.g., `Cisco` matches all `Cisco-*` HWSKUs) |
| `hwsku` | list | Exact HWSKU names to match |
| `reason` | string | (Optional) Explanation of why this skip is expected |

**Rules:**
- `skip` = always expected to skip on **ALL** HWSKUs (global skip)
- `skip_on` = expected to skip only on **specific** HWSKUs/vendors
- Both `vendor` and `hwsku` can be used together in one rule (OR logic)
- Cases matching `skip_on` for the current HWSKU are counted as OK (not flagged)
- If the case actually runs (e.g., platform got fixed), no alert is raised either

**Dryrun output:**
```
  SUMMARY: 831/910 expected cases ran | 79 unexpected skips
  ℹ️  EXPECTED HWSKU-SPECIFIC SKIPS: 1 cases (suppressed from alert)
```

### 3.5 Merge Logic: "Run Wins"

When multiple YAML files are loaded for a role, the merge rule is **"any match says run → run wins"**:

1. If `t1_general` skips `test_egress_unmatched_forwarded` (because Arista can't run it)
2. But `t1_smart` explicitly lists `acl.test_acl.TestBasicAcl.test_egress_unmatched_forwarded`
3. Then for Cisco/Mellanox (who load both files), the case is **expected to run**

This allows the general file to define conservative common coverage, while supplementary files add back platform-specific capabilities.

### 3.6 Expected Case Count by Role

**T1 Topology:**

| HWSKU | Role | Expected Cases | Composition |
|-------|------|---------------|-------------|
| Arista-7060CX-32S-C32 | t1_general | 842 | general only |
| Arista-7260CX3-C64 | t1_general | 842 | general only |
| Cisco-8102-C64 | t1_smart_ha_voq | 913 | general + smart + ha + voq |
| Cisco-8101-O32 | t1_smart_ha_voq | 910 | general + smart + ha + voq |
| Cisco-8101-O8C48 | t1_smart_ha_voq | 913 | general + smart + ha + voq |
| Cisco-8101-O8V48 | t1_smart_ha_voq | 910 | general + smart + ha + voq |
| Mellanox-SN2700 | t1_smart | 924 | general + smart + mlx_platform |
| Mellanox-SN4700-O32 | t1_smart | 926 | general + smart + mlx_platform |
| Mellanox-SN4600C-C64 | t1_smart | 924 | general + smart + mlx_platform |

**T0 Topology:**

| HWSKU | Role | Features | Composition |
|-------|------|----------|-------------|
| Arista-* | t0_general | 82 | general only |
| Mellanox-* | t0_smart | 82+ | general + smart + mlx_platform |

**DualToR Topology:**

| HWSKU | Role | Features | Composition |
|-------|------|----------|-------------|
| Arista-7050CX3-32C/S | dualtor_general | 78 | general only |
| Arista-7260CX3 | dualtor_general | 78 | general only |
| Cisco-8101C01 | dualtor_smart_ha_voq | 78+ | general + smart + ha + voq |
| Mellanox-SN4700-V64 | dualtor_smart | 78+ | general + smart + mlx_platform |

---

## 4. Dry-Run Validation Tool

### 4.1 Purpose

The **dryrun tool** (`dryrun_testplan.py`) compares the expected feature set against actual nightly test results from Kusto. It answers: *"Did every test we expected to run actually run? If not, why was it skipped?"*

### 4.2 How It Works

```
┌────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Kusto    │────▶│  dryrun_testplan  │◀────│  role_based_     │
│  (BuildId) │     │      .py         │     │  feature.yaml   │
└────────────┘     └────────┬─────────┘     └─────────────────┘
                            │
                   ┌────────▼─────────┐
                   │  Comparison Report│
                   │  - Per-feature    │
                   │  - Skip summaries │
                   └──────────────────┘
```

**Steps:**
1. Query Kusto with a BuildId → get all test results (FullCaseName, Feature, Result, Summary)
2. Detect HWSKU from results → determine role → load YAML files
3. Expand YAML entries into expected case set (resolving `all`, module prefixes, skip lists)
4. Classify actual results: if ANY row for a case is "ran", it's counted as ran
5. Compare: expected-to-run cases that were actually skipped → "unexpected skips"
6. Output per-feature summary table + detailed skip list with Summary reasons

### 4.3 Example Output

Running against Cisco-8102-C64 (BuildId `6a0d15b46db2e3b21cb662aa`):

```
================================================================================
  DRY-RUN REPORT: BuildId=6a0d15b46db2e3b21cb662aa
  HWSKU: Cisco-8102-C64 | Role: t1_smart_ha_voq
================================================================================
Feature                             Expected    Ran  Skipped Status
----------------------------------- -------- ------ -------- --------
  acl                                    101    101        0  ✅
  acms                                     9      9        0  ✅
  bgp                                    41     41        0  ✅
  drop_packets                            15     10        5  ❌ 5 skipped
  everflow                                32     27        5  ❌ 5 skipped
  platform_tests                         228    186       42  ❌ 42 skipped
  qos                                     37     24       13  ❌ 13 skipped
  ...

================================================================================
  ❌ UNEXPECTED SKIPS (79 cases should have run but were skipped)
================================================================================

  [drop_packets]
    ❌ drop_packets.test_drop_counters.test_dst_ip_absent
        reason: Test case not supported on Broadcom DNX platform and Cisco 8000 platform and M0/Mx topos
    ❌ drop_packets.test_drop_counters.test_ip_is_zero_addr
        reason: M0/Mx topos doesn't support drop packets / Cisco 8000 platform does not drop packets with 0.0.0.0 source or destination IP address
    ❌ drop_packets.test_drop_counters.test_no_egress_drop_on_down_link
        param: [port_channel_members-<DUT>]
        reason: RIF interface is absent
        param: [vlan_members-<DUT>]
        reason: Test case is only suitable for t0 type topology since it requires vlan interfaces
        param: [rif_members-<DUT>]
        reason: No rif_members available

  [generic_config_updater]
    ❌ generic_config_updater.test_pfcwd_interval.test_pfcwd_interval_config_updates
        reason: This test can only support mellanox platforms.

  [platform_tests]
    ❌ platform_tests.test_reboot.TestReboot.test_cold_reboot
        reason: cold reboot is disabled on the DUT
    ...

================================================================================
  SUMMARY: 831/910 expected cases ran | 79 unexpected skips
  ℹ️  EXPECTED HWSKU-SPECIFIC SKIPS: 1 cases (suppressed from alert)
================================================================================
```

**Output key points:**
- **Single reason**: When all params of a case share the same skip reason, only the reason is shown once (no param lines)
- **Multiple reasons**: When different params have different reasons, each `param:` + `reason:` pair is listed
- **`skip_on` suppression**: Cases matching a `skip_on` rule for the current HWSKU are counted as OK and summarized at the end

### 4.4 Batch Dryrun

`batch_dryrun.py` automates running the dryrun for all HWSKUs in a topology:

```bash
python batch_dryrun.py --t1       # All 9 T1 HWSKUs
python batch_dryrun.py --t0       # All T0 HWSKUs
python batch_dryrun.py --dualtor  # All DualToR HWSKUs
```

1. Queries Kusto for the most recent BuildId per HWSKU (>1500 total cases for T1, >500 for T0/DualToR)
2. Runs `dryrun_testplan.py` for each BuildId
3. Saves output to `log/dryrun_<hwsku>.log`

**Latest Batch Results (2026-05-22):**

| HWSKU | Expected | Ran | Unexpected Skips | Run Rate |
|-------|----------|-----|------------------|----------|
| Cisco-8102-C64 | 910 | 831 | 79 | 91.3% |
| Cisco-8102-C64 | 910 | 831 | 79 | 91.3% |
| Cisco-8101-O32 | 910 | 840 | 70 | 92.3% |
| Cisco-8101-O8C48 | 913 | 831 | 82 | 91.0% |
| Cisco-8101-O8V48 | 877 | 804 | 73 | 91.7% |
| Arista-7060CX-32S-C32 | 842 | 764 | 78 | 90.7% |
| Arista-7260CX3-C64 | 842 | 764 | 78 | 90.7% |
| Mellanox-SN2700 | 924 | 792 | 132 | 85.7% |
| Mellanox-SN4700-O32 | 926 | 778 | 148 | 84.0% |
| Mellanox-SN4600C-C64 | 924 | 780 | 144 | 84.4% |

### 4.5 Interpreting Skip Summaries

The dryrun extracts the skip `reason` (from the Kusto `Summary` field) for each unexpected skip. This helps triage whether a skip is:

| Category | Action | Example |
|----------|--------|---------|
| Platform limitation | Add to skip list in YAML | "Not supported on Broadcom platforms" |
| Topology mismatch | Add to skip list | "Only support t1-lag topology" |
| Infra/testbed issue | Investigate & fix testbed | "Cannot get baud rate", "No LAGs found" |
| Genuine test bug | File bug, keep as expected | "Test performs config reload causing pmon start-limit-hit" |
| Conditional skip | Evaluate if should be permanent | "SRv6 not supported on older ASICs" |

---

## 5. File Structure

```
test_matrix/
├── yaml/                                  # YAML definitions
│   ├── role_based_feature.yaml            # Entry point: role → YAML file mapping (9 roles)
│   │
│   │── ── T1 ──
│   ├── t1_general_feature_set.yaml        # General T1 (all 9 HWSKUs)
│   │   ├── includes: t1_platform_tests.yaml
│   │   ├── includes: t1_qos.yaml
│   │   ├── includes: t1_generic_config_updater.yaml
│   │   └── includes: t1_drop_packets.yaml
│   ├── t1_smart.yaml                      # Smart features (Cisco + Mellanox, manually maintained)
│   ├── t1_dualtor_ha.yaml                 # HA/BFD (Cisco only, shared T1+DualToR)
│   ├── t1_dualtor_voq.yaml               # VOQ (Cisco only, shared T1+DualToR)
│   ├── t1_platform_tests.yaml            # Platform tests (general subset, included by t1_general)
│   ├── t1_qos.yaml                       # QoS (general subset, with skip_on)
│   ├── t1_generic_config_updater.yaml    # GCU (general subset)
│   ├── t1_drop_packets.yaml              # Drop packets (general subset)
│   │
│   │── ── T0 ──
│   ├── t0_general_feature_set.yaml        # General T0 (82 features)
│   │   └── includes: t0_platform_tests.yaml
│   ├── t0_platform_tests.yaml            # Platform tests (T0 subset)
│   ├── t0_smart.yaml                      # Smart features T0 (manually maintained)
│   │
│   │── ── DualToR ──
│   ├── dualtor_general_feature_set.yaml   # General DualToR (78 features)
│   │   └── includes: dualtor_platform_tests.yaml
│   ├── dualtor_platform_tests.yaml       # Platform tests (DualToR subset)
│   ├── dualtor_smart.yaml                 # Smart features DualToR (manually maintained)
│   │
│   │── ── Shared ──
│   └── t0_t1_dualtor_platform_mnlx.yaml  # Mellanox platform tests (shared all topologies)
│
├── scripts/                               # Tools
│   ├── dryrun_testplan.py                # Validation tool (all topologies)
│   ├── batch_dryrun.py                   # Batch validation (--t0/--t1/--dualtor)
│   ├── gen_t0_feature_set.py             # Generator: T0 YAML from Kusto (--platform-tests-only)
│   ├── gen_t1_feature_set.py             # Generator: T1 YAML from Kusto
│   └── gen_dualtor_feature_set.py        # Generator: DualToR YAML from Kusto
├── log/                                   # Dryrun output logs
│   ├── dryrun_cisco_8102_c64.log
│   ├── dryrun_arista_7060cx_32s_c32.log
│   └── ...
└── FeatureTestMatrix.md                  # This document
```

**Maintenance model:**
- **Generated files** (via gen scripts): `*_general_feature_set.yaml`, `*_platform_tests.yaml`
- **Manually maintained** (smart/overlay): `t1_smart.yaml`, `t0_smart.yaml`, `dualtor_smart.yaml`, `t1_dualtor_ha.yaml`, `t1_dualtor_voq.yaml`, `t0_t1_dualtor_platform_mnlx.yaml`
- **MANUAL_FEATURES** in gen scripts: `acl`, `cacl`, `everflow`, `fib`, `iface_namingmode` — preserved from existing YAML, never overwritten by generators

---

## 6. How to Use

### 6.1 Run a Single HWSKU Validation

```bash
python dryrun_testplan.py <BuildId>
```

The script auto-detects HWSKU from the BuildId's Kusto data and selects the appropriate role.

### 6.2 Run All HWSKUs

```bash
python batch_dryrun.py --t1        # T1 topology (9 HWSKUs)
python batch_dryrun.py --t0        # T0 topology
python batch_dryrun.py --dualtor   # DualToR topology
```

Queries Kusto for the latest BuildId per HWSKU and runs validation for all.

### 6.3 Add a New Expected Case

1. Determine which YAML file the case belongs to (general vs. smart vs. platform-specific)
2. Add the module or case entry under the appropriate feature
3. If some methods in a module should be skipped, use the `module:` + `skip:` format
4. Re-run `dryrun_testplan.py` to verify the change

### 6.4 Add a New HWSKU

1. Add the HWSKU to the vendor detection logic in `dryrun_testplan.py`
2. The role will be assigned based on vendor (Cisco → t1_smart_ha_voq, etc.)
3. Run batch dryrun to validate

### 6.5 Mark a Case as Expected Skip on Specific HWSKUs

When a case legitimately skips on some HWSKUs but runs on others:

1. Identify the module entry in the appropriate YAML file
2. Add a `skip_on` block with the case name and either `vendor` or `hwsku` list:
   ```yaml
   - module: qos.test_qos_sai
     skip_on:
       - case: TestQosSai.testPfcStormWithSharedHeadroomOccupancy
         vendor: [Cisco, Arista]
         reason: Shared headroom not supported
   ```
3. Re-run dryrun to verify the case is suppressed from alerts on those HWSKUs

### 6.6 Regenerate Feature Set YAMLs from Kusto

Generator scripts query Kusto (90-day window) and rebuild `*_general_feature_set.yaml` and `*_platform_tests.yaml`:

```bash
# T0: regenerate both general + platform_tests
python gen_t0_feature_set.py

# T0: regenerate platform_tests only (skip general)
python gen_t0_feature_set.py --platform-tests-only

# T1: regenerate general + platform_tests
python gen_t1_feature_set.py

# DualToR: regenerate general + platform_tests
python gen_dualtor_feature_set.py
```

**Important:** Gen scripts respect `MANUAL_FEATURES` — features in this set are preserved from existing YAML and never overwritten. Smart/overlay YAML files are **never** touched by gen scripts.

---

## 7. Next Steps (Roadmap)

| Phase | Deliverable | Status |
|-------|------------|--------|
| Phase 1: Feature Set Definition | YAML files defining expected coverage for T1 HWSKUs | ✅ Complete |
| Phase 1b: T0 & DualToR Extension | Extend role-based architecture to T0 and DualToR topologies | ✅ Complete |
| Phase 2: Dryrun Validation | Compare nightly results against definition; identify gaps | ✅ Complete |
| Phase 3: Gap Reduction | Triage unexpected skips; update YAML or fix tests | 🔄 In Progress |
| Phase 4: Dashboard | Kusto-based dashboard showing coverage trends over time | Planned |
| Phase 5: Pipeline Integration | Post-nightly auto-validation + alerting on new gaps | Planned |
| Phase 6: Qualification Gate | Block release promotion when coverage below threshold | Planned |

**Phase 3 Target:** Reduce unexpected skips from current ~80-150 per HWSKU down to <20 (legitimate infra/testbed issues only).

---

## 8. Design Principles

1. **Single Source of Truth** — `role_based_feature.yaml` is the authoritative definition of what should run where
2. **Composable** — Roles compose multiple YAML files; changes to general affect all HWSKUs automatically
3. **Conservative General** — The general file only includes cases that ALL HWSKUs in a topology can run; platform-specific cases go in supplements
4. **Run Wins** — When composing files, if any file says "run this case", it's expected to run (skips are overridable)
5. **Data-Driven** — Feature sets are generated from actual Kusto data (90-day window), not guesswork
6. **Transparent Skips** — Every skip in the YAML has context (what egress means, why VOQ is Cisco-only); dryrun shows Summary reasons for runtime skips
7. **Generated + Manual** — General/platform_tests YAMLs are auto-generated; smart/overlay YAMLs are hand-maintained for nuanced platform-specific logic
8. **Shared Files** — HA, VOQ, and Mellanox platform files are shared across topologies to avoid duplication
