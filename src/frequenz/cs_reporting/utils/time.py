# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Time utilities for the reporting package."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Union

from pandas import to_datetime

DateLike = Union[str, date, datetime]


def to_iso8601(d: DateLike) -> str:
    """Normalize any date-like input to an ISO8601 string.

    Args:
        d: Date-like input such as ``str``, ``datetime.date``, or
            ``datetime.datetime`` (including pandas equivalents).

    Returns:
        ISO8601 formatted string.

    Raises:
        TypeError: If the input is not recognized as date-like.
    """
    if hasattr(d, "to_pydatetime"):
        d = d.to_pydatetime()

    if isinstance(d, str):
        return d
    if isinstance(d, datetime):
        return d.isoformat()
    if isinstance(d, date):
        return datetime(d.year, d.month, d.day, tzinfo=UTC).isoformat()
    raise TypeError(f"Invalid date-like value: {d!r}")


def validate_range(start: DateLike, end: DateLike) -> tuple[datetime, datetime]:
    """Validate that the start value precedes the end value.

    Args:
        start: Start date or datetime value.
        end: End date or datetime value.

    Returns:
        Original ``start`` and ``end`` values when valid.

    Raises:
        ValueError: If ``start`` is greater than or equal to ``end``.
    """
    start_ts = to_datetime(start)
    end_ts = to_datetime(end)

    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize(UTC)
    else:
        start_ts = start_ts.tz_convert(UTC)

    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize(UTC)
    else:
        end_ts = end_ts.tz_convert(UTC)

    start_dt = start_ts.to_pydatetime()
    end_dt = end_ts.to_pydatetime()
    if end_dt <= start_dt:
        raise ValueError("end_date must be after start_date")
    return start_dt, end_dt
