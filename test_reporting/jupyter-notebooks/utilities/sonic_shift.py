"""SonicShiftUpgradeSummary-scoped query helpers for SONiC Shift ETL."""

from io import StringIO
import json
import pandas as pd
from pandas import DataFrame
from azure.kusto.data.data_format import DataFormat
from azure.kusto.ingest import ColumnMapping, IngestionMappingKind, IngestionProperties
from utilities.kusto import execute_kusto_query, execute_kusto_command, build_ingest_client


UTC_ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Kusto ingest/target configuration for the SONiC Shift tables. Centralized here so
# callers (e.g. the ETL pipeline) don't hardcode the endpoint/database/cluster.
KUSTO_INGEST_URI = "https://ingest-sonicrepodatadev.westus.kusto.windows.net"
KUSTO_DATABASE = "SonicTestData"


def normalize_timestamp_to_iso_utc(timestamp) -> str | None:
    """Normalize timestamp to ISO 8601 UTC format (YYYY-MM-DDTHH:MM:SSZ).
    Accepts pd.Timestamp, str, or other datetime-like objects.
    Returns formatted string or None if coercion fails.
    """
    if timestamp is None:
        return None
    if isinstance(timestamp, str):
        timestamp = pd.to_datetime(timestamp, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return None
    return timestamp.strftime(UTC_ISO_FORMAT)


def get_existing_sonic_shift_upgrade_summary_rows(device_names: list[str], target_versions: list[str]) -> DataFrame:
    """Fetch existing HardwareProxy rows for the provided devices and target versions.
    Returns an empty DataFrame if either list is empty (OR), because matching requires both filters.
    """
    if not device_names or not target_versions:
        return DataFrame()

    devices_json = json.dumps(device_names)
    versions_json = json.dumps(target_versions)
    query = f"""
    let Devices = dynamic({devices_json});
    let Versions = dynamic({versions_json});
    SonicShiftUpgradeSummary
    | where UpgradeMethod == "HardwareProxy"
    | where set_has_element(Devices, tolower(DeviceName))
    | where set_has_element(Versions, tostring(TargetVersion))
    | project DeviceName = tolower(DeviceName), StartTime, EndTime,
        TargetVersion = tostring(TargetVersion),
        EventGuid = tostring(RawData.eventGuid), RawData
    """
    return execute_kusto_query("sonicrepodatadev.westus", "SonicTestData", query)


def get_latest_ingested_start_time() -> pd.Timestamp | None:
    """Return the latest ingested HardwareProxy StartTime from SonicShiftUpgradeSummary.
    Returns None when no rows exist. Raises ValueError if a value is present but
    cannot be parsed into a timestamp, so the pipeline fails loudly on bad data.
    """
    query = """
    SonicShiftUpgradeSummary
    | where UpgradeMethod == "HardwareProxy"
    | summarize LatestStartTime=max(StartTime)
    """
    df_latest = execute_kusto_query("sonicrepodatadev.westus", "SonicTestData", query)
    raw_latest = None if df_latest.empty else df_latest.iloc[0].get("LatestStartTime")
    if raw_latest is None or pd.isna(raw_latest):
        return None
    latest_start_time = pd.to_datetime(raw_latest, utc=True, errors="coerce")
    if pd.isna(latest_start_time):
        raise ValueError(
            f"Failed to parse LatestStartTime from SonicShiftUpgradeSummary: {raw_latest!r}"
        )
    return latest_start_time


def ingest_hwproxy_rows_to_kusto(df: DataFrame) -> None:
    """Ingest HardwareProxy upgrade rows to SonicShiftUpgradeSummary table in Kusto.
    Expects DataFrame with columns: DeviceName, Cluster, StartTime, EndTime, TargetVersion,
    UpgradeMethod, UpgradeMethodStatus, UpgradeMethodWindowPingMeshDrops,
    WarmbootWindowPingMeshDrops, RawData. The Cluster value comes from the source
    HardwareProxyApiCall row.
    Handles Kusto authentication and ingestion details.
    """
    df = df.reindex(
        columns=[
            "DeviceName", "Cluster", "StartTime", "EndTime", "TargetVersion",
            "UpgradeMethod", "UpgradeMethodStatus", "UpgradeMethodWindowPingMeshDrops",
            "WarmbootWindowPingMeshDrops", "RawData",
        ]
    )

    # Write CSV to in-memory buffer instead of disk.
    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    ingest_client = build_ingest_client(KUSTO_INGEST_URI)
    ingestion_props = IngestionProperties(
        database=KUSTO_DATABASE,
        table="SonicShiftUpgradeSummary",
        data_format=DataFormat.CSV,
        ignore_first_record=True,
    )
    ingestion_props.ingestion_mapping_type = IngestionMappingKind.CSV
    ingestion_props.ingestion_mapping = [
        ColumnMapping("DeviceName", "String"),
        ColumnMapping("Cluster", "String"),
        ColumnMapping("StartTime", "DateTime"),
        ColumnMapping("EndTime", "DateTime"),
        ColumnMapping("TargetVersion", "String"),
        ColumnMapping("UpgradeMethod", "String"),
        ColumnMapping("UpgradeMethodStatus", "String"),
        ColumnMapping("UpgradeMethodWindowPingMeshDrops", "Boolean"),
        ColumnMapping("WarmbootWindowPingMeshDrops", "Boolean"),
        ColumnMapping("RawData", "Dynamic"),
    ]
    ingest_client.ingest_from_stream(csv_buffer, ingestion_properties=ingestion_props)


def get_existing_staging_upgrade_guids(upgrade_guids: list[str]) -> set[str]:
    """Return set of UpgradeGuids that already exist in staging table."""
    if not upgrade_guids:
        return set()
    guids_json = json.dumps(list(upgrade_guids))
    query = f"""
    let Guids = dynamic({guids_json});
    SonicShiftUpgradeSummaryIncomplete
    | where set_has_element(Guids, UpgradeGuid)
    | project UpgradeGuid
    """
    df = execute_kusto_query("sonicrepodatadev.westus", "SonicTestData", query)
    if df.empty:
        return set()
    return set(df["UpgradeGuid"].dropna().astype(str).tolist())


def delete_staging_rows_by_upgrade_guids(upgrade_guids: list[str], database: str = "SonicTestData") -> None:
    """Delete staged incomplete rows whose UpgradeGuid now has a final-state pair in the main table.
    Used to promote resolved upgrade events out of SonicShiftUpgradeSummaryIncomplete.
    """
    if not upgrade_guids:
        return
    guids_json = json.dumps(list(upgrade_guids))
    command = f""".delete table SonicShiftUpgradeSummaryIncomplete records <|
    let Guids = dynamic({guids_json});
    SonicShiftUpgradeSummaryIncomplete
    | where set_has_element(Guids, UpgradeGuid)
    """
    execute_kusto_command("sonicrepodatadev.westus", database, command)


def ingest_incomplete_rows_to_staging(
    df: DataFrame,
    kusto_ingest_uri: str = KUSTO_INGEST_URI,
    database: str = KUSTO_DATABASE,
) -> None:
    """Ingest unmatched incomplete upgrade rows into staging table.
    Expects DataFrame with columns: StartTime, UpgradeGuid, RawData.
    """
    df = df.copy().reindex(columns=["StartTime", "UpgradeGuid", "RawData"])

    csv_buffer = StringIO()
    df.to_csv(csv_buffer, index=False)
    csv_buffer.seek(0)

    ingest_client = build_ingest_client(kusto_ingest_uri)
    ingestion_props = IngestionProperties(
        database=database,
        table="SonicShiftUpgradeSummaryIncomplete",
        data_format=DataFormat.CSV,
        ignore_first_record=True,
    )
    ingestion_props.ingestion_mapping_type = IngestionMappingKind.CSV
    ingestion_props.ingestion_mapping = [
        ColumnMapping("StartTime", "DateTime"),
        ColumnMapping("UpgradeGuid", "String"),
        ColumnMapping("RawData", "Dynamic"),
    ]
    ingest_client.ingest_from_stream(csv_buffer, ingestion_properties=ingestion_props)
