"""
Query Kusto for dualtor test data and generate dualtor YAML feature set files.

HWSKUs:
  Arista_7050: Arista-7050CX3-32C-C32, Arista-7050CX3-32S-C32
  Arista_7260: Arista-7260CX3-D108C8, Arista-7260CX3-C64
  Cisco_8101:  Cisco-8101C01-C32, Cisco-8101C01-V64
  MLX_4700:    Mellanox-SN4700-V64

Generates:
  - dualtor_general_feature_set.yaml (cases all vendors can run)
  - dualtor_platform_tests.yaml (included by general)
  - dualtor_smart.yaml (cases only MLX/Cisco run, Arista n/a)
"""
import sys
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


# Arista-NA rules (same as T0 — these features/cases don't run on Arista)
def is_arista_na(feat, case):
    """Check if a case is Arista n/a."""
    return (
        feat.lower() in ("vxlan", "vnet", "bfd")
        or (feat.lower() == "qos" and "voq" in case.lower())
        or "test_vnet_bgp_route_precedence" in case
        or "test_nvgre_hash" in case
        or (feat.lower() == "acl" and "egress" in case.lower())
        or (feat.lower() == "everflow" and "egress" in case.lower())
    )


# Features to skip (maintained manually)
MANUAL_FEATURES = {"acl", "cacl", "everflow", "fib", "iface_namingmode"}

# Features not supported on ANY dualtor platform — exclude entirely
EXCLUDED_FEATURES = set()

# Features generated into separate YAML files
SEPARATE_FEATURES = {"platform_tests"}


def query_kusto():
    query = """
let lookback = 90d;
let branch = "202511";
let dut_regex = @"{dut_regex}";
let base = TestReportUnionData
| where TestBranch == "internal-202511"
| where PipeStatus contains "finish"
| where BuildId != "69d1fa60eb4653619e057c43"
| where UploadTimestamp > ago(lookback)
| where Topology contains "dualtor"
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
    Arista_7260 = take_anyif(
        Status,
        HardwareSku in ("Arista-7260CX3-D108C8", "Arista-7260CX3-C64")
    ),
    Cisco_8101 = take_anyif(
        Status,
        HardwareSku in ("Cisco-8101C01-C32", "Cisco-8101C01-V64")
    ),
    MLX_4700 = take_anyif(Status, HardwareSku == "Mellanox-SN4700-V64")
    by FullCaseName
""".format(dut_regex=dut_regex)
    print("Querying Kusto for dualtor data...")
    kcsb = KustoConnectionStringBuilder.with_az_cli_authentication(KUSTO_CLUSTER)
    client = KustoClient(kcsb)
    response = client.execute(KUSTO_DB, query)

    rows = []
    for row in response.primary_results[0]:
        rows.append({
            "FullCaseName": row["FullCaseName"],
            "Feature": row["Feature"],
            "Arista_7050": row["Arista_7050"] or "",
            "Arista_7260": row["Arista_7260"] or "",
            "Cisco_8101": row["Cisco_8101"] or "",
            "MLX_4700": row["MLX_4700"] or "",
        })
    return rows


sys.path.insert(0, str(SCRIPTS_DIR))
from gen_t0_feature_set import (  # noqa: E402
    generate_platform_tests_yaml, generate_yaml_for_feature,
)


def main():
    DATA_DIR.mkdir(exist_ok=True)
    YAML_DIR.mkdir(exist_ok=True)

    rows = query_kusto()
    print(f"Got {len(rows)} unique cases")

    # Save raw data
    with open(DATA_DIR / "dualtor_all_status.json", "w") as f:
        json.dump(rows, f, indent=2)
    print("Saved raw data to data/dualtor_all_status.json")

    # ── General: cases that Arista can run (not Arista-NA) ──
    features_ran = defaultdict(set)
    features_skip = defaultdict(set)

    for r in rows:
        feat = r["Feature"]
        case = r["FullCaseName"]
        if is_arista_na(feat, case):
            continue
        statuses = [r["Arista_7050"], r["Arista_7260"], r["Cisco_8101"], r["MLX_4700"]]
        if "ran" in statuses:
            features_ran[feat].add(case)
        elif "skip_only" in statuses:
            features_skip[feat].add(case)

    print(f"\nGeneral features: {len(features_ran)} with ran cases")
    total_ran = sum(len(v) for v in features_ran.values())
    total_skip = sum(len(v) for v in features_skip.values())
    print(f"Total: {total_ran} ran cases, {total_skip} skip-only cases")

    # Generate general feature entries
    all_features = {}
    for feat in sorted(features_ran.keys()):
        if feat in MANUAL_FEATURES or feat in EXCLUDED_FEATURES or feat in SEPARATE_FEATURES:
            continue
        ran_cases = features_ran[feat]
        skip_cases = features_skip.get(feat, set())
        if not skip_cases:
            all_features[feat] = "all"
        else:
            entries = generate_yaml_for_feature(feat, ran_cases, skip_cases)
            if entries:
                all_features[feat] = entries

    # Read existing YAML to preserve manual features
    out_path = YAML_DIR / "dualtor_general_feature_set.yaml"
    existing_manual = {}
    if out_path.exists():
        with open(out_path) as f:
            existing = yaml.safe_load(f) or {}
        if "features" in existing:
            existing = existing["features"] or {}
        for feat in MANUAL_FEATURES:
            if feat in existing:
                existing_manual[feat] = existing[feat]

    # Build output
    features_dict = {}
    for feat in sorted(existing_manual.keys()):
        features_dict[feat] = existing_manual[feat]
    features_dict.update(all_features)

    output = {
        "metadata": {
            "description": "General dualtor - cases ran by ANY dualtor HWSKU (202511, 30-day window)",
            "branch": "202511",
            "test_branch": "internal-202511",
            "topology": "dualtor",
            "includes": ["dualtor_platform_tests.yaml"],
        },
        "features": features_dict,
    }

    with open(out_path, "w") as f:
        yaml_dump(output, f)
    print(f"\nGenerated: {out_path}")
    print(f"  Features: {len(all_features)} generated + {len(existing_manual)} manual")

    # Print summary
    print(f"\n{'='*60}")
    print("  Dualtor Feature Summary")
    print(f"{'='*60}")
    print("{:<35} {:>6} {:>6}".format("Feature", "Ran", "Skip"))
    print("{:<35} {:>6} {:>6}".format("-" * 35, "-" * 6, "-" * 6))
    for feat in sorted(features_ran.keys()):
        r = len(features_ran[feat])
        s = len(features_skip.get(feat, set()))
        print("  {:<33} {:>6} {:>6}".format(feat, r, s))

    # ── Generate dualtor_platform_tests.yaml ──
    if "platform_tests" in features_ran:
        pt_ran = {c for c in features_ran["platform_tests"] if "platform_tests.mellanox" not in c}
        pt_skip = {c for c in features_skip.get("platform_tests", set()) if "platform_tests.mellanox" not in c}
        pt_entries = generate_platform_tests_yaml(pt_ran, pt_skip)
        pt_output = {
            "metadata": {
                "description": "platform_tests expected cases (dualtor, 202511)",
                "feature": "platform_tests",
                "logic": "ran = any HWSKU ran it; skip = all HWSKUs skipped it",
                "branch": "202511",
            },
            "platform_tests": pt_entries
        }
        pt_path = YAML_DIR / "dualtor_platform_tests.yaml"
        with open(pt_path, "w") as f:
            yaml_dump(pt_output, f)
        print(f"\nGenerated: {pt_path}")
        print(f"  Modules: {len(pt_entries)}, Ran: {len(pt_ran)}, Skip: {len(pt_skip)}")

    # ── Smart YAML files are manually maintained — do not regenerate ──
    # dualtor_smart.yaml, t0_smart.yaml, t1_smart.yaml are all manual


if __name__ == "__main__":
    main()
