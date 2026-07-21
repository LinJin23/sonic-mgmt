from typing import List, Optional

from pandas import DataFrame

from utilities.kusto import execute_kusto_query
from utilities.sonic_shift import normalize_timestamp_to_iso_utc


def get_warmboot_window_bounds_batch(upgrades: DataFrame) -> DataFrame:
    """Derive the warm-reboot start/stop syslog bounds for many upgrades with a SINGLE Kusto query.

    ``upgrades`` must have ``DeviceName`` (host), ``StartTime``, ``EndTime`` (the enclosing
    upgrade-method window) and ``EventGuid`` (correlates the warm-reboot CLI syslog). For each
    upgrade:

      * ``WbStart``  = first ``/usr/local/bin/warm-reboot -c ... -e <EventGuid>`` log in
        [StartTime, EndTime].
      * ``WbEndRaw`` = first "Tearing down control plane assistant" log in [WbStart, EndTime]
        (null if that teardown log is missing, e.g. a failed warmboot).

    Returns a DataFrame with one row per upgrade that has a warm-reboot CLI log, columns
    ``UpgradeKey`` (str of the upgrade's DataFrame index), ``WbStart`` and ``WbEndRaw`` (null
    when the teardown log is missing).
    """
    required_columns = {"DeviceName", "StartTime", "EndTime", "EventGuid"}
    missing_columns = required_columns - set(upgrades.columns)
    assert not missing_columns, f"upgrades is missing required columns: {sorted(missing_columns)}"

    if upgrades.empty:
        return DataFrame(columns=["UpgradeKey", "WbStart", "WbEndRaw"])

    # One datatable row per upgrade, keyed by the (stringified) DataFrame index.
    literal_rows = []
    for idx, row in upgrades.iterrows():
        start_iso = normalize_timestamp_to_iso_utc(row["StartTime"])
        end_iso = normalize_timestamp_to_iso_utc(row["EndTime"])
        device = str(row["DeviceName"])
        guid = str(row["EventGuid"]).lower()
        literal_rows.append(
            '    "{idx}", "{device}", "{guid}", datetime({start}), datetime({end})'.format(
                idx=idx, device=device, guid=guid, start=start_iso, end=end_iso
            )
        )

    upgrades_literal = ",\n".join(literal_rows)
    # rf-string: regex backslashes stay literal while {..} interpolates; literal braces are {{ }}.
    query = rf"""
let upgrades = datatable(UpgradeKey: string, TorName: string, guid: string, StartTime: datetime, EndTime: datetime)
[
{upgrades_literal}
];
let tlo = toscalar(upgrades | summarize min(StartTime));
let thi = toscalar(upgrades | summarize max(EndTime));
let hosts = toscalar(upgrades | summarize make_set(tolower(TorName)));
// wb_start: first warm-reboot CLI syslog carrying this upgrade's EventGuid, within its window.
let cliStart =
    cluster('azphynet.kusto.windows.net').database('azdhmds').SyslogData
    | where TIMESTAMP between (tlo .. thi)
    | where Message has "warm-reboot"
    | extend host = tolower(Device)
    | where host in (hosts)
    | where Message matches regex @"(?i)/usr/local/bin/warm-reboot\s+-c\b"
    | extend guid = tolower(extract(@"-e\s+([0-9a-fA-F-]{{36}})", 1, Message))
    | where isnotempty(guid)
    | project host, guid, ts = TIMESTAMP;
let wbStart =
    upgrades
    | extend host = tolower(TorName)
    | join kind = inner cliStart on host, guid
    | where ts >= StartTime and ts <= EndTime
    | summarize wb_start = min(ts) by UpgradeKey, host, StartTime, EndTime;
// wb_end: first control-plane-assistant teardown after wb_start (fallback handled by the aggregator).
let teardownEv =
    cluster('azphynet.kusto.windows.net').database('azdhmds').SyslogData
    | where TIMESTAMP between (tlo .. thi)
    | where Message has "Tearing down control plane assistant"
    | extend host = tolower(Device)
    | where host in (hosts)
    | project host, end_ts = TIMESTAMP;
wbStart
| join kind = leftouter teardownEv on host
| summarize wb_end_raw = minif(end_ts, end_ts >= wb_start and end_ts <= EndTime)
    by UpgradeKey, host, StartTime, EndTime, wb_start
| project UpgradeKey, WbStart = wb_start, WbEndRaw = wb_end_raw
"""
    return execute_kusto_query("azphynet", "azdhmds", query)


def get_devices_with_excessive_syslog(devices: List[str]):

    formatted_devices = ', '.join([f'"{device}"' for device in devices])
    query = f'''

let devices = dynamic([{formatted_devices}]);
cluster('azphynet.kusto.windows.net').database('HwSwHealth').dhExceessiveSyslogs
| where TIMESTAMP > ago(2h)
| where DeviceName in~ (devices)
| summarize arg_max(TIMESTAMP, *) by DeviceName
| project DeviceName, FailureReason, MetricValue_Count
'''
    df_res = execute_kusto_query("azphynet", "HwSwHealth", query)
    return df_res


def get_syncd_restore_count(device: str, start_time: str, end_time: str):
    """
    Get the syncd restore count in the specified time window.

    """

    query = f'''

let startTime = datetime({start_time});
let endTime = datetime({end_time});
let rgx = @"syncd#syncd.+restore count (\\d+)";
let restoreCounts = cluster('azphynet.kusto.windows.net').database('azdhmds').SyslogData
| where Device =~ "{device}"
| where TIMESTAMP between (startTime .. endTime)
| where Message matches regex rgx
| extend restore_count = extract(rgx, 1, Message)
| project restore_count;
let summaryMessage = restoreCounts
| summarize row_count = count()
| extend output = case(
    row_count == 0, "No warm-reboot count found",
    row_count == 1, strcat("warm-reboot count: ", toscalar(restoreCounts | project restore_count)),
    strcat("Error: More than one warm-reboot count found (", row_count, ")")
)
| project output;
summaryMessage;

'''
    df_res = execute_kusto_query("azphynet", "azdhmds", query)
    result = df_res.iloc[0, 0]
    return result


def get_syslog_for_device_in_window(
    device: str,
    start_time: str,
    end_time: str,
    message_regex: Optional[str] = None,
):
    """
    Fetch syslog rows for a device in a time window.
    If message_regex is provided, filter to only messages matching that KQL regex.
    """

    regex_clause = ""
    if message_regex:
        # KQL expects the regex as a verbatim string literal: @"..."
        safe = message_regex.replace('"', r'\"')
        regex_clause = f'| where Message matches regex @"{safe}"'

    query = f'''
let startTime = datetime({start_time});
let endTime = datetime({end_time});

cluster('azphynet.kusto.windows.net').database('azdhmds').SyslogData
| where Device =~ "{device}"
| where TIMESTAMP between (startTime .. endTime)
| where Message notcontains "audisp"
| where Message notcontains "audisp-syslog:"
| where Message notcontains "auditlogger["
| where Message notcontains "macsec_mka["
{regex_clause}
| project
    Timestamp = TIMESTAMP,
    Device,
    Message
| order by Timestamp asc
'''
    df_res = execute_kusto_query("azphynet", "azdhmds", query)
    return df_res
