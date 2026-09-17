# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Async and cached data access helpers for microgrid measurements."""

from __future__ import annotations

import asyncio
import logging
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from pandas.errors import PerformanceWarning
from frequenz.client.common.metrics import Metric

from frequenz.cs_reporting.services.client_factory import (
    get_component_types,
    get_microgrid_client,
    get_microgrid_config,
    get_reporting_client,
)
from frequenz.cs_reporting.utils.time import validate_range

_COMPONENT_DATA_LOGGER = "frequenz.data.microgrid.component_data"


class _MissingComponentFilter(logging.Filter):
    """Filter expected missing-component warnings from the data client."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Return whether a log record should be emitted."""
        if record.name != _COMPONENT_DATA_LOGGER:
            return True
        message = record.getMessage()
        return not (
            message.startswith("Component ID ")
            and message.endswith(" not found in data, setting zero")
        )


@contextmanager
def _quiet_expected_component_data_warnings() -> Iterator[None]:
    """Suppress expected noisy warnings emitted while building component data."""
    logger = logging.getLogger(_COMPONENT_DATA_LOGGER)
    component_filter = _MissingComponentFilter()
    logger.addFilter(component_filter)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                category=PerformanceWarning,
                message="DataFrame is highly fragmented.*",
                module=r"frequenz\.data\.microgrid\.component_data",
            )
            yield
    finally:
        logger.removeFilter(component_filter)


async def fetch_microgrid_data(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float = 30.0,
) -> pd.DataFrame:
    """Fetch AC active power for a microgrid in ``[start_date, end_date)``.

    Args:
        microgrid_id: Identifier for the target microgrid.
        start_date: Inclusive start date of the query range.
        end_date: Exclusive end date of the query range.
        resolution: Resampling period for the returned data.
        timeout: Request timeout in seconds.

    Returns:
        Dataframe of AC active power measurements. Empty when no
            data is available.
    """
    start_iso, end_iso = validate_range(start_date, end_date)
    client = get_microgrid_client(microgrid_id)
    component_types: tuple[str, ...] = get_component_types(microgrid_id)

    coro = client.ac_active_power(
        microgrid_id=microgrid_id,
        component_types=component_types,
        start=start_iso,
        end=end_iso,
        resampling_period=resolution,
        keep_components=True,
        splits=True,
    )
    with _quiet_expected_component_data_warnings():
        df = await asyncio.wait_for(coro, timeout)

    if df is None or (hasattr(df, "empty") and df.empty):
        return pd.DataFrame()
    return df.copy()


async def fetch_microgrid_soc_data(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float = 30.0,
) -> pd.DataFrame:
    """Fetch battery SOC for a microgrid in ``[start_date, end_date)``.

    Args:
        microgrid_id: Identifier for the target microgrid.
        start_date: Inclusive start date of the query range.
        end_date: Exclusive end date of the query range.
        resolution: Resampling period for the returned data.
        timeout: Request timeout in seconds.

    Returns:
        Dataframe of battery SOC values. Empty when no SOC data is available.
    """
    start_iso, end_iso = validate_range(start_date, end_date)
    client = get_microgrid_client(microgrid_id)

    coro = client.soc(
        microgrid_id=microgrid_id,
        start=start_iso,
        end=end_iso,
        resampling_period=resolution,
        keep_components=False,
    )
    with _quiet_expected_component_data_warnings():
        df = await asyncio.wait_for(coro, timeout)

    if df is None or (hasattr(df, "empty") and df.empty):
        return pd.DataFrame()
    return df.copy()


def _battery_capacity_kwh_from_metric_data(df: pd.DataFrame) -> float | None:
    """Return the latest valid capacity for each battery component in kWh.

    The Reporting API reports ``METRIC_BATTERY_CAPACITY`` in Wh.  Capacity is a
    point-in-time metric, so repeated readings must not be summed.  Individual
    battery capacities are summed to obtain the microgrid capacity.
    """
    numeric_capacity_data = df.apply(
        lambda column: pd.to_numeric(column, errors="coerce")
    )
    capacity_values_wh = pd.Series(
        numeric_capacity_data.ffill().tail(1).to_numpy().ravel()
    ).dropna()
    if capacity_values_wh.empty:
        return None

    capacity_kwh = float(capacity_values_wh.sum()) / 1000.0
    return capacity_kwh if capacity_kwh > 0 else None


async def fetch_microgrid_battery_capacity_kwh(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float = 30.0,
) -> float | None:
    """Fetch battery capacity from the Reporting API's battery capacity metric."""
    start_iso, end_iso = validate_range(start_date, end_date)
    component_ids = get_microgrid_config(microgrid_id).component_type_ids(
        "battery",
        "component",
    )
    if not component_ids:
        return None

    client = get_reporting_client()
    try:
        receiver = client.receive_microgrid_components_data(
            microgrid_components=[(microgrid_id, component_ids)],
            metrics=Metric.BATTERY_CAPACITY,
            start_time=start_iso,
            end_time=end_iso,
            resampling_period=resolution,
        )
        with _quiet_expected_component_data_warnings():
            async with asyncio.timeout(timeout):
                samples = [sample async for sample in receiver]
    finally:
        await client.disconnect()

    if not samples:
        return None
    data = pd.DataFrame(samples)
    capacity_data = data[data["metric"] == Metric.BATTERY_CAPACITY.name]
    if capacity_data.empty:
        capacity_data = data[data["metric"] == f"{Metric.BATTERY_CAPACITY.name}_avg"]
    if capacity_data.empty:
        return None
    capacity_data = capacity_data.pivot_table(
        index="timestamp",
        columns="component_id",
        values="value",
        aggfunc="last",
    )
    return _battery_capacity_kwh_from_metric_data(capacity_data)


# Cached sync wrapper for Streamlit pages
@st.cache_data(ttl=300, show_spinner=False)
def get_microgrid_data(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float = 30.0,
) -> pd.DataFrame:
    """Sync wrapper for Streamlit pages with caching (5 min TTL).

    Args:
        microgrid_id: Identifier for the target microgrid.
        start_date: Inclusive start date of the query range.
        end_date: Exclusive end date of the query range.
        resolution: Resampling period for the returned data.
        timeout: Request timeout in seconds.

    Returns:
        Dataframe of AC active power measurements. Empty when no
            data is available.

    Raises:
        RuntimeError: If invoked from within an active event loop instead of
            using the async ``fetch_microgrid_data``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No active loop: safe to block
        return asyncio.run(
            fetch_microgrid_data(
                microgrid_id, start_date, end_date, resolution, timeout=timeout
            )
        )
    # Active loop: force caller to use the async API
    raise RuntimeError(
        "get_microgrid_data() called from within an active event loop. "
        "Use `await fetch_microgrid_data(...)` in async contexts."
    )


@st.cache_data(ttl=300, show_spinner=False)
def get_microgrid_soc_data(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float = 30.0,
) -> pd.DataFrame:
    """Sync wrapper for battery SOC data with caching.

    Args:
        microgrid_id: Identifier for the target microgrid.
        start_date: Inclusive start date of the query range.
        end_date: Exclusive end date of the query range.
        resolution: Resampling period for the returned data.
        timeout: Request timeout in seconds.

    Returns:
        Dataframe of battery SOC values. Empty when no SOC data is available.

    Raises:
        RuntimeError: If invoked from within an active event loop instead of
            using the async ``fetch_microgrid_soc_data``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            fetch_microgrid_soc_data(
                microgrid_id, start_date, end_date, resolution, timeout=timeout
            )
        )
    raise RuntimeError(
        "get_microgrid_soc_data() called from within an active event loop. "
        "Use `await fetch_microgrid_soc_data(...)` in async contexts."
    )


@st.cache_data(ttl=300, show_spinner=False)
def get_battery_capacity_kwh(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float = 30.0,
) -> float | None:
    """Sync wrapper for Reporting API battery capacity data in kWh."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            fetch_microgrid_battery_capacity_kwh(
                microgrid_id,
                start_date,
                end_date,
                resolution,
                timeout=timeout,
            )
        )
    raise RuntimeError(
        "get_battery_capacity_kwh() called from within an active event loop. "
        "Use `await fetch_microgrid_battery_capacity_kwh(...)` in async contexts."
    )
