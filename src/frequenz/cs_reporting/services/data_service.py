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

import pandas as pd
from frequenz.lib.notebooks.reporting.asset_optimization import (
    data as asset_optimization_data,
)
from pandas.errors import PerformanceWarning

from frequenz.cs_reporting.services.cache_config import CacheConfig, get_cache_config
from frequenz.cs_reporting.services.client_factory import (
    get_component_types,
    get_microgrid_client,
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
_ACTIVE_POWER_SYNC_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="active-power-sync",
)
_ACTIVE_POWER_SYNC_LOCK = Lock()
_ACTIVE_POWER_SYNC_JOBS: dict[
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
    return start.floor(frequency).to_pydatetime(), end.ceil(frequency).to_pydatetime()


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
        _DAY_AHEAD_SYNC_JOBS[key] = (future, now)
        return future


def _day_ahead_sync_range(
    start_date: datetime, end_date: datetime
) -> tuple[datetime, datetime]:
    """Normalize a price synchronization range to stable UTC day boundaries."""
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
    normalized_start = start.normalize().to_pydatetime()
    normalized_end = (end.normalize() + timedelta(days=1)).to_pydatetime()
    return normalized_start, normalized_end


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
