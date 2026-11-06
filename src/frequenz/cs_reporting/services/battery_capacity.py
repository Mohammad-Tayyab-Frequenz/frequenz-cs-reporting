# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Battery capacity retrieval from the Reporting API.

This module has no Streamlit or config-loading dependencies, so it can be awaited
from any context, including notebooks that already run an event loop.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pandas as pd
from frequenz.client.common.metrics import Metric
from frequenz.client.reporting import ReportingApiClient

_EMPTY_COLUMNS = ["timestamp", "battery_capacity_kwh"]


def battery_capacity_kwh_time_series_from_metric_data(
    df: pd.DataFrame,
) -> pd.DataFrame:
    """Convert Reporting API component capacity samples from Wh to kWh."""
    numeric_data = pd.DataFrame(
        {column: pd.to_numeric(df[column], errors="coerce") for column in df.columns},
        index=df.index,
    )
    capacity_kwh = numeric_data.ffill().sum(axis="columns", min_count=1) / 1000.0
    return (
        capacity_kwh.rename("battery_capacity_kwh")
        .reset_index()
        .rename(columns={"index": "timestamp"})
    )


# pylint: disable=too-many-arguments,too-many-positional-arguments
async def fetch_battery_capacity_data_kwh(
    client: ReportingApiClient,
    microgrid_id: int,
    component_ids: list[int],
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float = 30.0,
) -> pd.DataFrame:
    """Fetch time-varying total battery capacity in kWh from the Reporting API.

    The caller owns ``client`` and is responsible for disconnecting it.

    Args:
        client: Connected Reporting API client.
        microgrid_id: Identifier for the target microgrid.
        component_ids: Battery component IDs whose capacities are summed.
        start_date: Inclusive start of the query range.
        end_date: Exclusive end of the query range.
        resolution: Resampling period for the returned data.
        timeout: Request timeout in seconds.

    Returns:
        Dataframe with ``timestamp`` and ``battery_capacity_kwh`` columns. Empty
            when no capacity data is available.
    """
    empty = pd.DataFrame(columns=_EMPTY_COLUMNS)
    if not component_ids:
        return empty
    receiver = client.receive_microgrid_components_data(
        microgrid_components=[(int(microgrid_id), list(component_ids))],
        metrics=[Metric.BATTERY_CAPACITY],
        start_time=start_date,
        end_time=end_date,
        resampling_period=resolution,
    )
    async with asyncio.timeout(timeout):
        samples = [sample async for sample in receiver]
    if not samples:
        return empty
    data = pd.DataFrame(samples)
    metric_name = Metric.BATTERY_CAPACITY.name
    metric_names = data["metric"].astype(str)
    capacity_data = data[
        metric_names.eq(metric_name)
        | metric_names.eq(f"{metric_name}_avg")
        | metric_names.str.startswith(f"{metric_name}_raw_")
    ]
    if capacity_data.empty:
        return empty
    pivoted = capacity_data.pivot_table(
        index="timestamp", columns="component_id", values="value", aggfunc="last"
    )
    return battery_capacity_kwh_time_series_from_metric_data(pivoted)
