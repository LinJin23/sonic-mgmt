"""
Query Kusto for T0 test data and generate T0 YAML feature set files.
"""
import json
import yaml
from pathlib import Path
from collections import defaultdict
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder


class IndentedDumper(yaml.Dumper):
    """Custom YAML dumper that indents list items under mapping keys."""
    pass


def _increase_indent(self, flow=False, indentless=False):
    return super(IndentedDumper, self).increase_indent(flow, False)


IndentedDumper.increase_indent = _increase_indent


def yaml_dump(data, f):
    """Dump YAML with proper 2-space indentation for list items."""
    yaml.dump(data, f, Dumper=IndentedDumper, default_flow_style=False,
              sort_keys=False, allow_unicode=True)


SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
DATA_DIR = ROOT_DIR / "data"
YAML_DIR = ROOT_DIR / "yaml"

KUSTO_CLUSTER = "https://sonicrepodatadev.westus.kusto.windows.net"
KUSTO_DB = "SonicTestData"

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


def query_kusto():
    query = """
let lookback = 30d;
let branch = "202511";
let dut_regex = @"{dut_regex}";
let base = TestReportUnionData
| where TestBranch == "internal-202511"
| where PipeStatus contains "finish"
| where UploadTimestamp > ago(lookback)
| where Topology startswith "t0" and Topology !contains "isolate"
| where OSVersion contains branch
| extend FullTestPathNorm = replace_regex(FullTestPath, dut_regex, "<DUT>");
let ran = base
| where Result != "skipped" and Summary !contains "failed on setup"
| distinct FullTestPathNorm, HardwareSku, Feature, FullCaseName;
let skip_only = base
| where Result == "skipped"
| distinct FullTestPathNorm, HardwareSku, Feature, FullCaseName
| join kind=leftanti ran on FullTestPathNorm, HardwareSku, FullCaseName
| extend Status = "skip_only";
let all_status = ran
| extend Status = "ran"
| union skip_only;
all_status
| distinct HardwareSku, Feature, FullCaseName, Status
| summarize
    Feature = take_any(Feature),
    Arista_7050 = take_anyif(
        Status,
        HardwareSku in ("Arista-7050CX3-32C-C32", "Arista-7050CX3-32S-C32")
    ),
    Arista_7060 = take_anyif(
        Status,
        HardwareSku in (
            "Arista-7060CX-32S-C32",
            "Arista-7060CX-32S-D48C8",
            "Arista-7060CX-32S-Q32"
        )
    ),
    Arista_7260 = take_anyif(
        Status,
        HardwareSku in ("Arista-7260CX3-D108C8", "Arista-7260CX3-D108C10")
    ),
    MLX_2700 = take_anyif(
        Status,
        HardwareSku in ("Mellanox-SN2700", "Mellanox-SN2700-A1")
    ),
    MLX_4600 = take_anyif(Status, HardwareSku == "Mellanox-SN4600C-C64"),
    MLX_4700 = take_anyif(Status, HardwareSku == "Mellanox-SN4700-O8V48")
    by FullCaseName
""".format(dut_regex=dut_regex)
    print("Querying Kusto for T0 data...")
    kcsb = KustoConnectionStringBuilder.with_az_cli_authentication(KUSTO_CLUSTER)
    client = KustoClient(kcsb)
    response = client.execute(KUSTO_DB, query)

    rows = []
    for row in response.primary_results[0]:
        rows.append({
            "FullCaseName": row["FullCaseName"],
            "Feature": row["Feature"],
            "Arista_7050": row["Arista_7050"] or "",
            "Arista_7060": row["Arista_7060"] or "",
            "Arista_7260": row["Arista_7260"] or "",
            "MLX_2700": row["MLX_2700"] or "",
            "MLX_4600": row["MLX_4600"] or "",
            "MLX_4700": row["MLX_4700"] or "",
        })
    return rows


# Features to skip (maintained manually)
MANUAL_FEATURES = {"acl", "acms", "clock", "everflow", "fib", "iface_namingmode"}

# Features not supported on ANY T0 platform (n/a on both Arista and MLX) — exclude entirely
EXCLUDED_FEATURES = {"bfd"}

# Features generated into separate YAML files (included via metadata.includes)
SEPARATE_FEATURES = {"platform_tests"}


def get_module_path(case_name):
    """Extract the best module path from FullCaseName.

    Strategy: use 3 segments if 3rd segment is a TestClass (starts with uppercase 'Test'),
    otherwise use 2 segments (feature.test_file level).

    Examples:
      'acl.test_acl.TestBasicAcl.test_x' → 'acl.test_acl.TestBasicAcl'
      'arp.test_arpall.test_something' → 'arp.test_arpall'
      'bgp.test_bgp_fact' → 'bgp.test_bgp_fact'
    """
    parts = case_name.split(".")
    if len(parts) >= 3 and parts[2][0:4] == "Test" and parts[2][0].isupper():
        return ".".join(parts[:3])
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return case_name


def get_method_suffix(case_name, module_path):
    """Get the part after module_path."""
    if case_name.startswith(module_path + "."):
        return case_name[len(module_path) + 1:]
    return case_name


def collapse_skip_by_class(skip_methods, ran_methods):
    """If ALL methods of a TestClass are in skip (none ran), collapse to just TestClass name.

    E.g., skip has test_module.TestModuleApi.test_a, test_module.TestModuleApi.test_b, ...
    and ran has NO test_module.TestModuleApi.* → collapse to 'test_module.TestModuleApi'
    """
    # Group skip methods by their TestClass prefix (first 2 parts: file.TestClass)
    from collections import defaultdict as dd
    class_skip = dd(set)
    no_class = []

    for method in skip_methods:
        parts = method.split(".")
        if len(parts) >= 2 and parts[0][0:4] == "test" and len(parts[1]) > 0 and parts[1][0].isupper():
            # Has TestClass prefix like test_module.TestModuleApi.test_xxx
            class_prefix = f"{parts[0]}.{parts[1]}"
            class_skip[class_prefix].add(method)
        else:
            no_class.append(method)

    # Check if any ran method belongs to same class
    class_ran = dd(set)
    for method in ran_methods:
        parts = method.split(".")
        if len(parts) >= 2 and parts[0][0:4] == "test" and len(parts[1]) > 0 and parts[1][0].isupper():
            class_prefix = f"{parts[0]}.{parts[1]}"
            class_ran[class_prefix].add(method)

    result = list(no_class)
    for class_prefix, methods in class_skip.items():
        if class_prefix not in class_ran:
            # ALL methods of this class are skipped → collapse to class name
            result.append(class_prefix)
        else:
            # Some ran, some skipped — keep individual methods
            result.extend(methods)

    return result


def get_platform_tests_module_path(case_name):
    """For platform_tests, module path is at file level (include subfolder).

    Examples:
      'platform_tests.api.test_chassis.TestChassisApi.test_fans' → 'platform_tests.api.test_chassis'
      'platform_tests.test_sequential_restart.test_restart_syncd' → 'platform_tests.test_sequential_restart'
      'platform_tests.daemon.test_psud.test_something' → 'platform_tests.daemon.test_psud'
    """
    parts = case_name.split(".")
    # Find the test file segment (starts with 'test_')
    for i in range(1, len(parts)):
        if parts[i].startswith("test_"):
            return ".".join(parts[:i+1])
    # Fallback: 2 segments
    return ".".join(parts[:2])


def get_platform_tests_method(case_name, module_path):
    """Get just the method name (last segment) from the case name."""
    suffix = case_name[len(module_path)+1:] if case_name.startswith(module_path + ".") else case_name
    # suffix might be "TestClass.method" or just "method"
    # Return just the method name (last part)
    parts = suffix.split(".")
    return parts[-1] if parts else suffix


def generate_platform_tests_yaml(ran_cases, skip_cases):
    """Generate platform_tests YAML with file-level modules and short skip entries."""
    ran_by_module = defaultdict(set)
    skip_by_module = defaultdict(set)

    for case in ran_cases:
        mp = get_platform_tests_module_path(case)
        method = get_platform_tests_method(case, mp)
        ran_by_module[mp].add(method)

    for case in skip_cases:
        mp = get_platform_tests_module_path(case)
        method = get_platform_tests_method(case, mp)
        skip_by_module[mp].add(method)

    all_modules = sorted(set(list(ran_by_module.keys()) + list(skip_by_module.keys())))

    entries = []
    for module in all_modules:
        ran_methods = ran_by_module.get(module, set())
        skip_methods = skip_by_module.get(module, set())

        if not ran_methods:
            # All methods skip-only — don't include
            continue

        if not skip_methods:
            # All ran — just module path
            entries.append(module)
        else:
            # Mixed — module + skip (short method names)
            entries.append({
                "module": module,
                "skip": sorted(skip_methods)
            })

    return entries


def generate_yaml_for_feature(feature, ran_cases, skip_cases):
    """Generate YAML entries for a feature.

    Rules:
    - If a module has only 1 case (ran or skip), just use module path
    - If all cases in a module ran → just list module path
    - If mixed → module + skip format
    - Keep each line as short as possible
    - Avoid redundancy: if file-level module covers all, don't list TestClass children
    """
    # Group cases by module path
    ran_by_module = defaultdict(set)
    skip_by_module = defaultdict(set)

    for case in ran_cases:
        mp = get_module_path(case)
        suffix = get_method_suffix(case, mp)
        ran_by_module[mp].add(suffix)

    for case in skip_cases:
        mp = get_module_path(case)
        suffix = get_method_suffix(case, mp)
        skip_by_module[mp].add(suffix)

    # Merge: if a file-level module (2 segments) has all ran AND no TestClass children exist,
    # it means the file itself is the only module — safe to represent as just the file path.
    # But if TestClass children DO exist, we must keep them (they have their own skip patterns).
    all_modules = sorted(set(list(ran_by_module.keys()) + list(skip_by_module.keys())))

    # Find file-level modules that have all ran (no skips)
    file_level_all_ran = set()
    for module in all_modules:
        parts = module.split(".")
        if len(parts) == 2:  # file-level
            if module in ran_by_module and module not in skip_by_module:
                # Only mark as "all ran" if NO TestClass children exist for this file
                has_children = any(
                    m.startswith(module + ".") for m in all_modules if m != module
                )
                if not has_children:
                    file_level_all_ran.add(module)

    # Filter out TestClass modules that are children of a file-level all-ran module
    filtered_modules = []
    for module in all_modules:
        parts = module.split(".")
        if len(parts) >= 3:
            parent = ".".join(parts[:2])
            if parent in file_level_all_ran:
                # Parent already covers this, skip
                continue
        filtered_modules.append(module)

    # Count how many modules share the same file-level path
    file_level_count = defaultdict(int)
    for module in filtered_modules:
        parts = module.split(".")
        file_path = ".".join(parts[:2]) if len(parts) >= 2 else module
        file_level_count[file_path] += 1

    entries = []
    for module in filtered_modules:
        ran_methods = ran_by_module.get(module, set())
        skip_methods = skip_by_module.get(module, set())

        if not ran_methods:
            # All methods in this module are skip-only — don't include
            continue

        # If only 1 total case in this module, use shortest path
        total = len(ran_methods) + len(skip_methods)
        if total == 1:
            parts = module.split(".")
            file_path = ".".join(parts[:2]) if len(parts) >= 2 else module
            # Only collapse to file-level if this is the only module at that level
            if file_level_count[file_path] == 1:
                entries.append(file_path)
            else:
                entries.append(module)
            continue

        if not skip_methods:
            # All methods ran — just list the module
            entries.append(module)
        else:
            # Some ran, some skipped — use module+skip format
            # Collapse: if ALL methods of a TestClass are skipped, use just TestClass name
            collapsed_skips = collapse_skip_by_class(skip_methods, ran_methods)
            entries.append({
                "module": module,
                "skip": sorted(collapsed_skips)
            })

    return entries


def is_arista_na(feat, case):
    """Check if a case is Arista n/a (same rules as Kusto query)."""
    return (
        feat.lower() in ("vxlan", "vnet", "bfd")
        or (feat.lower() == "qos" and "voq" in case.lower())
        or "test_vnet_bgp_route_precedence" in case
        or "test_nvgre_hash" in case
        or (feat.lower() == "acl" and "egress" in case.lower())
        or (feat.lower() == "everflow" and "egress" in case.lower())
    )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate T0 YAML feature set files")
    parser.add_argument("--platform-tests-only", action="store_true",
                        help="Only regenerate t0_platform_tests.yaml, don't touch general")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    YAML_DIR.mkdir(exist_ok=True)

    rows = query_kusto()
    print(f"Got {len(rows)} unique cases")

    # Save raw data
    with open(DATA_DIR / "t0_all_status.json", "w") as f:
        json.dump(rows, f, indent=2)
    print("Saved raw data to data/t0_all_status.json")

    # Classify cases per feature
    features_ran = defaultdict(set)
    features_skip = defaultdict(set)

    for r in rows:
        feat = r["Feature"]
        case = r["FullCaseName"]
        # For general file: only count cases that Arista can run (not Arista n/a)
        # Arista-n/a cases go into smart only
        if is_arista_na(feat, case):
            continue
        statuses = [r["Arista_7050"], r["Arista_7060"], r["Arista_7260"],
                    r["MLX_2700"], r["MLX_4600"], r["MLX_4700"]]
        if "ran" in statuses:
            features_ran[feat].add(case)
        elif "skip_only" in statuses:
            features_skip[feat].add(case)

    print(f"\nFeatures: {len(features_ran)} with ran cases")
    total_ran = sum(len(v) for v in features_ran.values())
    total_skip = sum(len(v) for v in features_skip.values())
    print(f"Total: {total_ran} ran cases, {total_skip} skip-only cases")

    # ── Generate t0_platform_tests.yaml ──
    # Exclude platform_tests.mellanox.* — those are in t0_t1_platform_mnlx.yaml
    if "platform_tests" in features_ran:
        pt_ran = {c for c in features_ran["platform_tests"] if "platform_tests.mellanox" not in c}
        pt_skip = {c for c in features_skip.get("platform_tests", set()) if "platform_tests.mellanox" not in c}
        pt_entries = generate_platform_tests_yaml(pt_ran, pt_skip)
        pt_output = {
            "metadata": {
                "description": "platform_tests expected cases (T0, 202511)",
                "feature": "platform_tests",
                "logic": "ran = any HWSKU ran it; skip = all HWSKUs skipped it",
                "branch": "202511",
            },
            "platform_tests": pt_entries
        }
        pt_path = YAML_DIR / "t0_platform_tests.yaml"
        with open(pt_path, "w") as f:
            yaml_dump(pt_output, f)
        print(f"\nGenerated: {pt_path}")
        print(f"  Modules: {len(pt_entries)}, Ran: {len(pt_ran)}, Skip: {len(pt_skip)}")

    if args.platform_tests_only:
        print("\n  --platform-tests-only: skipping general feature set generation")
        return

    # Generate T0 general feature set YAML (cases ran by ANY hwsku)
    # Skip manually-maintained features (preserve them from existing file)
    all_features = {}
    for feat in sorted(features_ran.keys()):
        if feat in MANUAL_FEATURES or feat in EXCLUDED_FEATURES or feat in SEPARATE_FEATURES:
            continue
        ran_cases = features_ran[feat]
        skip_cases = features_skip.get(feat, set())
        if not skip_cases:
            # No skips at all → use "all"
            all_features[feat] = "all"
        else:
            entries = generate_yaml_for_feature(feat, ran_cases, skip_cases)
            if entries:
                all_features[feat] = entries

    # Read existing YAML to preserve manual features
    out_path = YAML_DIR / "t0_general_feature_set.yaml"
    existing_manual = {}
    if out_path.exists():
        with open(out_path) as f:
            existing = yaml.safe_load(f) or {}
        # Handle 'features:' wrapper
        if "features" in existing:
            existing = existing["features"] or {}
        for feat in MANUAL_FEATURES:
            if feat in existing:
                existing_manual[feat] = existing[feat]

    # Build output: metadata + features wrapper
    features_dict = {}
    # Add manual features first (preserved as-is)
    for feat in sorted(existing_manual.keys()):
        features_dict[feat] = existing_manual[feat]
    # Add generated features
    features_dict.update(all_features)

    output = {
        "metadata": {
            "description": "General T0 - cases ran by ANY T0 HWSKU (202511, 30-day window)",
            "branch": "202511",
            "test_branch": "internal-202511",
            "topology": "t0",
            "includes": ["t0_platform_tests.yaml"],
        },
        "features": features_dict,
    }

    with open(out_path, "w") as f:
        yaml_dump(output, f)
    print(f"\nGenerated: {out_path}")
    print(f"  Features: {len(all_features)} generated + {len(existing_manual)} manual")
    print(f"  Ran cases: {total_ran}")
    print(f"  Skip cases: {total_skip}")

    # Print summary
    print(f"\n{'='*60}")
    print("  T0 Feature Summary")
    print(f"{'='*60}")
    print("{:<35} {:>6} {:>6}".format("Feature", "Ran", "Skip"))
    print("{:<35} {:>6} {:>6}".format("-" * 35, "-" * 6, "-" * 6))
    for feat in sorted(features_ran.keys()):
        r = len(features_ran[feat])
        s = len(features_skip.get(feat, set()))
        print("  {:<33} {:>6} {:>6}".format(feat, r, s))

    # t0_smart.yaml is manually maintained — do not regenerate
    # generate_t0_smart(rows)


def generate_t0_smart(rows):
    """Generate t0_smart.yaml — cases that MLX runs but Arista doesn't support."""
    # Collect cases where: Arista n/a AND MLX ran
    smart_ran = defaultdict(set)   # feat -> set of case names
    smart_skip = defaultdict(set)  # feat -> set of case names (MLX all-skipped)

    for r in rows:
        feat = r["Feature"]
        case = r["FullCaseName"]
        if not is_arista_na(feat, case):
            continue
        # Skip platform_tests.mellanox — in t0_t1_platform_mnlx.yaml
        if "platform_tests.mellanox" in case:
            continue
        # Skip everflow — manually maintained in smart yaml
        if feat == "everflow":
            continue
        # bfd not supported on ANY T0 platform (no Cisco on T0)
        if feat.lower() == "bfd":
            continue
        mlx_statuses = [r["MLX_2700"], r["MLX_4600"], r["MLX_4700"]]
        if "ran" in mlx_statuses:
            smart_ran[feat].add(case)
        elif "skip_only" in mlx_statuses:
            smart_skip[feat].add(case)

    # Generate entries per feature using same format as general
    smart_features = {}
    for feat in sorted(smart_ran.keys()):
        ran_cases = smart_ran[feat]
        skip_cases = smart_skip.get(feat, set())
        if not skip_cases:
            smart_features[feat] = "all"
        else:
            entries = generate_yaml_for_feature(feat, ran_cases, skip_cases)
            if entries:
                smart_features[feat] = entries

    total_ran = sum(len(v) for v in smart_ran.values())
    total_skip = sum(len(v) for v in smart_skip.values())

    smart_output = {
        "metadata": {
            "description": "Smart T0 - MLX-supported features not supported by Arista",
            "branch": "202511",
            "test_branch": "internal-202511",
            "topology": "t0",
            "rules": "vxlan, vnet, bfd, acl-egress, everflow-egress, nvgre_hash",
            "vendor_applicability": "mellanox",
        },
        "features": smart_features,
    }

    smart_path = YAML_DIR / "t0_smart.yaml"
    with open(smart_path, "w") as f:
        yaml_dump(smart_output, f)
    print(f"\nGenerated: {smart_path}")
    print(f"  Features: {len(smart_features)}, Ran: {total_ran}, Skip: {total_skip}")


if __name__ == "__main__":
    main()
