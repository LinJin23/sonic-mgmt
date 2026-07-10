"""HardwareProxy-scoped query helpers for SONiC Shift ETL."""
from pandas import DataFrame

from utilities.kusto import execute_kusto_query


def get_hitless_request_update_firmware_hwproxy_api_calls(since_utc_iso: str) -> DataFrame:
    """Fetch recent HitlessReload RequestUpdateFirmware HardwareProxy API calls.
    Returns one row per logical upgrade with timing derived from row-level TIMESTAMP values.

    Fetches rows whose TIMESTAMP is strictly after ``since_utc_iso`` (an ISO-8601 UTC
    string, e.g. "2026-07-01T10:00:00Z"), i.e. a date-based lower bound rather than a
    relative ago() window, so the fetch is exact and idempotent against the last
    ingested StartTime.

    Source storage: one upgrade spans multiple HardwareProxyApiCall rows sharing the same
    eventGuid, one per state transition (e.g. success="Incomplete" at 10:00:00, then
    success="True" at 10:07:30 for the same device/version).

    Squashing: this query groups those rows by (DeviceName, TargetVersion, EventGuid) into
    one summary row, deriving StartTime from the earliest Incomplete and EndTime from the
    earliest final state. The example above collapses to StartTime=10:00:00, EndTime=10:07:30.

    Rules:
    - StartTime: earliest TIMESTAMP where success == Incomplete.
    - EndTime: earliest TIMESTAMP where success in (True, False).
    - If only incomplete exists: EndTime stays null.
    - If only final exists: StartTime and EndTime both use the final TIMESTAMP.

    Returned columns (one row per upgrade):
    - DeviceName: name of the device being upgraded.
    - Cluster: the cluster the device belongs to (from the raw row payload).
    - StartTime: when the upgrade started (see Rules above).
    - EndTime: when the upgrade reached a final state, or null if still incomplete.
    - TargetVersion: the SONiC version the device is being upgraded to.
    - EventGuid: unique id for the upgrade (from the source eventGuid field).
    - RawData: the full raw HardwareProxyApiCall row (latest by TIMESTAMP) as a dynamic bag.
    - HasFinalState: True if a final (True/False) success row was seen for this upgrade.
    - HasIncompleteState: True if an Incomplete success row was seen for this upgrade.
    """
    query = f"""
    HardwareProxyApiCall
    | where operationName == "RequestUpdateFirmware"
    | where inputs contains "HitlessReload"
    | where TIMESTAMP > datetime({since_utc_iso})
    | extend _success = tolower(success)
    | extend TargetVersion = extract(@"SONiC\\.[^<]+", 0, inputs)
    | extend EventGuid = eventGuid
    | extend _RowData = pack_all()
    | summarize
        FirstIncompleteTs = minif(TIMESTAMP, _success == "incomplete"),
        FirstFinalTs = minif(TIMESTAMP, _success in ("true", "false")),
        arg_max(TIMESTAMP, _RowData)
      by DeviceName = deviceName,
         TargetVersion,
         EventGuid
    | extend StartTime = iif(isnotnull(FirstIncompleteTs), FirstIncompleteTs, FirstFinalTs)
    | extend EndTime = FirstFinalTs
        | extend Cluster = tostring(_RowData.Cluster)
        | extend HasFinalState = isnotnull(FirstFinalTs)
        | extend HasIncompleteState = isnotnull(FirstIncompleteTs)
        | project
            DeviceName, Cluster, StartTime, EndTime, TargetVersion, EventGuid,
            RawData = _RowData, HasFinalState, HasIncompleteState
    """
    return execute_kusto_query("azphynet", "DeviceAccess", query)
