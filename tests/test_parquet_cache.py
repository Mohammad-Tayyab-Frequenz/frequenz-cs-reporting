# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for persistent Parquet synchronization."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from frequenz.cs_reporting.services import data_service
from frequenz.cs_reporting.services.parquet_cache import (
    DatasetKey,
    ParquetRangeCache,
    SyncMetadata,
)


def _frame(start: datetime, end: datetime, value: float = 1.0) -> pd.DataFrame:
    index = pd.date_range(start, end, freq="15min", inclusive="left")
    return pd.DataFrame({"power": value}, index=index)


def _cache(root: Path, *, due: bool = False) -> ParquetRangeCache:
    return ParquetRangeCache(
        root / "parquet",
        sync_interval=timedelta(0) if due else timedelta(minutes=15),
        overlap=timedelta(minutes=15),
        retry_attempts=1,
    )


def test_initial_sync_and_restart_use_existing_parquet(tmp_path: Path) -> None:
    """A restart reads the persisted file without a second API request."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    calls: list[tuple[datetime, datetime]] = []

    def fetch(fetch_start: datetime, fetch_end: datetime) -> pd.DataFrame:
        calls.append((fetch_start, fetch_end))
        return _frame(fetch_start, fetch_end)

    key = DatasetKey("active_power", 42, 900)
    first = _cache(tmp_path).get(key, start, end, fetch)
    restarted = _cache(tmp_path).get(key, start, end, fetch)

    assert len(first) == 4
    pd.testing.assert_frame_equal(restarted, first, check_freq=False)
    assert calls == [(start, end)]


def test_read_with_metadata_uses_one_metadata_snapshot(tmp_path: Path) -> None:
    """A cache-only read returns its dataframe and matching metadata together."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    key = DatasetKey("active_power", 42, 900)
    cache = _cache(tmp_path)
    expected = cache.get(key, start, end, _frame)

    actual, metadata = cache.read_with_metadata(key, start, end)

    pd.testing.assert_frame_equal(actual, expected, check_freq=False)
    assert metadata.status == "ok"
    assert metadata.dataset == key.slug


def test_sync_writes_metadata_only_once_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synchronization does not persist an intermediate syncing state."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    key = DatasetKey("active_power", 42, 900)
    cache = _cache(tmp_path)
    writes = 0
    original_write = cache._write_metadata  # pylint: disable=protected-access

    def count_write(dataset_key: DatasetKey, metadata: SyncMetadata) -> None:
        nonlocal writes
        writes += 1
        original_write(dataset_key, metadata)

    monkeypatch.setattr(cache, "_write_metadata", count_write)

    cache.get(key, start, end, _frame)

    assert writes == 1


def test_temporary_cache_does_not_fsync_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ephemeral cache metadata avoids unnecessary durability synchronization."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)

    def unexpected_fsync(_descriptor: int) -> None:
        pytest.fail("fsync should not be used for an ephemeral cache")

    monkeypatch.setattr(
        "frequenz.cs_reporting.services.parquet_cache.os.fsync", unexpected_fsync
    )

    result = _cache(tmp_path).get(
        DatasetKey("active_power", 42, 900), start, end, _frame
    )

    assert not result.empty


def test_extension_fetches_only_missing_range(tmp_path: Path) -> None:
    """Extending a covered request fetches only its uncovered tail."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    middle = start + timedelta(hours=1)
    end = middle + timedelta(hours=1)
    calls: list[tuple[datetime, datetime]] = []

    def fetch(fetch_start: datetime, fetch_end: datetime) -> pd.DataFrame:
        calls.append((fetch_start, fetch_end))
        return _frame(fetch_start, fetch_end)

    cache = _cache(tmp_path)
    key = DatasetKey("active_power", 42, 900)
    cache.get(key, start, middle, fetch)
    result = cache.get(key, start, end, fetch)

    assert len(result) == 8
    assert calls == [(start, middle), (middle, end)]


def test_small_live_tail_does_not_fetch_again_before_interval(tmp_path: Path) -> None:
    """A moving current-time endpoint does not cause API calls on every rerun."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    calls: list[tuple[datetime, datetime]] = []

    def fetch(fetch_start: datetime, fetch_end: datetime) -> pd.DataFrame:
        calls.append((fetch_start, fetch_end))
        return _frame(fetch_start, fetch_end)

    cache = _cache(tmp_path)
    key = DatasetKey("active_power", 42, 900)
    cache.get(key, start, end, fetch)
    cache.get(key, start, end + timedelta(minutes=1), fetch)

    assert calls == [(start, end)]


def test_overlap_refresh_updates_existing_timestamp(tmp_path: Path) -> None:
    """A due overlap refresh replaces rows using their timestamp key."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    key = DatasetKey("active_power", 42, 900)
    cache = _cache(tmp_path, due=True)

    cache.get(key, start, end, _frame)
    result = cache.get(
        key,
        start,
        end,
        lambda fetch_start, fetch_end: _frame(fetch_start, fetch_end, value=9.0),
    )

    assert result.iloc[:-1]["power"].eq(1.0).all()
    assert result.iloc[-1]["power"] == 9.0
    assert result.index.is_unique


def test_failed_refresh_preserves_and_serves_previous_file(tmp_path: Path) -> None:
    """A transient refresh failure leaves the valid Parquet file untouched."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    key = DatasetKey("active_power", 42, 900)
    cache = _cache(tmp_path, due=True)
    expected = cache.get(key, start, end, _frame)
    parquet_path = tmp_path / "parquet" / f"{key.slug}.parquet"
    contents_before = parquet_path.read_bytes()

    def fail(_start: datetime, _end: datetime) -> pd.DataFrame:
        raise TimeoutError("temporary outage")

    actual = cache.get(key, start, end, fail)

    pd.testing.assert_frame_equal(actual, expected, check_freq=False)
    assert parquet_path.read_bytes() == contents_before
    metadata = cache.metadata(key)
    assert metadata.status == "error"
    assert "temporary outage" in (metadata.last_error or "")


def test_failed_initial_sync_does_not_create_parquet(tmp_path: Path) -> None:
    """An interrupted initial request never publishes a partial dataset."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    key = DatasetKey("active_power", 42, 900)

    def fail(_start: datetime, _end: datetime) -> pd.DataFrame:
        raise OSError("offline")

    with pytest.raises(OSError, match="offline"):
        _cache(tmp_path).get(key, start, end, fail)

    assert not (tmp_path / "parquet" / f"{key.slug}.parquet").exists()


def test_empty_response_is_recorded_as_a_successful_covered_range(
    tmp_path: Path,
) -> None:
    """A legitimate empty API response is distinct from a failed request."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    calls = 0

    def fetch(_start: datetime, _end: datetime) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return pd.DataFrame()

    cache = _cache(tmp_path)
    key = DatasetKey("active_power", 42, 900)
    assert cache.get(key, start, end, fetch).empty
    assert cache.get(key, start, end, fetch).empty
    assert calls == 1
    assert cache.metadata(key).status == "ok"


def test_timestamp_column_shape_is_preserved(tmp_path: Path) -> None:
    """A source timestamp column remains a column after a cache round trip."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    key = DatasetKey("active_power", 42, 900)

    def fetch(fetch_start: datetime, fetch_end: datetime) -> pd.DataFrame:
        return _frame(fetch_start, fetch_end).rename_axis("timestamp").reset_index()

    result = _cache(tmp_path).get(key, start, end, fetch)

    assert isinstance(result.index, pd.RangeIndex)
    assert list(result.columns) == ["timestamp", "power"]
    assert str(result["timestamp"].dtype) == "datetime64[ns, UTC]"


def test_api_boundary_buckets_are_discarded(tmp_path: Path) -> None:
    """Expected resampling buckets outside ``[start, end)`` do not fail sync."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    key = DatasetKey("active_power", 42, 900)

    def fetch(_fetch_start: datetime, _fetch_end: datetime) -> pd.DataFrame:
        index = pd.DatetimeIndex(
            [
                start - timedelta(minutes=15),
                start,
                start + timedelta(minutes=15),
                end,
            ]
        )
        return pd.DataFrame({"power": [0.0, 1.0, 2.0, 3.0]}, index=index)

    result = _cache(tmp_path).get(key, start, end, fetch)

    assert result.index.tolist() == [start, start + timedelta(minutes=15)]
    assert result["power"].tolist() == [1.0, 2.0]


def test_extra_distant_rows_are_discarded_when_response_overlaps(
    tmp_path: Path,
) -> None:
    """Relevant rows are retained even if the API includes a much wider range."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    key = DatasetKey("active_power", 42, 900)

    def fetch(_fetch_start: datetime, _fetch_end: datetime) -> pd.DataFrame:
        return pd.DataFrame(
            {"power": [0.0, 1.0, 2.0]},
            index=pd.DatetimeIndex(
                [start - timedelta(days=1), start, end + timedelta(days=1)]
            ),
        )

    result = _cache(tmp_path).get(key, start, end, fetch)

    assert result.index.tolist() == [start]
    assert result["power"].tolist() == [1.0]


def test_timestamps_without_request_overlap_still_fail_validation(
    tmp_path: Path,
) -> None:
    """Unrelated response timestamps cannot replace a valid cache dataset."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    key = DatasetKey("active_power", 42, 900)

    def fetch(_fetch_start: datetime, _fetch_end: datetime) -> pd.DataFrame:
        return pd.DataFrame(
            {"power": [1.0]},
            index=pd.DatetimeIndex([end + timedelta(hours=1)]),
        )

    with pytest.raises(ValueError, match="does not overlap the requested time range"):
        _cache(tmp_path).get(key, start, end, fetch)


def test_mixed_column_label_types_survive_restart(tmp_path: Path) -> None:
    """Integer component IDs and formula names keep their distinct types."""
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    key = DatasetKey("active_power", 42, 900)

    def fetch(fetch_start: datetime, fetch_end: datetime) -> pd.DataFrame:
        index = pd.date_range(fetch_start, fetch_end, freq="15min", inclusive="left")
        return pd.DataFrame({1: 1.0, "1": 2.0, "pv": 3.0}, index=index)

    cache = _cache(tmp_path)
    expected = cache.get(key, start, end, fetch)
    actual = _cache(tmp_path).get(
        key,
        start,
        end,
        lambda _start, _end: pytest.fail("cache should satisfy the request"),
    )

    assert list(actual.columns) == [1, "1", "pv"]
    pd.testing.assert_frame_equal(actual, expected, check_freq=False)


def test_day_ahead_subset_reuses_persistent_price_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing to a smaller date range does not call ENTSO-E again."""
    monkeypatch.setenv("PARQUET_STORAGE_PATH", str(tmp_path / "parquet"))
    start = datetime(2026, 10, 1, tzinfo=UTC)
    end = start + timedelta(days=7)
    calls: list[tuple[datetime, datetime]] = []

    def fetch_prices(
        entsoe_key: str | None,
        start: datetime,
        end: datetime,
        country_code: str,
    ) -> pd.Series:
        del entsoe_key
        assert country_code == "DE_LU"
        calls.append((start, end))
        index = pd.date_range(start, end, freq="15min", inclusive="left")
        return pd.Series(50.0, index=index, name="price")

    monkeypatch.setattr(
        "frequenz.lib.notebooks.reporting.asset_optimization.data."
        "fetch_day_ahead_prices",
        fetch_prices,
    )

    week = data_service.get_day_ahead_prices("DE_LU", start, end)
    two_days = data_service.get_day_ahead_prices("DE_LU", end - timedelta(days=2), end)

    assert len(week) == 7 * 24 * 4
    assert len(two_days) == 2 * 24 * 4
    assert calls == [(start, end)]


def test_cached_day_ahead_prices_never_call_external_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Interactive cache reads return immediately without an ENTSO-E request."""
    monkeypatch.setenv("PARQUET_STORAGE_PATH", str(tmp_path / "parquet"))
    start = datetime(2026, 10, 1, tzinfo=UTC)
    end = start + timedelta(days=1)
    calls = 0

    def fetch_prices(
        entsoe_key: str | None,
        start: datetime,
        end: datetime,
        country_code: str,
    ) -> pd.Series:
        del entsoe_key, country_code
        nonlocal calls
        calls += 1
        index = pd.date_range(start, end, freq="15min", inclusive="left")
        return pd.Series(50.0, index=index, name="price")

    monkeypatch.setattr(
        "frequenz.lib.notebooks.reporting.asset_optimization.data."
        "fetch_day_ahead_prices",
        fetch_prices,
    )

    assert data_service.get_cached_day_ahead_prices("DE_LU", start, end).empty
    assert calls == 0

    data_service.get_day_ahead_prices("DE_LU", start, end)
    cached = data_service.get_cached_day_ahead_prices("DE_LU", start, end)

    assert len(cached) == 24 * 4
    assert calls == 1


def test_background_day_ahead_sync_is_shared_between_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent sessions reuse one in-process price synchronization job."""
    start = datetime(2035, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=1)
    calls: list[tuple[str, datetime, datetime]] = []

    def sync_prices(
        country_code: str, sync_start: datetime, sync_end: datetime
    ) -> pd.Series:
        calls.append((country_code, sync_start, sync_end))
        return pd.Series(
            [50.0],
            index=pd.DatetimeIndex([sync_start]),
            name="day_ahead_price",
        )

    monkeypatch.setattr(data_service, "get_day_ahead_prices", sync_prices)

    first = data_service.start_background_day_ahead_price_sync("DE_LU", start, end)
    second = data_service.start_background_day_ahead_price_sync("DE_LU", start, end)

    assert first is second
    assert not first.result(timeout=1).empty
    assert calls == [("DE_LU", start, end + timedelta(days=1))]


def test_background_active_power_sync_is_shared_between_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent sessions reuse one in-process active-power synchronization."""
    start = datetime(2040, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    resolution = timedelta(minutes=15)
    calls: list[tuple[int, datetime, datetime, timedelta]] = []

    def sync_active_power(
        microgrid_id: int,
        sync_start: datetime,
        sync_end: datetime,
        sync_resolution: timedelta,
    ) -> pd.DataFrame:
        calls.append((microgrid_id, sync_start, sync_end, sync_resolution))
        return _frame(sync_start, sync_end)

    monkeypatch.setattr(data_service, "get_microgrid_data", sync_active_power)

    first = data_service.start_background_microgrid_data_sync(
        42, start, end, resolution
    )
    second = data_service.start_background_microgrid_data_sync(
        42, start, end, resolution
    )

    assert first is second
    assert not first.result(timeout=1).empty
    assert calls == [(42, start, end, resolution)]


def test_background_battery_soc_sync_is_shared_between_callers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent sessions reuse one in-process battery-SOC synchronization."""
    start = datetime(2041, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    resolution = timedelta(minutes=15)
    calls: list[tuple[int, datetime, datetime, timedelta]] = []

    def sync_battery_soc(
        microgrid_id: int,
        sync_start: datetime,
        sync_end: datetime,
        sync_resolution: timedelta,
    ) -> pd.DataFrame:
        calls.append((microgrid_id, sync_start, sync_end, sync_resolution))
        return _frame(sync_start, sync_end)

    monkeypatch.setattr(data_service, "get_microgrid_soc_data", sync_battery_soc)

    first = data_service.start_background_microgrid_soc_data_sync(
        42, start, end, resolution
    )
    second = data_service.start_background_microgrid_soc_data_sync(
        42, start, end, resolution
    )

    assert first is second
    assert not first.result(timeout=1).empty
    assert calls == [(42, start, end, resolution)]


def test_active_power_sync_does_not_round_end_into_future() -> None:
    """The normalized API range never extends past the requested end."""
    start = datetime(2040, 1, 1, 10, 2, tzinfo=UTC)
    end = datetime(2040, 1, 1, 11, 8, tzinfo=UTC)

    sync_start, sync_end = (
        data_service._active_power_sync_range(  # pylint: disable=protected-access
            start,
            end,
            timedelta(minutes=15),
        )
    )

    assert sync_start == datetime(2040, 1, 1, 10, 0, tzinfo=UTC)
    assert sync_end == datetime(2040, 1, 1, 11, 0, tzinfo=UTC)
    assert sync_end <= end
