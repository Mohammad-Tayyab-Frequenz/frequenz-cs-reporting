# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Async and persistent data access helpers for reporting datasets."""

from __future__ import annotations

import asyncio
import logging
import warnings
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import Lock
from time import monotonic
from typing import Any

import pandas as pd
from frequenz.client.common.metrics import Metric
from frequenz.lib.notebooks.reporting.asset_optimization import (
    data as asset_optimization_data,
)
from pandas.errors import PerformanceWarning

from frequenz.cs_reporting.services.battery_capacity import (
    fetch_battery_capacity_data_kwh,
)
from frequenz.cs_reporting.services.cache_config import CacheConfig, get_cache_config
from frequenz.cs_reporting.services.client_factory import (
    get_component_types,
    get_microgrid_client,
    get_microgrid_config,
    get_reporting_client,
)
from frequenz.cs_reporting.services.deepnote_cache import (
    start_background_deepnote_cache_persist,
)
from frequenz.cs_reporting.services.parquet_cache import (
    DatasetKey,
    ParquetRangeCache,
    SyncMetadata,
)
from frequenz.cs_reporting.utils.time import validate_range
from frequenz.cs_reporting.utils.timing import log_duration

_COMPONENT_DATA_LOGGER = "frequenz.data.microgrid.component_data"
_DAY_AHEAD_PRICE_RESOLUTION = timedelta(minutes=15)
_DAY_AHEAD_SYNC_RETRY_INTERVAL = 15 * 60
_ACTIVE_POWER_SYNC_RETRY_INTERVAL = 15 * 60
_BATTERY_SOC_SYNC_RETRY_INTERVAL = 15 * 60
_ACTIVE_POWER_SYNC_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="active-power-sync",
)
_ACTIVE_POWER_SYNC_LOCK = Lock()
_ACTIVE_POWER_SYNC_JOBS: dict[
    tuple[int, datetime, datetime, int], tuple[Future[pd.DataFrame], float]
] = {}
_BATTERY_SOC_SYNC_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="battery-soc-sync",
)
_BATTERY_SOC_SYNC_LOCK = Lock()
_BATTERY_SOC_SYNC_JOBS: dict[
    tuple[int, datetime, datetime, int], tuple[Future[pd.DataFrame], float]
] = {}
_DAY_AHEAD_SYNC_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="day-ahead-price-sync",
)
_DAY_AHEAD_SYNC_LOCK = Lock()
_DAY_AHEAD_SYNC_JOBS: dict[
    tuple[str, datetime, datetime], tuple[Future[pd.Series], float]
] = {}


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
        with log_duration("data.active_power.api_request"):
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
        with log_duration("data.battery_soc.api_request"):
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


async def fetch_microgrid_battery_capacity_data_kwh(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float = 30.0,
) -> pd.DataFrame:
    """Fetch time-varying battery capacity data in kWh from Reporting.

    Streamlit-side wrapper that resolves the battery components and Reporting
    client from the app configuration. Use
    ``battery_capacity.fetch_battery_capacity_data_kwh`` directly when those are
    already at hand, e.g. in a notebook.
    """
    start_iso, end_iso = validate_range(start_date, end_date)
    component_ids = get_microgrid_config(microgrid_id).component_type_ids(
        "battery", "component"
    )
    client = get_reporting_client()
    try:
        return await fetch_battery_capacity_data_kwh(
            client,
            microgrid_id,
            component_ids,
            start_iso,
            end_iso,
            resolution,
            timeout=timeout,
        )
    finally:
        await client.disconnect()


def get_microgrid_data(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float | None = None,
) -> pd.DataFrame:
    """Load active-power data through the persistent Parquet cache.

    Args:
        microgrid_id: Identifier for the target microgrid.
        start_date: Inclusive start date of the query range.
        end_date: Exclusive end date of the query range.
        resolution: Resampling period for the returned data.
        timeout: Request timeout in seconds. Uses configuration when omitted.

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
        config = get_cache_config()
        effective_timeout = timeout or float(config.request_timeout_seconds)
        cache = ParquetRangeCache(
            config.storage_path,
            sync_interval=timedelta(minutes=config.sync_interval_minutes),
            overlap=timedelta(minutes=config.sync_overlap_minutes),
        )
        with log_duration("data.active_power.cache_get"):
            return cache.get(
                _dataset_key("active_power", microgrid_id, resolution),
                start_date,
                end_date,
                lambda fetch_start, fetch_end: asyncio.run(
                    fetch_microgrid_data(
                        microgrid_id,
                        fetch_start,
                        fetch_end,
                        resolution,
                        timeout=effective_timeout,
                    )
                ),
            )
    # Active loop: force caller to use the async API
    raise RuntimeError(
        "get_microgrid_data() called from within an active event loop. "
        "Use `await fetch_microgrid_data(...)` in async contexts."
    )


def get_cached_microgrid_data(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
) -> tuple[pd.DataFrame, SyncMetadata]:
    """Read active-power data and metadata without external requests.

    Args:
        microgrid_id: Identifier for the target microgrid.
        start_date: Inclusive start of the requested range.
        end_date: Exclusive end of the requested range.
        resolution: Resolution of the cached dataset.

    Returns:
        Cached active-power data and the metadata read with it.
    """
    config = get_cache_config()
    cache = ParquetRangeCache(
        config.storage_path,
        sync_interval=timedelta(minutes=config.sync_interval_minutes),
        overlap=timedelta(minutes=config.sync_overlap_minutes),
    )
    with log_duration("data.active_power.cache_read"):
        return cache.read_with_metadata(
            _dataset_key("active_power", microgrid_id, resolution),
            start_date,
            end_date,
        )


def start_background_microgrid_data_sync(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
) -> Future[pd.DataFrame]:
    """Start one shared, non-blocking active-power cache synchronization."""
    sync_start, sync_end = _active_power_sync_range(start_date, end_date, resolution)
    key = (
        microgrid_id,
        sync_start,
        sync_end,
        int(resolution.total_seconds()),
    )
    now = monotonic()
    with _ACTIVE_POWER_SYNC_LOCK:
        existing = _ACTIVE_POWER_SYNC_JOBS.get(key)
        if existing is not None:
            future, started = existing
            if not future.done() or now - started < _ACTIVE_POWER_SYNC_RETRY_INTERVAL:
                return future

        future = _ACTIVE_POWER_SYNC_EXECUTOR.submit(
            get_microgrid_data,
            microgrid_id,
            sync_start,
            sync_end,
            resolution,
        )
        future.add_done_callback(_persist_cache_after_successful_sync)
        _ACTIVE_POWER_SYNC_JOBS[key] = (future, now)
        return future


def get_microgrid_soc_data(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float | None = None,
) -> pd.DataFrame:
    """Sync wrapper for battery SOC data with caching.

    Args:
        microgrid_id: Identifier for the target microgrid.
        start_date: Inclusive start date of the query range.
        end_date: Exclusive end date of the query range.
        resolution: Resampling period for the returned data.
        timeout: Request timeout in seconds. Uses configuration when omitted.

    Returns:
        Dataframe of battery SOC values. Empty when no SOC data is available.

    Raises:
        RuntimeError: If invoked from within an active event loop instead of
            using the async ``fetch_microgrid_soc_data``.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        config = get_cache_config()
        effective_timeout = timeout or float(config.request_timeout_seconds)
        cache = ParquetRangeCache(
            config.storage_path,
            sync_interval=timedelta(minutes=config.sync_interval_minutes),
            overlap=timedelta(minutes=config.sync_overlap_minutes),
        )
        with log_duration("data.battery_soc.cache_get"):
            return cache.get(
                _dataset_key("battery_soc", microgrid_id, resolution),
                start_date,
                end_date,
                lambda fetch_start, fetch_end: asyncio.run(
                    fetch_microgrid_soc_data(
                        microgrid_id,
                        fetch_start,
                        fetch_end,
                        resolution,
                        timeout=effective_timeout,
                    )
                ),
            )
    raise RuntimeError(
        "get_microgrid_soc_data() called from within an active event loop. "
        "Use `await fetch_microgrid_soc_data(...)` in async contexts."
    )


def get_cached_microgrid_soc_data(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
) -> pd.DataFrame:
    """Read battery SOC data from the cache without an external request."""
    config = get_cache_config()
    cache = ParquetRangeCache(
        config.storage_path,
        sync_interval=timedelta(minutes=config.sync_interval_minutes),
        overlap=timedelta(minutes=config.sync_overlap_minutes),
    )
    with log_duration("data.battery_soc.cache_read"):
        return cache.read(
            _dataset_key("battery_soc", microgrid_id, resolution),
            start_date,
            end_date,
        )


def start_background_microgrid_soc_data_sync(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
) -> Future[pd.DataFrame]:
    """Start one shared, non-blocking battery-SOC cache synchronization."""
    sync_start, sync_end = _active_power_sync_range(start_date, end_date, resolution)
    key = (
        microgrid_id,
        sync_start,
        sync_end,
        int(resolution.total_seconds()),
    )
    now = monotonic()
    with _BATTERY_SOC_SYNC_LOCK:
        existing = _BATTERY_SOC_SYNC_JOBS.get(key)
        if existing is not None:
            future, started = existing
            if not future.done() or now - started < _BATTERY_SOC_SYNC_RETRY_INTERVAL:
                return future

        future = _BATTERY_SOC_SYNC_EXECUTOR.submit(
            get_microgrid_soc_data,
            microgrid_id,
            sync_start,
            sync_end,
            resolution,
        )
        future.add_done_callback(_persist_cache_after_successful_sync)
        _BATTERY_SOC_SYNC_JOBS[key] = (future, now)
        return future


def _dataset_key(name: str, microgrid_id: int, resolution: timedelta) -> DatasetKey:
    """Build the stable storage key for a reporting dataset."""
    seconds = int(resolution.total_seconds())
    if seconds <= 0:
        raise ValueError("resolution must be greater than zero")
    return DatasetKey(name, microgrid_id, seconds)


def _active_power_sync_range(
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
) -> tuple[datetime, datetime]:
    """Normalize an active-power job range to stable resolution boundaries."""
    resolution_seconds = int(resolution.total_seconds())
    if resolution_seconds <= 0:
        raise ValueError("resolution must be greater than zero")
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    frequency = f"{resolution_seconds}s"
    normalized_start = start.floor(frequency)
    normalized_end = end.floor(frequency)
    if normalized_end <= normalized_start:
        normalized_end = end
    return normalized_start.to_pydatetime(), normalized_end.to_pydatetime()


def get_dataset_sync_metadata(
    name: str, microgrid_id: int, resolution: timedelta
) -> SyncMetadata:
    """Return persisted freshness information for a reporting dataset."""
    config = get_cache_config()
    cache = ParquetRangeCache(
        config.storage_path,
        sync_interval=timedelta(minutes=config.sync_interval_minutes),
        overlap=timedelta(minutes=config.sync_overlap_minutes),
    )
    return cache.metadata(_dataset_key(name, microgrid_id, resolution))


def get_day_ahead_prices(
    country_code: str,
    start_date: datetime,
    end_date: datetime,
) -> pd.Series:
    """Load ENTSO-E day-ahead prices through the persistent range cache.

    Args:
        country_code: ENTSO-E bidding-zone country code.
        start_date: Inclusive beginning of the required price range.
        end_date: Exclusive end of the required price range.

    Returns:
        Day-ahead prices indexed by UTC timestamp.
    """
    config = get_cache_config()
    cache = _day_ahead_price_cache(config)

    def fetch(fetch_start: datetime, fetch_end: datetime) -> pd.DataFrame:
        with log_duration("data.day_ahead_prices.api_request"):
            prices = asset_optimization_data.fetch_day_ahead_prices(  # type: ignore[attr-defined]
                entsoe_key=None,
                start=fetch_start,
                end=fetch_end,
                country_code=country_code,
            )
        return prices.rename("day_ahead_price").to_frame()

    with log_duration("data.day_ahead_prices.cache_get"):
        frame = cache.get(
            _day_ahead_price_key(country_code),
            start_date,
            end_date,
            fetch,
        )
    if "day_ahead_price" not in frame.columns:
        return pd.Series(dtype="float64", name="day_ahead_price")
    return frame["day_ahead_price"].rename("day_ahead_price")


def get_cached_day_ahead_prices(
    country_code: str,
    start_date: datetime,
    end_date: datetime,
) -> pd.Series:
    """Read day-ahead prices from local storage without external requests.

    Args:
        country_code: ENTSO-E bidding-zone country code.
        start_date: Inclusive beginning of the required price range.
        end_date: Exclusive end of the required price range.

    Returns:
        Cached 15-minute prices indexed by UTC timestamp, or an empty series
        when the scheduled synchronization has not populated this range.
    """
    config = get_cache_config()
    cache = _day_ahead_price_cache(config)
    with log_duration("data.day_ahead_prices.cache_read"):
        frame = cache.read(
            _day_ahead_price_key(country_code),
            start_date,
            end_date,
        )
    if "day_ahead_price" not in frame.columns:
        return pd.Series(dtype="float64", name="day_ahead_price")
    return frame["day_ahead_price"].rename("day_ahead_price")


def start_background_day_ahead_price_sync(
    country_code: str,
    start_date: datetime,
    end_date: datetime,
) -> Future[pd.Series]:
    """Start one non-blocking price synchronization for a normalized date range.

    Concurrent Streamlit sessions share the same in-process job. Failed or
    empty synchronizations are held for a short cooldown to avoid retry loops
    on every rerun.

    Args:
        country_code: ENTSO-E bidding-zone country code.
        start_date: Inclusive beginning of the required price range.
        end_date: Exclusive end of the required price range.

    Returns:
        Future representing the background synchronization.
    """
    sync_start, sync_end = _day_ahead_sync_range(start_date, end_date)
    key = (country_code, sync_start, sync_end)
    now = monotonic()
    with _DAY_AHEAD_SYNC_LOCK:
        existing = _DAY_AHEAD_SYNC_JOBS.get(key)
        if existing is not None:
            future, started = existing
            if not future.done() or now - started < _DAY_AHEAD_SYNC_RETRY_INTERVAL:
                return future

        future = _DAY_AHEAD_SYNC_EXECUTOR.submit(
            get_day_ahead_prices,
            country_code,
            sync_start,
            sync_end,
        )
        future.add_done_callback(_persist_cache_after_successful_sync)
        _DAY_AHEAD_SYNC_JOBS[key] = (future, now)
        return future


def _persist_cache_after_successful_sync(future: Future[Any]) -> None:
    """Queue Deepnote persistence after a successful background sync."""
    if future.cancelled() or future.exception() is not None:
        return
    start_background_deepnote_cache_persist()


def _day_ahead_sync_range(
    start_date: datetime,
    end_date: datetime,
    *,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Normalize a price synchronization range without requesting future data."""
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")

    current = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")

    frequency = f"{int(_DAY_AHEAD_PRICE_RESOLUTION.total_seconds())}s"
    normalized_start = start.floor(frequency)
    normalized_end = min(
        end.ceil(frequency),
        current.floor(frequency),
    )
    if normalized_end <= normalized_start:
        normalized_end = min(end, current)
    if normalized_end <= normalized_start:
        raise ValueError("The day-ahead price range end must be after its start")
    return normalized_start.to_pydatetime(), normalized_end.to_pydatetime()


def _day_ahead_price_key(country_code: str) -> DatasetKey:
    """Return the cache key for a 15-minute day-ahead price dataset."""
    return DatasetKey(
        f"day_ahead_prices_{country_code}",
        0,
        int(_DAY_AHEAD_PRICE_RESOLUTION.total_seconds()),
    )


def _day_ahead_price_cache(config: CacheConfig) -> ParquetRangeCache:
    """Build the persistent cache used by scheduled price synchronization."""
    return ParquetRangeCache(
        config.storage_path,
        sync_interval=timedelta(minutes=config.sync_interval_minutes),
        overlap=max(timedelta(minutes=config.sync_overlap_minutes), timedelta(hours=2)),
    )


def get_battery_capacity_kwh(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float | None = None,
) -> float | None:
    """Sync wrapper for Reporting API battery capacity data in kWh."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        config = get_cache_config()
        effective_timeout = timeout or float(config.request_timeout_seconds)
        return asyncio.run(
            fetch_microgrid_battery_capacity_kwh(
                microgrid_id,
                start_date,
                end_date,
                resolution,
                timeout=effective_timeout,
            )
        )
    raise RuntimeError(
        "get_battery_capacity_kwh() called from within an active event loop. "
        "Use `await fetch_microgrid_battery_capacity_kwh(...)` in async contexts."
    )


def get_battery_capacity_data_kwh(
    microgrid_id: int,
    start_date: datetime,
    end_date: datetime,
    resolution: timedelta,
    timeout: float | None = None,
) -> pd.DataFrame:
    """Sync wrapper for time-varying Reporting API battery capacity data."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        config = get_cache_config()
        effective_timeout = timeout or float(config.request_timeout_seconds)
        return asyncio.run(
            fetch_microgrid_battery_capacity_data_kwh(
                microgrid_id,
                start_date,
                end_date,
                resolution,
                timeout=effective_timeout,
            )
        )
    raise RuntimeError(
        "get_battery_capacity_data_kwh() called from an active event loop."
    )
