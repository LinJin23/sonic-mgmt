"""
Batch Dry-Run: Query Kusto for recent BuildIds per HWSKU group, run dryrun_testplan.py
for each, and save date-stamped logs.

Usage:
    python batch_dryrun.py              # run T0, T1, and dualtor
    python batch_dryrun.py --t0         # T0 only
    python batch_dryrun.py --t1         # T1 only
    python batch_dryrun.py --dualtor    # dualtor only
"""
import sys
import os
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
from azure.kusto.data import KustoClient, KustoConnectionStringBuilder

SCRIPTS_DIR = Path(__file__).parent
ROOT_DIR = SCRIPTS_DIR.parent
LOG_DIR = ROOT_DIR / "log"
LOG_DIR.mkdir(exist_ok=True)

KUSTO_CLUSTER = "https://sonicrepodatadev.westus.kusto.windows.net"
KUSTO_DB = "SonicTestData"

# T1 HWSKU groups — one representative HWSKU per group to pick BuildIds
T1_HWSKU_GROUPS = {
    "Cisco_8102": {
        "hwskus": ["Cisco-8102-C64"],
        "topology_filter": "t1",
    },
    "Cisco_8101_O32": {
        "hwskus": ["Cisco-8101-O32"],
        "topology_filter": "t1",
    },
    "Cisco_8101_O8C48": {
        "hwskus": ["Cisco-8101-O8C48"],
        "topology_filter": "t1",
    },
    "Cisco_8101_O8V48": {
        "hwskus": ["Cisco-8101-O8V48"],
        "topology_filter": "t1",
    },
    "Arista_7060_T1": {
        "hwskus": ["Arista-7060CX-32S-C32"],
        "topology_filter": "t1",
    },
    "Arista_7260_T1": {
        "hwskus": ["Arista-7260CX3-C64"],
        "topology_filter": "t1",
    },
    "MLX_2700_T1": {
        "hwskus": ["Mellanox-SN2700"],
        "topology_filter": "t1",
    },
    "MLX_4600_T1": {
        "hwskus": ["Mellanox-SN4600C-C64"],
        "topology_filter": "t1",
    },
    "MLX_4700_T1": {
        "hwskus": ["Mellanox-SN4700-O32"],
        "topology_filter": "t1",
    },
}

# T0 HWSKU groups — some groups have multiple HWSKUs that may share a BuildId
T0_HWSKU_GROUPS = {
    "Arista_7050": {
        "hwskus": ["Arista-7050CX3-32C-C32", "Arista-7050CX3-32S-C32"],
        "topology_filter": "t0",
    },
    "Arista_7060": {
        "hwskus": ["Arista-7060CX-32S-C32", "Arista-7060CX-32S-D48C8", "Arista-7060CX-32S-Q32"],
        "topology_filter": "t0",
    },
    "Arista_7260": {
        "hwskus": ["Arista-7260CX3-D108C8", "Arista-7260CX3-D108C10"],
        "topology_filter": "t0",
    },
    "MLX_2700": {
        "hwskus": ["Mellanox-SN2700", "Mellanox-SN2700-A1"],
        "topology_filter": "t0",
    },
    "MLX_4600": {
        "hwskus": ["Mellanox-SN4600C-C64"],
        "topology_filter": "t0",
    },
    "MLX_4700": {
        "hwskus": ["Mellanox-SN4700-O8V48"],
        "topology_filter": "t0",
    },
}

# Dualtor HWSKU groups
DUALTOR_HWSKU_GROUPS = {
    "Arista_7050_DT": {
        "hwskus": ["Arista-7050CX3-32C-C32", "Arista-7050CX3-32S-C32"],
        "topology_filter": "dualtor",
    },
    "Arista_7260_DT": {
        "hwskus": ["Arista-7260CX3-D108C8", "Arista-7260CX3-C64"],
        "topology_filter": "dualtor",
    },
    "Cisco_8101_DT": {
        "hwskus": ["Cisco-8101C01-C32", "Cisco-8101C01-V64"],
        "topology_filter": "dualtor",
    },
    "MLX_4700_DT": {
        "hwskus": ["Mellanox-SN4700-V64"],
        "topology_filter": "dualtor",
    },
}


def find_build_ids(hwsku_groups):
    """Query Kusto to find recent finished BuildIds for each HWSKU group.

    For groups with multiple HWSKUs, finds a BuildId that contains ANY of them.
    Returns {group_name: {build_id, case_count, hwsku_found, max_time}}.
    """
    # Collect all HWSKUs and topology filters
    all_hwskus = []
    for group in hwsku_groups.values():
        all_hwskus.extend(group["hwskus"])
    hwsku_list = ", ".join(f'"{h}"' for h in all_hwskus)

    # Determine topology filter (all groups in one call share the same filter)
    topo_filter = list(hwsku_groups.values())[0]["topology_filter"]
    # Use 'contains' for dualtor, 'startswith' for t0/t1
    if topo_filter == "dualtor":
        topo_clause = f'| where Topology contains "{topo_filter}"'
    else:
        topo_clause = f'| where Topology startswith "{topo_filter}"'

    query = """
let base = TestReportUnionData
| where UploadTimestamp > ago(30d)
| where TestBranch == "internal-202511"
| where HardwareSku in ({hwsku_list})
{topo_clause}
| where OSVersion contains "202511"
| where PipeStatus contains "finish";
base
| summarize CaseCount=dcount(FullCaseName), MaxTime=max(UploadTimestamp) by HardwareSku, BuildId
| where CaseCount > 1000
| order by HardwareSku asc, MaxTime desc
""".format(hwsku_list=hwsku_list, topo_clause=topo_clause)
    print(f"  Querying Kusto for {topo_filter.upper()} BuildIds...")
    kcsb = KustoConnectionStringBuilder.with_az_cli_authentication(KUSTO_CLUSTER)
    client = KustoClient(kcsb)
    response = client.execute(KUSTO_DB, query)

    # Index by HWSKU: pick most recent BuildId per HWSKU
    hwsku_builds = {}  # {hwsku: {build_id, case_count, max_time}}
    for row in response.primary_results[0]:
        hwsku = row["HardwareSku"]
        if hwsku not in hwsku_builds:
            hwsku_builds[hwsku] = {
                "build_id": row["BuildId"],
                "case_count": row["CaseCount"],
                "max_time": str(row["MaxTime"]),
            }

    # Map groups to BuildIds (pick from first matching HWSKU in group)
    results = {}
    for group_name, group_info in hwsku_groups.items():
        for hwsku in group_info["hwskus"]:
            if hwsku in hwsku_builds:
                info = hwsku_builds[hwsku]
                results[group_name] = {
                    "build_id": info["build_id"],
                    "case_count": info["case_count"],
                    "hwsku_found": hwsku,
                    "max_time": info["max_time"],
                }
                break
    return results


def run_dryrun(build_id, group_name, log_file, date_str):
    """Run dryrun_testplan.py and capture output to log file."""
    cmd = [sys.executable, str(SCRIPTS_DIR / "dryrun_testplan.py"), build_id]
    print(f"    Running: python dryrun_testplan.py {build_id}")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=str(SCRIPTS_DIR), env=env, encoding="utf-8"
    )
    output = result.stdout + result.stderr
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("# Dry-Run Report\n")
        f.write(f"# Group: {group_name}\n")
        f.write(f"# BuildId: {build_id}\n")
        f.write(f"# Date: {date_str}\n")
        f.write(f"# Command: python dryrun_testplan.py {build_id}\n")
        f.write("{}\n\n".format("=" * 80))
        f.write(output)
    return result.returncode, output


def run_batch(hwsku_groups, topo_label, date_str):
    """Run dryrun for all groups in the given topology."""
    print("\n{}".format("=" * 80))
    print(f"  {topo_label} DRY-RUN BATCH ({date_str})")
    print("=" * 80)

    # Step 1: Find BuildIds
    build_ids = find_build_ids(hwsku_groups)

    print("\n  Found BuildIds for {}/{} groups:".format(len(build_ids), len(hwsku_groups)))
    for group_name in hwsku_groups:
        if group_name in build_ids:
            info = build_ids[group_name]
            print(
                "    {:<20} BuildId={}... Cases={} HWSKU={} Time={}".format(
                    group_name,
                    info["build_id"][:12],
                    info["case_count"],
                    info["hwsku_found"],
                    info["max_time"][:10],
                )
            )
        else:
            print("    {:<20} -- No qualifying BuildId found".format(group_name))

    # Step 2: Run dryrun for each group
    print("\n  Running dry-runs...")
    summaries = []

    for group_name in hwsku_groups:
        if group_name not in build_ids:
            print(f"\n    SKIP {group_name}: no BuildId")
            continue

        info = build_ids[group_name]
        build_id = info["build_id"]
        safe_name = group_name.lower()
        log_file = LOG_DIR / f"dryrun_{topo_label.lower()}_{safe_name}_{date_str}.log"

        print("\n  {}".format("-" * 60))
        print(f"  {group_name} ({info['hwsku_found']}, {info['case_count']} cases)")
        print("  {}".format("-" * 60))

        rc, output = run_dryrun(build_id, group_name, log_file, date_str)
        if rc != 0:
            error_summary = f"ERROR: dryrun_testplan.py exited with rc={rc}"
            summaries.append((group_name, error_summary))
            print(f"    {error_summary}")
            print(f"    Saved: {log_file.name}")
            continue

        # Extract summary
        summary_line = ""
        for line in output.split("\n"):
            if "SUMMARY:" in line:
                summary_line = line.strip()
                break
        summaries.append((group_name, summary_line))
        print(f"    {summary_line}")
        print(f"    Saved: {log_file.name}")

    # Final summary table
    print("\n{}".format("=" * 80))
    print(f"  {topo_label} RESULTS SUMMARY")
    print("=" * 80)
    print("  {:<20} {:>8} {:>6} {:>6} {:>6}".format("Group", "Expected", "Ran", "Skips", "Rate"))
    print("  {:<20} {:>8} {:>6} {:>6} {:>6}".format("-" * 20, "-" * 8, "-" * 6, "-" * 6, "-" * 6))
    for group_name, summary in summaries:
        # Parse "SUMMARY: 758/829 expected cases ran | 71 unexpected skips"
        try:
            parts = summary.split()
            ran_total = parts[1]  # "758/829"
            ran, total = ran_total.split("/")
            skips = parts[6]  # number before "unexpected"
            rate = "{:.1f}%".format(int(ran) / int(total) * 100)
            print("  {:<20} {:>8} {:>6} {:>6} {:>6}".format(group_name, total, ran, skips, rate))
        except (IndexError, ValueError):
            print("  {:<20} {}".format(group_name, summary))
    print("=" * 80)
    print(f"  Logs: {LOG_DIR}")


def main():
    parser = argparse.ArgumentParser(description="Batch dry-run for SONiC test matrix")
    parser.add_argument("--t0", action="store_true", help="Run T0 only")
    parser.add_argument("--t1", action="store_true", help="Run T1 only")
    parser.add_argument("--dualtor", action="store_true", help="Run dualtor only")
    args = parser.parse_args()

    # Default: run all if none specified
    any_specified = args.t0 or args.t1 or args.dualtor
    run_t0 = args.t0 or not any_specified
    run_t1 = args.t1 or not any_specified
    run_dualtor = args.dualtor or not any_specified

    date_str = datetime.now().strftime("%Y%m%d")

    if run_t1:
        run_batch(T1_HWSKU_GROUPS, "T1", date_str)
    if run_t0:
        run_batch(T0_HWSKU_GROUPS, "T0", date_str)
    if run_dualtor:
        run_batch(DUALTOR_HWSKU_GROUPS, "DUALTOR", date_str)


if __name__ == "__main__":
    main()
