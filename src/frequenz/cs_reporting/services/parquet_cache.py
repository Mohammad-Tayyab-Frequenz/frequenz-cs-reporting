# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Atomic, range-aware Parquet storage for reporting time series."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

_LOGGER = logging.getLogger(__name__)
_Range = tuple[datetime, datetime]
_COLUMN_PREFIX = "__frequenz_column_v1__"
_LEGACY_BOUNDARY_ERROR = (
    "ValueError: Reporting data contains timestamps outside the requested range"
)


def _utc(value: datetime) -> datetime:
    """Return an aware UTC datetime."""
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(UTC)
    else:
        timestamp = timestamp.tz_convert(UTC)
    return timestamp.to_pydatetime()


def _iso(value: datetime) -> str:
    """Serialize an instant in a stable UTC representation."""
    return _utc(value).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    """Parse a metadata timestamp as UTC."""
    return pd.Timestamp(value).tz_convert(UTC).to_pydatetime()


@dataclass(frozen=True)
class DatasetKey:
    """Identify one independently stored time-series dataset."""

    name: str
    microgrid_id: int
    resolution_seconds: int

    @property
    def slug(self) -> str:
        """Return a filename-safe stable identifier."""
        safe_name = "".join(
            character if character.isalnum() or character in "-_" else "_"
            for character in self.name
        )
        return f"{safe_name}_mid{self.microgrid_id}_{self.resolution_seconds}s"


# pylint: disable = too-many-instance-attributes
@dataclass
class SyncMetadata:
    """Persisted synchronization state for one dataset."""

    dataset: str
    covered_ranges: list[list[str]] = field(default_factory=list)
    timestamp_axis: str = "index"
    index_name: str | None = None
    last_successful_sync: str | None = None
    last_attempted_sync: str | None = None
    status: str = "never_synced"
    records_retrieved: int = 0
    records_inserted_or_updated: int = 0
    total_stored_records: int = 0
    sync_duration_seconds: float = 0.0
    last_error: str | None = None

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> SyncMetadata:
        """Create metadata while tolerating fields added by newer versions."""
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in values.items() if key in known})


class ParquetRangeCache:
    """Synchronize API time ranges into an atomic local Parquet dataset."""

    def __init__(
        self,
        root: Path,
        *,
        sync_interval: timedelta,
        overlap: timedelta,
        retry_attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        """Initialize a cache rooted at the configured Parquet directory."""
        self._root = root
        self._metadata_root = root.parent / "metadata"
        self._sync_interval = sync_interval
        self._overlap = overlap
        self._retry_attempts = retry_attempts
        self._sleeper = sleeper

    # pylint: disable = too-many-locals
    def get(
        self,
        key: DatasetKey,
        start: datetime,
        end: datetime,
        fetch: Callable[[datetime, datetime], pd.DataFrame],
    ) -> pd.DataFrame:
        """Return a requested range, synchronizing missing or stale data."""
        requested = (_utc(start), _utc(end))
        if requested[0] >= requested[1]:
            raise ValueError("The cache range end must be after its start")

        self._root.mkdir(parents=True, exist_ok=True)
        self._metadata_root.mkdir(parents=True, exist_ok=True)
        with self._lock(key):
            metadata = self._read_metadata(key)
            stored, storage_valid = self._read_frame(key)
            covered = self._metadata_ranges(metadata)
            if not storage_valid:
                covered = []
            required = _subtract_range(requested, covered)
            now = datetime.now(tz=UTC)
            due = _sync_due(metadata.last_successful_sync, now, self._sync_interval)
            if not due and _is_small_trailing_extension(
                required, covered, self._sync_interval
            ):
                required = []

            ranges = list(required)
            if due and covered:
                watermark = max(range_end for _, range_end in covered)
                coverage_start = min(range_start for range_start, _ in covered)
                refresh_start = max(coverage_start, watermark - self._overlap)
                if refresh_start < watermark:
                    ranges.append((refresh_start, watermark))
            ranges = _merge_ranges(ranges)

            if ranges:
                stored, metadata = self._synchronize(
                    key, stored, metadata, covered, ranges, fetch, now
                )

            return _slice_frame(stored, requested, metadata)

    def read(
        self,
        key: DatasetKey,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Return cached data without synchronizing missing or stale ranges.

        Args:
            key: Dataset identifier.
            start: Inclusive start of the requested range.
            end: Exclusive end of the requested range.

        Returns:
            The locally cached slice, or an empty dataframe when no valid cache
            exists.  This method never calls an external data source.
        """
        requested = (_utc(start), _utc(end))
        if requested[0] >= requested[1]:
            raise ValueError("The cache range end must be after its start")

        self._root.mkdir(parents=True, exist_ok=True)
        self._metadata_root.mkdir(parents=True, exist_ok=True)
        metadata = self._read_metadata(key)
        stored, storage_valid = self._read_frame(key)
        if not storage_valid:
            return pd.DataFrame()
        return _slice_frame(stored, requested, metadata)

    def metadata(self, key: DatasetKey) -> SyncMetadata:
        """Read synchronization metadata for status display or monitoring."""
        return self._read_metadata(key)

    # pylint: disable = too-many-locals, too-many-arguments, too-many-positional-arguments
    def _synchronize(
        self,
        key: DatasetKey,
        stored: pd.DataFrame,
        metadata: SyncMetadata,
        covered: list[_Range],
        ranges: list[_Range],
        fetch: Callable[[datetime, datetime], pd.DataFrame],
        attempted_at: datetime,
    ) -> tuple[pd.DataFrame, SyncMetadata]:
        started = time.monotonic()
        metadata.last_attempted_sync = _iso(attempted_at)
        metadata.status = "syncing"
        metadata.last_error = None
        self._write_metadata(key, metadata)

        try:
            incoming_parts: list[pd.DataFrame] = []
            incoming_axis: tuple[str, str | None] | None = None
            for range_start, range_end in ranges:
                raw_frame = self._fetch_with_retry(fetch, range_start, range_end)
                if not raw_frame.empty and incoming_axis is None:
                    incoming_axis = _raw_frame_axis(raw_frame)
                incoming_parts.append(
                    _normalize_frame(
                        raw_frame,
                        range_start,
                        range_end,
                        tolerance=timedelta(seconds=key.resolution_seconds),
                    )
                )
            incoming = _concat_frames(incoming_parts)
            normalized_stored = _normalize_stored(stored)
            merged = _merge_frames(normalized_stored, incoming)
            axis, index_name = incoming_axis or (
                metadata.timestamp_axis,
                metadata.index_name,
            )
            new_covered = _merge_ranges([*covered, *ranges])

            self._write_frame(key, merged)
            metadata.covered_ranges = [
                [_iso(range_start), _iso(range_end)]
                for range_start, range_end in new_covered
            ]
            metadata.timestamp_axis = axis
            metadata.index_name = index_name
            metadata.last_successful_sync = _iso(attempted_at)
            metadata.status = "ok"
            metadata.records_retrieved = len(incoming)
            metadata.records_inserted_or_updated = len(incoming)
            metadata.total_stored_records = len(merged)
            metadata.sync_duration_seconds = round(time.monotonic() - started, 3)
            metadata.last_error = None
            self._write_metadata(key, metadata)
            return merged, metadata
        except Exception as exc:
            metadata.status = "error"
            metadata.sync_duration_seconds = round(time.monotonic() - started, 3)
            metadata.last_error = f"{type(exc).__name__}: {exc}"
            self._write_metadata(key, metadata)
            _LOGGER.exception("Synchronization failed for %s", key.slug)
            if _range_is_covered(ranges, covered):
                return stored, metadata
            raise

    def _fetch_with_retry(
        self,
        fetch: Callable[[datetime, datetime], pd.DataFrame],
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Retry transient transport and server failures with backoff."""
        for attempt in range(self._retry_attempts):
            try:
                return fetch(start, end)
            except Exception as exc:  # pylint: disable=broad-except
                if attempt + 1 >= self._retry_attempts or not _is_transient(exc):
                    raise
                delay = _retry_after_seconds(exc) or (0.5 * (2**attempt))
                _LOGGER.warning(
                    "Transient sync failure; retrying %s in %.1f seconds",
                    type(exc).__name__,
                    delay,
                )
                self._sleeper(delay)
        raise AssertionError("retry loop exited unexpectedly")

    def _read_frame(self, key: DatasetKey) -> tuple[pd.DataFrame, bool]:
        path = self._data_path(key)
        if not path.exists():
            return pd.DataFrame(), False
        version = (path.stat().st_mtime_ns, path.stat().st_size)
        try:
            return _read_parquet_versioned(str(path), version), True
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Ignoring unreadable Parquet cache %s", path)
            return pd.DataFrame(), False

    def _write_frame(self, key: DatasetKey, frame: pd.DataFrame) -> None:
        path = self._data_path(key)
        temporary = _temporary_path(path, ".parquet.tmp")
        try:
            encoded = frame.copy()
            encoded.columns = [_encode_column(column) for column in frame.columns]
            encoded.to_parquet(temporary, engine="pyarrow", index=True)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read_metadata(self, key: DatasetKey) -> SyncMetadata:
        path = self._metadata_path(key)
        if not path.exists():
            return SyncMetadata(dataset=key.slug)
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(values, dict):
                raise ValueError("metadata root must be an object")
            metadata = SyncMetadata.from_dict(values)
            # Versions before the boundary-filtering fix recorded valid API
            # responses as failures. Do not keep presenting that obsolete
            # false-positive after an application restart.
            if metadata.last_error == _LEGACY_BOUNDARY_ERROR:
                metadata.status = "ok"
                metadata.last_error = None
            return metadata
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            _LOGGER.exception("Ignoring invalid cache metadata %s", path)
            return SyncMetadata(dataset=key.slug)

    def _write_metadata(self, key: DatasetKey, metadata: SyncMetadata) -> None:
        path = self._metadata_path(key)
        temporary = _temporary_path(path, ".json.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as output:
                json.dump(asdict(metadata), output, indent=2, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def _lock(self, key: DatasetKey) -> Iterator[None]:
        lock_path = self._metadata_root / f"{key.slug}.lock"
        with lock_path.open("a", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _data_path(self, key: DatasetKey) -> Path:
        return self._root / f"{key.slug}.parquet"

    def _metadata_path(self, key: DatasetKey) -> Path:
        return self._metadata_root / f"{key.slug}.json"

    def _metadata_ranges(self, metadata: SyncMetadata) -> list[_Range]:
        try:
            return _merge_ranges(
                [(_parse(start), _parse(end)) for start, end in metadata.covered_ranges]
            )
        except (TypeError, ValueError):
            _LOGGER.warning("Discarding invalid ranges for %s", metadata.dataset)
            return []


@st.cache_data(show_spinner=False)
def _read_parquet_versioned(path: str, version: tuple[int, int]) -> pd.DataFrame:
    """Read Parquet once per exact file version."""
    del version
    frame = pd.read_parquet(path)
    frame.columns = [_decode_column(column) for column in frame.columns]
    return frame


def _encode_column(value: Any) -> str:
    """Encode a pandas column label without losing its Python type."""

    def encode(item: Any) -> dict[str, Any]:
        if isinstance(item, bool):
            return {"type": "bool", "value": item}
        if isinstance(item, int):
            return {"type": "int", "value": item}
        if isinstance(item, float):
            return {"type": "float", "value": item}
        if isinstance(item, str):
            return {"type": "str", "value": item}
        if item is None:
            return {"type": "none", "value": None}
        if isinstance(item, tuple):
            return {"type": "tuple", "value": [encode(part) for part in item]}
        raise TypeError(f"Unsupported Parquet column label type: {type(item).__name__}")

    return _COLUMN_PREFIX + json.dumps(encode(value), separators=(",", ":"))


def _decode_column(value: Any) -> Any:
    """Decode a column label written by :func:`_encode_column`."""
    if not isinstance(value, str) or not value.startswith(_COLUMN_PREFIX):
        return value
    encoded = json.loads(value.removeprefix(_COLUMN_PREFIX))

    def decode(item: dict[str, Any]) -> Any:
        kind = item["type"]
        raw_value = item["value"]
        if kind == "tuple":
            return tuple(decode(part) for part in raw_value)
        if kind == "none":
            return None
        if kind in {"bool", "int", "float", "str"}:
            return raw_value
        raise ValueError(f"Unknown encoded column label type: {kind}")

    if not isinstance(encoded, dict):
        raise ValueError("Encoded column label must be an object")
    return decode(encoded)


def _temporary_path(destination: Path, suffix: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=suffix, dir=destination.parent
    )
    os.close(descriptor)
    return Path(raw_path)


def _sync_due(last_success: str | None, now: datetime, interval: timedelta) -> bool:
    if last_success is None:
        return True
    try:
        return now - _parse(last_success) >= interval
    except (TypeError, ValueError):
        return True


def _http_status(exc: Exception) -> int | None:
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None) or getattr(exc, "status_code", None)
    return value if isinstance(value, int) else None


def _is_transient(exc: Exception) -> bool:
    status = _http_status(exc)
    return (
        isinstance(exc, (TimeoutError, ConnectionError, OSError))
        or status == 429
        or (status is not None and 500 <= status < 600)
    )


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {})
    value = headers.get("Retry-After") if hasattr(headers, "get") else None
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(str(value))
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(0.0, (retry_at - datetime.now(tz=UTC)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _merge_ranges(ranges: list[_Range]) -> list[_Range]:
    if not ranges:
        return []
    merged: list[_Range] = []
    for current_start, current_end in sorted(ranges):
        if current_start >= current_end:
            continue
        if merged and current_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], current_end))
        else:
            merged.append((current_start, current_end))
    return merged


def _subtract_range(requested: _Range, covered: list[_Range]) -> list[_Range]:
    missing: list[_Range] = []
    cursor, requested_end = requested
    for covered_start, covered_end in _merge_ranges(covered):
        if covered_end <= cursor:
            continue
        if covered_start >= requested_end:
            break
        if covered_start > cursor:
            missing.append((cursor, min(covered_start, requested_end)))
        cursor = max(cursor, covered_end)
        if cursor >= requested_end:
            break
    if cursor < requested_end:
        missing.append((cursor, requested_end))
    return missing


def _range_is_covered(requested: list[_Range], covered: list[_Range]) -> bool:
    return all(not _subtract_range(item, covered) for item in requested)


def _is_small_trailing_extension(
    missing: list[_Range], covered: list[_Range], interval: timedelta
) -> bool:
    """Defer a moving live-range tail until the next synchronization is due."""
    if len(missing) != 1 or not covered:
        return False
    missing_start, missing_end = missing[0]
    watermark = max(range_end for _, range_end in covered)
    return missing_start == watermark and missing_end - watermark <= interval


def _normalize_frame(
    frame: pd.DataFrame,
    range_start: datetime,
    range_end: datetime,
    *,
    tolerance: timedelta,
) -> pd.DataFrame:
    """Normalize timestamps and remove expected API boundary buckets.

    Resampling APIs can include buckets outside the requested interval. Those
    rows are safe to discard when the response also contains relevant rows. A
    response with no overlap is accepted only when all its rows are expected
    adjacent boundary buckets; otherwise synchronization is aborted.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("The reporting client returned a non-DataFrame response")
    if frame.empty:
        return frame.copy()
    result = frame.copy()
    if isinstance(result.index, pd.DatetimeIndex):
        result.index = pd.to_datetime(result.index, utc=True)
    elif "timestamp" in result.columns:
        result["timestamp"] = pd.to_datetime(
            result["timestamp"], utc=True, errors="raise"
        )
        result = result.set_index("timestamp")
    else:
        raise ValueError("Reporting data has no DatetimeIndex or timestamp column")
    if result.index.hasnans:
        raise ValueError("Reporting data contains null timestamps")
    start_utc, end_utc = pd.Timestamp(range_start), pd.Timestamp(range_end)
    in_range = (result.index >= start_utc) & (result.index < end_utc)
    if not in_range.any():
        earliest_allowed = start_utc - tolerance
        latest_allowed = end_utc + tolerance
        expected_boundary_rows = (
            (result.index >= earliest_allowed) & (result.index <= latest_allowed)
        ).all()
        if not expected_boundary_rows:
            raise ValueError("Reporting data does not overlap the requested time range")
    return result.loc[in_range].sort_index()


def _normalize_stored(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("Stored reporting data does not have a DatetimeIndex")
    result = frame.copy()
    result.index = pd.to_datetime(result.index, utc=True)
    return result.sort_index()


def _concat_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    populated = [frame for frame in frames if not frame.empty]
    if not populated:
        return pd.DataFrame()
    return pd.concat(populated, axis=0, sort=False)


def _merge_frames(stored: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
    if stored.empty:
        combined = incoming.copy()
    elif incoming.empty:
        combined = stored.copy()
    else:
        combined = pd.concat([stored, incoming], axis=0, sort=False)
    if combined.empty:
        return combined
    return combined[~combined.index.duplicated(keep="last")].sort_index()


def _raw_frame_axis(frame: pd.DataFrame) -> tuple[str, str | None]:
    if isinstance(frame.index, pd.DatetimeIndex):
        index_name = frame.index.name
        return "index", str(index_name) if index_name is not None else None
    if "timestamp" in frame.columns:
        return "column", "timestamp"
    raise ValueError("Reporting data has no DatetimeIndex or timestamp column")


def _slice_frame(
    frame: pd.DataFrame, requested: _Range, metadata: SyncMetadata
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    normalized = _normalize_stored(frame)
    start, end = map(pd.Timestamp, requested)
    result = normalized.loc[
        (normalized.index >= start) & (normalized.index < end)
    ].copy()
    result.index.name = metadata.index_name
    if metadata.timestamp_axis == "column":
        column_name = metadata.index_name or "timestamp"
        return result.rename_axis(column_name).reset_index()
    return result
