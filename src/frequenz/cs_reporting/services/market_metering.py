# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Fetch, normalize, and merge DSO Market Metering data."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from frequenz.client.marketmetering import MarketMeteringApiClient
from frequenz.client.marketmetering.types import (
    EnergyFlowDirection,
    MarketArea,
    MarketLocationId,
    MarketLocationIdType,
    MarketLocationRef,
    MetricType,
)

from frequenz.cs_reporting.services.client_factory import (
    get_market_location_ids,
    get_market_metering_client,
)
from frequenz.cs_reporting.utils.time import validate_range

_NATIVE_RESOLUTION = timedelta(minutes=15)
DSO_ENERGY_COLUMNS = ("dso_import_energy", "dso_export_energy")


def _empty_energy_frame() -> pd.DataFrame:
    """Return an empty dataframe with the stable DSO energy schema."""
    return pd.DataFrame(columns=["timestamp", *DSO_ENERGY_COLUMNS])


def _market_location_refs(
    market_location_ids: tuple[str, ...],
) -> list[MarketLocationRef]:
    """Build German MaLo references for a Market Metering request."""
    return [
        MarketLocationRef(
            market_area=MarketArea.EU_DE,
            market_location_id=MarketLocationId(
                value=market_location_id,
                type=MarketLocationIdType.MALO_ID,
            ),
        )
        for market_location_id in market_location_ids
    ]


async def _stream_records(
    client: MarketMeteringApiClient,
    market_locations: list[MarketLocationRef],
    start_time: datetime,
    end_time: datetime,
    timeout: float,
) -> list[dict[str, Any]]:
    """Collect import and export samples from the bounded API stream."""
    records: list[dict[str, Any]] = []
    async with asyncio.timeout(timeout):
        async for series in client.stream_samples(
            market_locations=market_locations,
            directions=[
                EnergyFlowDirection.IMPORT,
                EnergyFlowDirection.EXPORT,
            ],
            metric_types=[MetricType.ACTIVE_ENERGY],
            start_time=start_time,
            end_time=end_time,
        ):
            records.extend(
                {
                    "timestamp": sample.sample_time,
                    "dso_energy": sample.value,
                    "direction": series.direction.name.lower(),
                    "revision": sample.revision,
                    "market_location_id": (
                        series.market_location_ref.market_location_id.value
                    ),
                }
                for sample in series.samples
            )
    return records


def _aggregate_records(
    records: list[dict[str, Any]], resolution: timedelta
) -> pd.DataFrame:
    """Select latest revisions and aggregate MaLos by timestamp and direction."""
    resolution_seconds = int(resolution.total_seconds())
    if resolution_seconds <= 0:
        raise ValueError("resolution must be greater than zero")
    if not records:
        return _empty_energy_frame()

    frame = pd.DataFrame.from_records(records)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("revision").drop_duplicates(
        subset=["timestamp", "market_location_id", "direction"],
        keep="last",
    )
    summed = frame.groupby(["timestamp", "direction"])["dso_energy"].sum(min_count=1)
    directional = summed.unstack("direction").rename(
        columns={
            "import": "dso_import_energy",
            "export": "dso_export_energy",
        }
    )
    directional = directional.reindex(columns=DSO_ENERGY_COLUMNS)
    if resolution != _NATIVE_RESOLUTION:
        directional = directional.resample(f"{resolution_seconds}s").sum(min_count=1)
    return directional.reset_index()


async def fetch_market_metering_data(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float = 300.0,
) -> pd.DataFrame:
    """Fetch aggregated DSO import and export energy for a microgrid."""
    start_date, end_date = validate_range(start_date, end_date)
    market_location_ids = get_market_location_ids(microgrid_id)
    if not market_location_ids:
        return _empty_energy_frame()

    client = get_market_metering_client(timeout)
    try:
        records = await _stream_records(
            client,
            _market_location_refs(market_location_ids),
            start_date,
            end_date,
            timeout,
        )
    finally:
        await client.disconnect()
    return _aggregate_records(records, resolution)


def merge_dso_energy(
    master_df: pd.DataFrame,
    dso_energy_df: pd.DataFrame | None,
    resolution: timedelta,
) -> pd.DataFrame:
    """Merge DSO interval energy into a report dataframe as average power."""
    interval_hours = resolution.total_seconds() / 3600
    if interval_hours <= 0:
        raise ValueError("resolution must be greater than zero")
    if dso_energy_df is None or dso_energy_df.empty:
        return master_df.copy()
    if "timestamp" not in dso_energy_df:
        return master_df.copy()

    energy_columns = [
        column for column in DSO_ENERGY_COLUMNS if column in dso_energy_df.columns
    ]
    if not energy_columns:
        return master_df.copy()

    dso = dso_energy_df.loc[:, ["timestamp", *energy_columns]].copy()
    dso["_timestamp_utc"] = pd.to_datetime(dso["timestamp"], utc=True, errors="coerce")
    for column in energy_columns:
        dso[column] = pd.to_numeric(dso[column], errors="coerce")
    values = (
        dso.dropna(subset=["_timestamp_utc"])
        .drop_duplicates(subset=["_timestamp_utc"], keep="last")
        .set_index("_timestamp_utc")[energy_columns]
    )

    merged = master_df.copy()
    master_timestamps = pd.to_datetime(merged["timestamp"], utc=True, errors="coerce")
    for energy_column in energy_columns:
        power_column = energy_column.replace("_energy", "_power")
        merged[power_column] = (
            master_timestamps.map(values[energy_column]) / interval_hours
        )
    return merged
