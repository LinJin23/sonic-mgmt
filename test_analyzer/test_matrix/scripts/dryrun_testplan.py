"""
Testplan Dry-Run: Compare actual test results against expected feature set.

Usage:
    python dryrun_testplan.py <BuildId>
    python dryrun_testplan.py 6a03eca4ea3a02a739d038c4

Logic:
  1. Query Kusto with the given BuildId to get actual test results
  2. Detect HWSKU and topology from results
  3. Look up the role in role_based_feature.yaml (e.g., Cisco T1 → t1_smart_ha_voq)
  4. Load all referenced YAML files to build expected case set
  5. Compare: flag cases that should run but were skipped
  6. Output a readable table with OK/X markers
"""
import sys
import yaml
from pathlib import Path
from collections import defaultdict
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder
from azure.kusto.data import ClientRequestProperties

# Ensure UTF-8 output for emoji rendering on Windows
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
YAML_DIR = ROOT_DIR / "yaml"
KUSTO_CLUSTER = "https://sonicrepodatadev.westus.kusto.windows.net"
KUSTO_DB = "SonicTestData"

# HWSKU → role mapping (keyed by topology prefix + hwsku)
# T1 roles
HWSKU_ROLE_MAP = {
    "Cisco-8102-C64": "t1_smart_ha_voq",
    "Cisco-8101-O32": "t1_smart_ha_voq",
    "Cisco-8101-O8C48": "t1_smart_ha_voq",
    "Cisco-8101-O8V48": "t1_smart_ha_voq",
    "Arista-7260CX3-C64": "t1_general",
    "Arista-7060CX-32S-C32": "t1_general",
    "Mellanox-SN2700": "t1_smart",
    "Mellanox-SN4600C-C64": "t1_smart",
    "Mellanox-SN4700-O32": "t1_smart",
}

# T0 overrides (topology-aware: if topology starts with "t0", use these)
T0_HWSKU_ROLE_MAP = {
    "Arista-7050CX3-32C-C32": "t0_general",
    "Arista-7050CX3-32S-C32": "t0_general",
    "Arista-7060CX-32S-C32": "t0_general",
    "Arista-7060CX-32S-D48C8": "t0_general",
    "Arista-7060CX-32S-Q32": "t0_general",
    "Arista-7260CX3-D108C8": "t0_general",
    "Arista-7260CX3-D108C10": "t0_general",
    "Mellanox-SN2700": "t0_smart",
    "Mellanox-SN2700-A1": "t0_smart",
    "Mellanox-SN4600C-C64": "t0_smart",
    "Mellanox-SN4700-O8V48": "t0_smart",
}

# Dualtor overrides (topology-aware: if topology contains "dualtor")
DUALTOR_HWSKU_ROLE_MAP = {
    "Arista-7050CX3-32C-C32": "dualtor_general",
    "Arista-7050CX3-32S-C32": "dualtor_general",
    "Arista-7260CX3-D108C8": "dualtor_general",
    "Arista-7260CX3-C64": "dualtor_general",
    "Cisco-8101C01-C32": "dualtor_smart_ha_voq",
    "Cisco-8101C01-V64": "dualtor_smart_ha_voq",
    "Mellanox-SN4700-V64": "dualtor_smart",
}

# File name mapping (role yaml references → actual file names)
FILE_MAP = {
    "t1_general.yaml": "t1_general_feature_set.yaml",
    "t1_smart.yaml": "t1_smart.yaml",
    "t1_dualtor_ha.yaml": "t1_dualtor_ha.yaml",
    "t1_dualtor_voq.yaml": "t1_dualtor_voq.yaml",
    "t0_t1_platform_mnlx.yaml": "t0_t1_platform_mnlx.yaml",
}


def query_kusto(build_id):
    """Query Kusto for test results of the given BuildId."""
    dut_regex = (
        r"(?:"
        r"bjw\d*-can-(?:t1-)?[\w]+-\d+"
        r"|str\d+-(?:7060(?:x6)?|7260cx3|8101c?1?|8102|msn[\w]+(?:-spy)?)-"
        r"(?:acs-|smartswitch-)?[\w-]*?\d+"
        r"|str-(?:a7060cx-acs-\d+|msn\d+-\d+)"
        r"|strtk\d+-[\w]+-\d+"
        r"|svcstr-[\w]+-acs-\d+"
        r")"
    )

    query = """
declare query_parameters(build_id:string);
let dut_regex = @"{dut_regex}";
TestReportUnionData
| where UploadTimestamp > ago(30d)
| where PipeStatus contains "finished"
| where BuildId contains build_id
| extend FullTestPathNorm = replace_regex(FullTestPath, dut_regex, "<DUT>")
| project FullCaseName, Feature, Result, Summary, HardwareSku, Topology, ModulePath, FullTestPathNorm
""".format(dut_regex=dut_regex)
    print(f"Querying Kusto for BuildId: {build_id}...")
    kcsb = KustoConnectionStringBuilder.with_az_cli_authentication(KUSTO_CLUSTER)
    client = KustoClient(kcsb)
    request_props = ClientRequestProperties()
    request_props.set_parameter("build_id", build_id)
    response = client.execute(KUSTO_DB, query, properties=request_props)

    rows = []
    for row in response.primary_results[0]:
        rows.append({
            "FullCaseName": row["FullCaseName"],
            "Feature": row["Feature"],
            "Result": row["Result"],
            "Summary": str(row["Summary"] or ""),
            "HardwareSku": row["HardwareSku"],
            "Topology": row["Topology"],
            "ModulePath": row["ModulePath"],
            "FullTestPathNorm": str(row["FullTestPathNorm"] or ""),
        })
    return rows


def load_expected_features(role_name):
    """Load all feature YAML files for the given role and build expected case set."""
    with open(YAML_DIR / "role_based_feature.yaml") as f:
        roles = yaml.safe_load(f)

    if role_name not in roles:
        print("ERROR: Role '{}' not found in role_based_feature.yaml".format(role_name))
        print(f"Available roles: {list(roles.keys())}")
        sys.exit(1)

    yaml_files = roles[role_name]
    print(f"  Role '{role_name}' includes: {yaml_files}")

    # Merge all features from all YAML files
    # expected[feature] = list of module entries (same format as the YAML)
    expected = {}

    for yaml_ref in yaml_files:
        actual_file = FILE_MAP.get(yaml_ref, yaml_ref)
        filepath = YAML_DIR / actual_file
        if not filepath.exists():
            print(f"  WARNING: {actual_file} not found, skipping")
            continue

        with open(filepath) as f:
            data = yaml.safe_load(f)

        # Extract features - handle different structures
        if "features" in data:
            features = data["features"]
        else:
            # Features are top-level keys (excluding 'metadata')
            features = {k: v for k, v in data.items() if k != "metadata"}

        # Also handle 'includes' in metadata (e.g., t1_general_feature_set.yaml includes platform_tests)
        if "metadata" in data and "includes" in (data["metadata"] or {}):
            for inc_file in data["metadata"]["includes"]:
                inc_path = YAML_DIR / inc_file
                if inc_path.exists():
                    with open(inc_path) as f:
                        inc_data = yaml.safe_load(f)
                    if "features" in inc_data:
                        inc_features = inc_data["features"]
                    else:
                        inc_features = {k: v for k, v in inc_data.items() if k != "metadata"}
                    for feat, entries in inc_features.items():
                        if feat in expected:
                            # Merge entries
                            if expected[feat] == "all" or entries == "all":
                                expected[feat] = "all"
                            else:
                                expected[feat] = expected[feat] + entries
                        else:
                            expected[feat] = entries

        for feat, entries in features.items():
            if feat in expected:
                if expected[feat] == "all" or entries == "all":
                    expected[feat] = "all"
                else:
                    expected[feat] = expected[feat] + entries
            else:
                expected[feat] = entries

    return expected


def expand_expected_to_prefixes(expected):
    """
    Convert expected feature entries to a set of module prefixes that should run.
    Returns: {feature: {"modules": [prefix_list], "skip_methods": {prefix: set(methods)}, "skip_on": {prefix: [rules]}}}
    """
    result = {}
    for feature, entries in expected.items():
        if entries == "all":
            result[feature] = {"all": True, "modules": [], "skip_methods": {}, "skip_on": {}}
            continue

        modules = []
        skip_methods = {}
        skip_on = {}
        for entry in entries:
            if isinstance(entry, str):
                modules.append(entry)
            elif isinstance(entry, dict) and "module" in entry:
                mp = entry["module"]
                modules.append(mp)
                if entry.get("skip"):
                    skip_methods[mp] = set(entry["skip"])
                if entry.get("skip_on"):
                    skip_on[mp] = entry["skip_on"]

        result[feature] = {"all": False, "modules": modules, "skip_methods": skip_methods, "skip_on": skip_on}
    return result


def is_expected_skip_on(case_name, feature_info, hwsku):
    """Check if a case is expected to skip on this specific HWSKU via skip_on rules.

    Returns (True, reason) if expected skip, (False, None) otherwise.
    """
    for module_prefix, rules in feature_info.get("skip_on", {}).items():
        # Check if case belongs to this module
        if not (case_name == module_prefix or case_name.startswith(module_prefix + ".")):
            continue
        suffix = case_name[len(module_prefix) + 1:]  # part after module.

        for rule in rules:
            rule_case = rule.get("case", "")
            # Match: suffix equals rule_case or starts with it
            if not (suffix == rule_case or suffix.startswith(rule_case + ".")):
                continue
            # Check hwsku match
            hwsku_list = rule.get("hwsku", [])
            vendor_list = rule.get("vendor", [])
            matched = False
            if hwsku in hwsku_list:
                matched = True
            for v in vendor_list:
                if hwsku.startswith(v):
                    matched = True
                    break
            if matched:
                return True, rule.get("reason", "expected skip on this HWSKU")
    return False, None


def case_matches_expected(case_name, feature_info):
    """Check if a case is expected to run given the feature info.

    When multiple YAML files are merged (e.g., t1_general skips egress but t1_smart adds it back),
    an explicit "run" entry always wins over a "skip" from a broader module.
    Logic: check all matching modules; if ANY says "run" (no skip), the case should run.
    """
    if feature_info["all"]:
        return True

    matched_any = False
    explicitly_run = False

    for module in feature_info["modules"]:
        # Match must be exact or at a dot boundary to avoid false prefix matches
        if case_name == module or case_name.startswith(module + "."):
            matched_any = True
            # Check if this specific case is in skip list
            skip_set = feature_info["skip_methods"].get(module, set())
            if not skip_set:
                # No skip list for this module — case is explicitly expected to run
                explicitly_run = True
                break
            else:
                is_skipped = False
                # Get suffix (part after module.)
                suffix = case_name[len(module) + 1:]  # e.g. "TestClass.test_method"

                # 1. Check if suffix matches or starts with any skip entry
                for skip_entry in skip_set:
                    if suffix == skip_entry or suffix.startswith(skip_entry + "."):
                        is_skipped = True
                        break

                # 2. Check individual segments against skip set (single-name entries)
                if not is_skipped:
                    parts = suffix.split(".")
                    for part in parts:
                        if part in skip_set:
                            is_skipped = True
                            break
                if not is_skipped:
                    explicitly_run = True
                    break
                # If skipped by this module, continue checking other modules
                # (a later file may have added it back explicitly)

    if explicitly_run:
        return True
    if matched_any:
        return False  # matched but all matches say skip
    return False


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    build_id = sys.argv[1]

    # Step 1: Query Kusto
    rows = query_kusto(build_id)
    if not rows:
        print("No results found for this BuildId.")
        sys.exit(1)
    print(f"  Got {len(rows)} test results")

    # Step 2: Detect HWSKU and topology
    hwskus = set(r["HardwareSku"] for r in rows)
    topos = set(r["Topology"] for r in rows)
    print(f"  HWSKU: {hwskus}")
    print(f"  Topology: {topos}")

    if len(hwskus) > 1:
        print("WARNING: Multiple HWSKUs in results, using first one")
    hwsku = next(iter(hwskus))

    # Determine topology type based on topology names
    is_dualtor = any("dualtor" in t for t in topos)
    is_t0 = any(t.startswith("t0") for t in topos) and not is_dualtor

    # Step 3: Look up role (topology-aware)
    if is_dualtor:
        role_map = DUALTOR_HWSKU_ROLE_MAP
        topo_label = "DUALTOR"
    elif is_t0:
        role_map = T0_HWSKU_ROLE_MAP
        topo_label = "T0"
    else:
        role_map = HWSKU_ROLE_MAP
        topo_label = "T1"
    if hwsku not in role_map:
        print(f"ERROR: HWSKU '{hwsku}' not in {topo_label}_HWSKU_ROLE_MAP")
        sys.exit(1)
    role = role_map[hwsku]
    print(f"  Role: {role}")

    # Step 4: Load expected features
    expected = load_expected_features(role)
    expected_info = expand_expected_to_prefixes(expected)
    print(f"  Expected features: {len(expected_info)}")

    # Step 5: Classify actual results
    # Group by feature → case → result
    # If ANY row for a case is "ran", it's "ran" (same case can have different params)
    actual = defaultdict(dict)  # {feature: {case_name: result}}
    case_reasons = defaultdict(lambda: defaultdict(list))  # {feature: {case_name: [(param, reason)]}}
    failed_on_setup = set()  # cases that failed on setup (don't report as untracked)
    for row in rows:
        feat = row["Feature"]
        case = row["FullCaseName"]
        result = row["Result"]
        summary = row["Summary"]
        full_path = row["FullTestPathNorm"]
        # Extract param from FullTestPathNorm (e.g., "test_foo[param_value]" → "param_value")
        param = ""
        if "[" in full_path and full_path.endswith("]"):
            param = full_path[full_path.rfind("["):]  # includes brackets like [rif_members-<DUT>]
        # Track "failed on setup" — these count as "ran" for unexpected-skip purposes
        # but should NOT appear in untracked cases list
        if "failed on setup" in summary.lower():
            failed_on_setup.add((feat, case))
            actual[feat][case] = "ran"
            continue
        # Collect reasons for skipped cases
        # "failed on setup" = attempted to run but errored → counts as "ran" not "skipped"
        if result == "skipped":
            if summary.strip():
                case_reasons[feat][case].append((param, summary.strip()))
            # Only set to skipped if not already marked as ran
            if actual[feat].get(case) != "ran":
                actual[feat][case] = "skipped"
        else:
            actual[feat][case] = "ran"

    # Step 6: Compare expected vs actual
    print(f"\n{'='*80}")
    print(f"  DRY-RUN REPORT: BuildId={build_id}")
    print(f"  HWSKU: {hwsku} | Role: {role}")
    print("  ℹ️  NOTE: multi_asic/multi_dut param cases are excluded from unexpected skips (single_asic testbed)")
    print(f"{'='*80}\n")

    # Track issues
    issues = []  # (feature, case, issue_type)
    skip_on_suppressed = []  # (feature, case, reason) — expected HWSKU-specific skips
    multi_asic_suppressed = []  # (feature, case) — suppressed due to multi_asic param
    untracked = []  # (feature, case, result) — cases not in any YAML
    feature_summary = {}  # {feature: {"expected": N, "ran": N, "skipped_bad": N}}

    for feature in sorted(expected_info.keys()):
        feat_info = expected_info[feature]
        feat_actual = actual.get(feature, {})

        expected_ran = 0
        actual_ran = 0
        unexpected_skip = []

        if feat_info["all"]:
            # All cases in this feature should run
            for case, result in feat_actual.items():
                expected_ran += 1
                if result == "ran":
                    actual_ran += 1
                else:
                    # Check skip_on before flagging
                    is_skip_on, skip_reason = is_expected_skip_on(case, feat_info, hwsku)
                    if is_skip_on:
                        skip_on_suppressed.append((feature, case, skip_reason))
                        actual_ran += 1  # count as OK
                    else:
                        unexpected_skip.append(case)
        else:
            # Check each actual case against expected
            for case, result in feat_actual.items():
                should_run = case_matches_expected(case, feat_info)
                if should_run:
                    expected_ran += 1
                    if result == "ran":
                        actual_ran += 1
                    else:
                        # Check skip_on before flagging
                        is_skip_on, skip_reason = is_expected_skip_on(case, feat_info, hwsku)
                        if is_skip_on:
                            skip_on_suppressed.append((feature, case, skip_reason))
                            actual_ran += 1  # count as OK
                        else:
                            unexpected_skip.append(case)
                else:
                    # Case not in YAML — only flag if it actually ran (skipped = normal)
                    # Also exclude "failed on setup" cases — they didn't really run successfully
                    if result == "ran" and (feature, case) not in failed_on_setup:
                        untracked.append((feature, case, result))

        # Filter out cases where ALL skip reasons are from multi_asic/multi_dut params
        filtered_skip = []
        for case in unexpected_skip:
            reasons = case_reasons.get(feature, {}).get(case, [])
            if reasons and all(
                "multi_asic" in param or "multi-asic" in param or "multi_dut" in param or "multi-dut" in param
                for param, _ in reasons
            ):
                multi_asic_suppressed.append((feature, case))
            else:
                filtered_skip.append(case)
        unexpected_skip = filtered_skip

        feature_summary[feature] = {
            "expected": expected_ran,
            "ran": actual_ran,
            "skipped_bad": len(unexpected_skip),
        }

        for case in unexpected_skip:
            issues.append((feature, case))

    # Detect untracked cases: ran but not in YAML, for features that ARE tracked
    # (If a feature isn't in YAML at all, it's intentionally excluded — don't report)
    # (If a case is skipped and not in YAML, that's normal — don't report)

    # Step 7: Output report
    # Feature summary table
    print("{:<35} {:>8} {:>6} {:>8} {}".format("Feature", "Expected", "Ran", "Skipped", "Status"))
    print("{:<35} {:>8} {:>6} {:>8} {}".format("-" * 35, "-" * 8, "-" * 6, "-" * 8, "-" * 8))

    for feature in sorted(feature_summary.keys()):
        s = feature_summary[feature]
        if s["expected"] == 0:
            status = "  --"  # Feature not in this testplan
        elif s["skipped_bad"] == 0:
            status = " ✅"
        elif s["skipped_bad"] == s["expected"]:
            status = " ❌ ALL SKIPPED"
        else:
            status = f" ❌ {s['skipped_bad']} skipped"

        if s["expected"] > 0:
            print(
                "  {:<33} {:>8} {:>6} {:>8} {}".format(
                    feature,
                    s["expected"],
                    s["ran"],
                    s["skipped_bad"],
                    status,
                )
            )

    # Detailed issues
    if issues:
        print(f"\n{'='*80}")
        print(f"  ❌ UNEXPECTED SKIPS ({len(issues)} cases should have run but were skipped)")
        if multi_asic_suppressed:
            print(
                f"  ℹ️  ({len(multi_asic_suppressed)} multi_asic/multi_dut param cases excluded "
                "— single_asic testbed only)"
            )
        print(f"{'='*80}")
        current_feat = None
        for feature, case in sorted(issues):
            if feature != current_feat:
                if feature == "qos":
                    print(
                        f"\n  [{feature}]  ⚠️  multi_asic/multi_dut param cases hidden "
                        "(not applicable to single_asic testbed)"
                    )
                else:
                    print(f"\n  [{feature}]")
                current_feat = feature
            # Show param + reason pairs for this case
            reasons = case_reasons.get(feature, {}).get(case, [])
            # Filter out multi_asic params from display
            display_reasons = [
                (p, r) for p, r in reasons
                if "multi_asic" not in p and "multi-asic" not in p
                and "multi_dut" not in p and "multi-dut" not in p
            ]
            if not display_reasons:
                display_reasons = reasons  # fallback: show all if nothing left
            skip_count = len(display_reasons) if display_reasons else 1
            print(f"    ❌ [{skip_count}] {case}")
            if display_reasons:
                # Check if all reasons are the same
                unique_reasons = set(r for _, r in display_reasons)
                if len(unique_reasons) == 1:
                    # All same reason — just print it once, no params
                    print(f"        reason: {unique_reasons.pop()}")
                else:
                    # Multiple different reasons — show param + reason pairs
                    seen = set()
                    for param, reason in display_reasons:
                        key = (param, reason)
                        if key not in seen:
                            seen.add(key)
                            if param:
                                print(f"        param: {param}")
                            print(f"        reason: {reason}")
    else:
        print("\n  ✅ ALL EXPECTED CASES RAN SUCCESSFULLY!")

    # Untracked cases (ran but not in YAML — only for features already tracked)
    if untracked:
        print(f"\n{'='*80}")
        print(f"  ⚠️  UNTRACKED CASES ({len(untracked)} ran but not in YAML — may need to add)")
        print(f"{'='*80}")
        current_feat = None
        for feature, case, result in sorted(untracked):
            if feature != current_feat:
                current_feat = feature
                print(f"\n  [{feature}]")
            print(f"    ⚠️  {case}")

    # Summary
    total_expected = sum(s["expected"] for s in feature_summary.values())
    total_ran = sum(s["ran"] for s in feature_summary.values())
    total_bad = sum(s["skipped_bad"] for s in feature_summary.values())
    print(f"\n{'='*80}")
    print(f"  SUMMARY: {total_ran}/{total_expected} expected cases ran | {total_bad} unexpected skips")
    if multi_asic_suppressed:
        print(
            f"  ℹ️  MULTI_ASIC/MULTI_DUT EXCLUDED: {len(multi_asic_suppressed)} cases "
            "(single_asic testbed, not applicable)"
        )
    if untracked:
        print(f"  ⚠️  UNTRACKED: {len(untracked)} cases ran but not in YAML — consider adding")
    if skip_on_suppressed:
        print(f"  ℹ️  EXPECTED HWSKU-SPECIFIC SKIPS: {len(skip_on_suppressed)} cases (suppressed from alert)")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
