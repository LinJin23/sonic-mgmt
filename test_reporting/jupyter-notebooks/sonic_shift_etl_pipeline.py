import json
import logging
from datetime import date, datetime
import pandas as pd
from utilities.hw_proxy import (
    get_hitless_request_update_firmware_hwproxy_api_calls,
)
from utilities.sonic_shift import (
    get_existing_staging_upgrade_guids,
    get_existing_sonic_shift_upgrade_summary_rows,
    get_latest_ingested_start_time,
    delete_staging_rows_by_upgrade_guids,
    ingest_incomplete_rows_to_staging,
    ingest_hwproxy_rows_to_kusto,
    normalize_timestamp_to_iso_utc,
)
from utilities.dataplane_drop import get_upgrade_method_window_pingmesh_drops_batch

logger = logging.getLogger(__name__)

NULL_SENTINEL = "__NULL__"
DEDUP_KEY_COLS = [
    "DeviceName",
    "TargetVersion",
    "_StartTimeKey",
    "_EndTimeKey",
    "_EventGuid",
    "_SourceTimestamp",
    "_SuccessState",
]


def _to_json_string(raw_value):
    """Normalize RawData into a JSON string for CSV ingestion.
    This ensures dynamic payloads are serialized consistently so Kusto ingestion and later parsing are reliable.
    """
    def _json_default(value):
        # Handle datetime-like objects that json.dumps cannot serialize by default.
        if isinstance(value, (pd.Timestamp, datetime, date)):
            return value.isoformat()
        return str(value)

    if raw_value is None:
        return None
    # Already-structured payloads (dict/list) can be serialized directly.
    if isinstance(raw_value, (dict, list)):
        return json.dumps(raw_value, ensure_ascii=False, default=_json_default)
    # For a string, re-serialize valid JSON (to normalize it); leave non-JSON text untouched.
    if isinstance(raw_value, str):
        try:
            return json.dumps(json.loads(raw_value), ensure_ascii=False, default=_json_default)
        except Exception:
            return raw_value
    # Fallback for scalars / other types.
    return json.dumps(raw_value, ensure_ascii=False, default=_json_default)


def _extract_raw_field(raw_value, field_name):
    """Extract a top-level field from a RawData payload.
    RawData is normally a Kusto dynamic bag (dict); a JSON string is tolerated as a fallback.
    Returns None if the payload cannot be interpreted or the field is absent.
    """
    if isinstance(raw_value, str):
        try:
            raw_value = json.loads(raw_value)
        except Exception:
            return None
    if not isinstance(raw_value, dict):
        return None
    value = raw_value.get(field_name)
    return str(value) if value is not None else None


def _add_sonic_shift_upgrade_summary_dedupe_key_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Extract and normalize deduplication key columns from fetched data.
    Normalizes timestamps to ISO format, extracts eventGuid/TIMESTAMP/success from RawData,
    and fills None values with sentinel to enable deterministic deduplication.
    """
    # Normalize the two timestamp columns to a stable ISO string so equal times compare equal.
    df["_StartTimeKey"] = df["StartTime"].apply(normalize_timestamp_to_iso_utc)
    df["_EndTimeKey"] = df["EndTime"].apply(normalize_timestamp_to_iso_utc)
    # EventGuid is always present as a column (source query and existing-rows query both provide it).
    df["_EventGuid"] = df["EventGuid"].astype(str)
    # Extra discriminators pulled from RawData to make the dedup key unique per source event.
    df["_SourceTimestamp"] = df["RawData"].apply(lambda x: _extract_raw_field(x, "TIMESTAMP"))
    df["_SuccessState"] = df["RawData"].apply(lambda x: _extract_raw_field(x, "success"))
    # Replace None with a sentinel so rows with nulls still match deterministically on merge.
    for col in DEDUP_KEY_COLS[2:]:
        df[col] = df[col].fillna(NULL_SENTINEL)
    return df


def deduplicate_main_rows_against_existing(df_jobs: pd.DataFrame) -> pd.DataFrame:
    """Remove rows already present in SonicShiftUpgradeSummary for this fetched batch."""
    if df_jobs.empty:
        return df_jobs

    # Normalize join columns (case-insensitive device names) on the incoming batch.
    fetched_upgrades = df_jobs.copy()
    fetched_upgrades["DeviceName"] = fetched_upgrades["DeviceName"].astype(str).str.lower()
    fetched_upgrades["TargetVersion"] = fetched_upgrades["TargetVersion"].astype(str)

    # Narrow the existing-rows query to only the devices/versions in this batch.
    devices = sorted(fetched_upgrades["DeviceName"].dropna().unique().tolist())
    versions = sorted(fetched_upgrades["TargetVersion"].dropna().unique().tolist())
    if not devices or not versions:
        return df_jobs

    existing_upgrades_in_sonic_shift_upgrade_summary = get_existing_sonic_shift_upgrade_summary_rows(devices, versions)

    # Nothing already ingested for these devices/versions — every row is new.
    if existing_upgrades_in_sonic_shift_upgrade_summary.empty:
        return df_jobs

    # Build merge-safe comparable keys so null timestamps are still deduped deterministically.
    fetched_upgrades = _add_sonic_shift_upgrade_summary_dedupe_key_columns(fetched_upgrades)
    existing_upgrades_in_sonic_shift_upgrade_summary = _add_sonic_shift_upgrade_summary_dedupe_key_columns(
        existing_upgrades_in_sonic_shift_upgrade_summary.copy()
    )

    # Collapse any internal duplicates on both sides before comparing.
    fetched_upgrades = fetched_upgrades.drop_duplicates(subset=DEDUP_KEY_COLS)
    existing_upgrades_in_sonic_shift_upgrade_summary = existing_upgrades_in_sonic_shift_upgrade_summary.drop_duplicates(
        subset=DEDUP_KEY_COLS
    )

    # Left-join on the dedup key; keep only rows with no match in existing ("left_only").
    merged = fetched_upgrades.merge(
        existing_upgrades_in_sonic_shift_upgrade_summary[DEDUP_KEY_COLS],
        how="left", on=DEDUP_KEY_COLS, indicator=True,
    )
    df_new = merged[merged["_merge"] == "left_only"].drop(columns=["_merge", *DEDUP_KEY_COLS[2:]])
    return df_new


def main() -> int:
    # 1. Fetch data: only pull source events newer than the latest StartTime already ingested.
    latest_start = get_latest_ingested_start_time()
    now_utc = pd.Timestamp.now(tz="UTC")
    if latest_start is None:
        # First ingest: table is empty, so fall back to a 60-day lookback window.
        latest_start = now_utc - pd.Timedelta(days=60)
    # The source query uses this ISO string as a strict lower bound (StartTime > since_utc_iso).
    since_utc_iso = normalize_timestamp_to_iso_utc(latest_start)
    df_fetched_events = get_hitless_request_update_firmware_hwproxy_api_calls(since_utc_iso=since_utc_iso)
    logger.info(
        "Latest StartTime from target Kusto: %s\n"
        "Current UTC: %s\n"
        "Time difference (current-latest): %s\n"
        "Fetched rows since %s: %s",
        since_utc_iso,
        normalize_timestamp_to_iso_utc(now_utc),
        str((now_utc - latest_start)).split(".")[0],
        since_utc_iso,
        len(df_fetched_events),
    )

    # Nothing new to process this run.
    if df_fetched_events.empty:
        return 0

    # 1b. Data-quality check: RawData must carry the full row payload (with eventGuid),
    #     not a bare timestamp. This guards against the source query regressing such that
    #     RawData/eventGuid silently come back empty.
    raw_guids = df_fetched_events["RawData"].apply(lambda x: _extract_raw_field(x, "eventGuid"))
    empty_raw = int(
        df_fetched_events["RawData"].isna().sum()
        + (df_fetched_events["RawData"].astype(str).str.strip() == "").sum()
    )
    missing_guid = int(raw_guids.isna().sum())
    logger.info(
        "Data-quality: rows with empty RawData: %s\n"
        "Data-quality: rows with no eventGuid extractable from RawData: %s/%s",
        empty_raw, missing_guid, len(df_fetched_events),
    )
    if len(df_fetched_events) > 0 and missing_guid == len(df_fetched_events):
        logger.warning(
            "eventGuid could not be extracted from RawData for ANY fetched row. "
            "RawData likely does not contain the full payload (check the source query's "
            "arg_max(TIMESTAMP, _RowData) projection)."
        )

    # 2. Add required columns
    # Tag every row with the fixed upgrade method and a stable per-event id used for staging dedup.
    df_fetched_events["UpgradeMethod"] = "HardwareProxy"
    df_fetched_events["UpgradeGuid"] = df_fetched_events["EventGuid"].astype(str)

    # 3. Route each upgrade event to a destination table based on its state.
    #    Combine the final/incomplete signals into a single Destination string:
    #      "main"    -> reached a final state (SonicShiftUpgradeSummary)
    #      "staging" -> only incomplete so far (SonicShiftUpgradeSummaryIncomplete)
    has_final = df_fetched_events["HasFinalState"].fillna(False).astype(bool)
    has_incomplete = df_fetched_events["HasIncompleteState"].fillna(False).astype(bool)

    df_fetched_events["Destination"] = ""
    df_fetched_events.loc[has_final, "Destination"] = "main"
    df_fetched_events.loc[has_incomplete & ~has_final, "Destination"] = "staging"

    # Events that reached a final state go to the main summary table; incomplete-only
    # events (no final state yet) go to the staging table.
    SonicShiftUpgradeSummary_df = df_fetched_events[df_fetched_events["Destination"] == "main"].copy()
    SonicShiftUpgradeSummaryIncomplete_df = df_fetched_events[
        df_fetched_events["Destination"] == "staging"
    ].copy()
    logger.info(
        "Events with a final state -> SonicShiftUpgradeSummary table: %s\n"
        "Incomplete-only events -> SonicShiftUpgradeSummaryIncomplete table: %s",
        len(SonicShiftUpgradeSummary_df), len(SonicShiftUpgradeSummaryIncomplete_df),
    )

    # 4. Remove main-path rows already ingested for this fetched batch.
    pre_dedup = len(SonicShiftUpgradeSummary_df)
    SonicShiftUpgradeSummary_df = deduplicate_main_rows_against_existing(SonicShiftUpgradeSummary_df)
    logger.info(
        "Deduplication on main-path rows: %s\n"
        "Main-path deduplicated rows removed: %s",
        "yes" if len(SonicShiftUpgradeSummary_df) < pre_dedup else "no",
        pre_dedup - len(SonicShiftUpgradeSummary_df),
    )

    # 5. Keep one staging row per unique upgrade event and skip already-staged events.
    if not SonicShiftUpgradeSummaryIncomplete_df.empty:
        # Keep the latest row per event id (sort by StartTime so keep="last" is deterministic).
        SonicShiftUpgradeSummaryIncomplete_df = SonicShiftUpgradeSummaryIncomplete_df.sort_values(
            "StartTime"
        ).drop_duplicates(
            subset=["UpgradeGuid"],
            keep="last",
        )
        # ...then drop events that are already sitting in the staging table.
        existing_staging_guids = get_existing_staging_upgrade_guids(
            SonicShiftUpgradeSummaryIncomplete_df["UpgradeGuid"].tolist()
        )
        SonicShiftUpgradeSummaryIncomplete_df = SonicShiftUpgradeSummaryIncomplete_df[
            ~SonicShiftUpgradeSummaryIncomplete_df["UpgradeGuid"].isin(existing_staging_guids)
        ]
        logger.info(
            "Staging rows after unique-event and existing-staging dedup: %s",
            len(SonicShiftUpgradeSummaryIncomplete_df),
        )

    # 6. Normalize data before ingestion.
    if not SonicShiftUpgradeSummary_df.empty:
        # UpgradeMethodStatus captures the HardwareProxy "success" value from RawData
        # (e.g. incomplete / true / false) before RawData is serialized.
        SonicShiftUpgradeSummary_df["UpgradeMethodStatus"] = SonicShiftUpgradeSummary_df["RawData"].apply(
            lambda x: _extract_raw_field(x, "success")
        )
        # Flag whether pingmesh drops occurred during each row's upgrade-method window
        # ([StartTime, EndTime]) with a SINGLE Kusto query for the whole batch, merged back
        # by index. Computed before StartTime/EndTime are normalized below.
        pingmesh_drops = get_upgrade_method_window_pingmesh_drops_batch(SonicShiftUpgradeSummary_df)
        SonicShiftUpgradeSummary_df["UpgradeMethodWindowPingMeshDrops"] = pingmesh_drops["HasDrop"]
        # Store the per-bucket drop detail (Timestamp, NodeId, SendCount, RecvCount) inside the
        # existing RawData dynamic column for downstream time-window analysis.
        SonicShiftUpgradeSummary_df["RawData"] = [
            {**raw, "PingMeshDropBuckets": buckets}
            for raw, buckets in zip(
                SonicShiftUpgradeSummary_df["RawData"], pingmesh_drops["DropBuckets"]
            )
        ]
        # Convert timestamps to ISO strings and RawData to a JSON string for CSV ingestion.
        SonicShiftUpgradeSummary_df["StartTime"] = SonicShiftUpgradeSummary_df["StartTime"].apply(
            normalize_timestamp_to_iso_utc
        )
        SonicShiftUpgradeSummary_df["EndTime"] = SonicShiftUpgradeSummary_df["EndTime"].apply(
            normalize_timestamp_to_iso_utc
        )
        SonicShiftUpgradeSummary_df["RawData"] = SonicShiftUpgradeSummary_df["RawData"].apply(_to_json_string)

    if not SonicShiftUpgradeSummaryIncomplete_df.empty:
        # Staging rows only carry a StartTime (no final EndTime yet).
        SonicShiftUpgradeSummaryIncomplete_df["StartTime"] = SonicShiftUpgradeSummaryIncomplete_df["StartTime"].apply(
            normalize_timestamp_to_iso_utc
        )
        SonicShiftUpgradeSummaryIncomplete_df["RawData"] = SonicShiftUpgradeSummaryIncomplete_df["RawData"].apply(
            _to_json_string
        )

    # 7. Ingest to Kusto. Endpoint/database/cluster defaults live in utilities.sonic_shift.
    if not SonicShiftUpgradeSummary_df.empty:
        # Completed upgrades → main summary table.
        ingest_hwproxy_rows_to_kusto(SonicShiftUpgradeSummary_df)
    if not SonicShiftUpgradeSummaryIncomplete_df.empty:
        # Still-incomplete upgrades → staging table, awaiting a future final state.
        ingest_incomplete_rows_to_staging(SonicShiftUpgradeSummaryIncomplete_df)

    logger.info(
        "Uploaded rows to main table: %s\n"
        "Uploaded rows to staging table: %s",
        len(SonicShiftUpgradeSummary_df), len(SonicShiftUpgradeSummaryIncomplete_df),
    )

    # 8. Promote resolved events: any main-path event whose final pair just arrived and
    #    that was previously staged as incomplete must be removed from the staging table.
    promoted_guids = []
    if not SonicShiftUpgradeSummary_df.empty:
        main_guids = SonicShiftUpgradeSummary_df["UpgradeGuid"].dropna().astype(str).tolist()
        promoted_guids = sorted(get_existing_staging_upgrade_guids(main_guids))
        if promoted_guids:
            delete_staging_rows_by_upgrade_guids(promoted_guids)
    logger.info("Promoted events removed from staging table: %s", len(promoted_guids))
    return 0


if __name__ == "__main__":
    # Root at WARNING hides noisy third-party logs; only our INFO summary lines show.
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    logger.setLevel(logging.INFO)
    raise SystemExit(main())
