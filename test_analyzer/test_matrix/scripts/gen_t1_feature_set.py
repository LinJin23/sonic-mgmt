"""
Generate per-feature expected case YAML from ran_cases + skip_only_cases files.

Usage:
    python gen_feature_set.py <feature_name>
    python gen_feature_set.py platform_tests
    python gen_feature_set.py qos

Logic:
  - A case is "expected ran" if ANY of the 9 HWSKUs ran it
  - A case goes into "skip" only if ALL 9 HWSKUs skipped it (none ran it)
  - Output uses compressed module format: module path alone if all methods ran,
    or {module: X, skip: [...]} if some methods are universally skipped

Output file: t1_{feature_name}.yaml
"""
import sys
import yaml
from pathlib import Path
from collections import defaultdict

SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
DATA_DIR = ROOT_DIR / "data"

HWSKU_FILES = {
    "Arista-7060CX-32S-C32": (
        "arista_7060cx-32s-c32_t1_202511_ran_cases.yaml",
        "arista_7060cx-32s-c32_t1_202511_skip_only_cases.yaml",
    ),
    "Arista-7260CX3-C64": (
        "arista_7260cx3-c64_t1_202511_ran_cases.yaml",
        "arista_7260cx3-c64_t1_202511_skip_only_cases.yaml",
    ),
    "Cisco-8101-O32": (
        "cisco_8101-o32_t1_202511_ran_cases.yaml",
        "cisco_8101-o32_t1_202511_skip_only_cases.yaml",
    ),
    "Cisco-8101-O8C48": (
        "cisco_8101-o8c48_t1_202511_ran_cases.yaml",
        "cisco_8101-o8c48_t1_202511_skip_only_cases.yaml",
    ),
    "Cisco-8101-O8V48": (
        "cisco_8101-o8v48_t1_202511_ran_cases.yaml",
        "cisco_8101-o8v48_t1_202511_skip_only_cases.yaml",
    ),
    "Cisco-8102-C64": (
        "cisco_8102-c64_t1_202511_ran_cases.yaml",
        "cisco_8102-c64_t1_202511_skip_only_cases.yaml",
    ),
    "Mellanox-SN2700": (
        "mellanox_sn2700_t1_202511_ran_cases.yaml",
        "mellanox_sn2700_t1_202511_skip_only_cases.yaml",
    ),
    "Mellanox-SN4600C-C64": (
        "mellanox_sn4600c-c64_t1_202511_ran_cases.yaml",
        "mellanox_sn4600c-c64_t1_202511_skip_only_cases.yaml",
    ),
    "Mellanox-SN4700-O32": (
        "mellanox_sn4700-o32_t1_202511_ran_cases.yaml",
        "mellanox_sn4700-o32_t1_202511_skip_only_cases.yaml",
    ),
}


def load_feature(filepath, feature):
    """Load cases for a feature from a YAML file."""
    with open(filepath) as f:
        data = yaml.safe_load(f)
    return set(data.get("features", {}).get(feature, []))


def get_script_path(case, feature):
    """
    Extract the script-level path from a full case name.
    Convention: feature.test_script_name is the script path (first 2 segments).
    E.g. iface_namingmode.test_iface_namingmode.TestShowVlan.test_x → iface_namingmode.test_iface_namingmode

    For nested features like platform_tests.api.test_chassis, use 3 segments.
    Heuristic: segments that start with 'test_' are script files.
    """
    parts = case.split(".")
    # Find the script file: the last segment starting with 'test_' before class/method
    script_idx = 0
    for i, p in enumerate(parts):
        if p.startswith("test_") and i > 0:
            script_idx = i
            break
    if script_idx == 0:
        # Fallback: use first 2 segments
        script_idx = min(1, len(parts) - 1)
    return ".".join(parts[:script_idx + 1])


def compress_to_modules(ran_cases, skip_cases, feature):
    """
    Compress case lists into module format using script-level grouping.
    - Group by script path (e.g. feature.test_script_name)
    - If no skips for a script → plain script path entry
    - If some cases are skipped → {module: script_path, skip: [...]}
    - Skip entries use the shortest unique suffix (class level if all methods
      in that class are skipped, otherwise full path)
    """
    # Group ran and skip by script path
    scripts = defaultdict(lambda: {"ran": set(), "skip": set()})

    for case in ran_cases:
        sp = get_script_path(case, feature)
        scripts[sp]["ran"].add(case)

    for case in skip_cases:
        sp = get_script_path(case, feature)
        scripts[sp]["skip"].add(case)

    # Build compressed entries
    entries = []
    for sp in sorted(scripts.keys()):
        info = scripts[sp]
        if not info["ran"]:
            continue  # All-skip script — don't list it at all
        elif not info["skip"]:
            # No skips — just use the script path
            entries.append(sp)
        else:
            # Has both ran and skips — try to compress skip list to class level
            skip_list = compress_skip_list(info["skip"], info["ran"], sp)
            entries.append({"module": sp, "skip": skip_list})

    return entries


def compress_skip_list(skip_cases, ran_cases, script_path):
    """
    Compress skip cases to the highest possible level.
    If ALL methods under a class are skipped (and none ran), use the class name.
    Otherwise use method names.
    Output uses SHORT names (relative to script_path), not full paths.
    """
    # Group skips by class (3rd segment after script path)
    prefix_len = len(script_path) + 1  # +1 for the dot

    # Collect all classes that have skipped cases
    class_skips = defaultdict(set)  # class_name → set of full skip cases
    class_rans = defaultdict(set)   # class_name → set of full ran cases
    no_class_skips = []  # skips that are directly under script (no class)

    for case in skip_cases:
        suffix = case[prefix_len:] if case.startswith(script_path + ".") else case
        parts = suffix.split(".")
        if len(parts) >= 2:
            # Has class: e.g. TestShowVlan.test_show_vlan_brief
            class_name = parts[0]
            class_skips[class_name].add(case)
        else:
            no_class_skips.append(suffix)  # short name

    for case in ran_cases:
        suffix = case[prefix_len:] if case.startswith(script_path + ".") else case
        parts = suffix.split(".")
        if len(parts) >= 2:
            class_name = parts[0]
            class_rans[class_name].add(case)

    # Build compressed skip list using SHORT names
    result = []

    for class_name in sorted(class_skips.keys()):
        if class_name in class_rans and class_rans[class_name]:
            # Some methods ran in this class — list individual method names
            for case in sorted(class_skips[class_name]):
                suffix = case[prefix_len:] if case.startswith(script_path + ".") else case
                # suffix is like "ClassName.method_name" — keep as-is (relative to module)
                result.append(suffix)
        else:
            # ALL methods in this class are skipped — use class name only
            result.append(class_name)

    # Add non-class skips (already short names)
    result.extend(sorted(no_class_skips))

    return sorted(result)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    feature = sys.argv[1]

    # Protected files that should NOT be overwritten by this script
    PROTECTED_FEATURES = {"platform_tests"}
    if feature in PROTECTED_FEATURES:
        print(f"ERROR: '{feature}' is protected. t1_{feature}.yaml is manually maintained.")
        print("Edit the file directly instead of regenerating it.")
        sys.exit(1)

    print(f"=== Generating expected cases for feature: {feature} ===\n")

    # Collect union of ran cases (any HWSKU ran it → expected)
    all_ran = set()
    # Track per-case: which HWSKUs have it and which skipped it
    case_skip_count = defaultdict(int)   # case → count of HWSKUs that skipped it
    case_present_count = defaultdict(int)  # case → count of HWSKUs that have it (ran or skip)

    for hwsku, (ran_file, skip_file) in HWSKU_FILES.items():
        ran_path = DATA_DIR / ran_file
        skip_path = DATA_DIR / skip_file

        ran = load_feature(ran_path, feature) if ran_path.exists() else set()
        skip = load_feature(skip_path, feature) if skip_path.exists() else set()

        all_ran.update(ran)
        # Track per-case presence
        for case in ran:
            case_present_count[case] += 1
        for case in skip:
            case_present_count[case] += 1
            case_skip_count[case] += 1

        total = len(ran) + len(skip)
        if total:
            print(f"  {hwsku}: {len(ran)} ran, {len(skip)} skip_only")
        else:
            print(f"  {hwsku}: n/a (not applicable)")

    # Skip = cases where ALL applicable (non-n/a) HWSKUs skipped it
    # i.e., skip_count == present_count AND not ran by anyone
    universal_skip = set()
    for case, present in case_present_count.items():
        if case not in all_ran and case_skip_count.get(case, 0) == present:
            universal_skip.add(case)

    print(f"\n  Union of ran (any HWSKU): {len(all_ran)} cases")
    print(f"  Universal skip (all applicable skipped): {len(universal_skip)} cases")

    # Compress into module format
    entries = compress_to_modules(all_ran, universal_skip, feature)

    # Build output
    output = {
        "metadata": {
            "description": f"{feature} expected cases (T1, 202511)",
            "feature": feature,
            "logic": "ran = any HWSKU ran it; skip = all applicable (non-n/a) HWSKUs skipped it",
            "branch": "202511",
            "ran_count": len(all_ran),
            "skip_count": len(universal_skip),
        },
        feature: entries,
    }

    outfile = ROOT_DIR / "yaml" / f"t1_{feature}.yaml"
    with open(outfile, "w") as f:
        yaml.dump(output, f, default_flow_style=False, sort_keys=False, width=200,
                  indent=2, default_style=None)
        # Fix: PyYAML doesn't indent list items under keys by default.
        # Re-write with proper indentation.
    # Re-read and fix indentation for list items
    with open(outfile) as f:
        content = f.read()
    # Add proper indentation: feature items get 4 spaces, skip items get 8 spaces
    lines = content.split("\n")
    result = []
    in_feature_list = False
    in_skip_block = False
    for line in lines:
        if line.startswith("{}:".format(feature)):
            in_feature_list = True
            in_skip_block = False
            result.append(line)
        elif in_feature_list and line.startswith("- "):
            # Top-level list item under feature → indent to 4 spaces
            in_skip_block = False
            result.append("    " + line)
        elif in_feature_list and line.startswith("  skip:"):
            # skip: key under module → indent to 6 spaces
            in_skip_block = True
            result.append("    " + line)
        elif in_feature_list and in_skip_block and line.startswith("  - "):
            # skip list item → indent to 8 spaces
            result.append("      " + line)
        elif in_feature_list and line.startswith("  "):
            # Other continuation (e.g., module key-value pair) → indent to 4 spaces
            in_skip_block = False
            result.append("    " + line)
        elif in_feature_list and line == "":
            in_feature_list = False
            in_skip_block = False
            result.append(line)
        else:
            in_feature_list = False
            in_skip_block = False
            result.append(line)
    with open(outfile, "w") as f:
        f.write("\n".join(result))

    print(f"\nWritten: {outfile.name}")
    print(f"  {len(entries)} module entries")


if __name__ == "__main__":
    main()
