from utilities.kusto import execute_kusto_query


def get_ferret_replied_packets_in_window(device: str, start_time: str, end_time: str):
    """
    Get the number of replied Ferret server packets for a device during the
    given time window, broken down per Ferret server (hop).

    A device may reach a different Ferret server per upgrade (not guaranteed to
    be the same one), so the `Responded`
    (para1) field is reported independently per server rather than summed
    together. Returns a DataFrame with columns `server` and `RepliedPackets`,
    or an empty DataFrame if the device has no Ferret Neighbor data in the
    window (absent).
    """

    query = f'''
let startTime = datetime("{start_time}");
let endTime = datetime("{end_time}");
let deviceName = "{device}";
cluster("Azphynet").database("aznwmds").FerretLog
| where tag contains 'Neighbor'
| where PreciseTimeStamp between (startTime .. endTime)
| where para3 =~ deviceName
| project server, RepliedPackets = tolong(para1)
'''
    df_res = execute_kusto_query("azphynet", "aznwmds", query)
    return df_res
