# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests that raw exception text never reaches the user interface."""

import logging
import re
from concurrent.futures import Future
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import streamlit as st

from frequenz.cs_reporting.app_pages.reporting import _format_data_loading_error
from frequenz.cs_reporting.utils.errors import report_error
from frequenz.cs_reporting.views import dashboard

SECRET = "/work/secret/tomls https://api.internal.example:8443 key=abc"
SOURCE_ROOT = Path(__file__).parents[1] / "src" / "frequenz" / "cs_reporting"


def test_report_error_logs_exception_and_returns_matching_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The user-facing text carries the id that the log line carries."""
    exc = RuntimeError(SECRET)
    with caplog.at_level(logging.ERROR):
        text = report_error(exc, "Loading failed")
    match = re.fullmatch(r"\(Fehler-ID: ([0-9a-f]{8})\)", text)
    assert match is not None
    assert SECRET not in text
    record = caplog.records[-1]
    assert match.group(1) in record.getMessage()
    assert record.exc_info is not None and record.exc_info[1] is exc


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError(SECRET),
        KeyError(SECRET),
        ValueError(f"grid is missing formula for AC_POWER_ACTIVE {SECRET}"),
        ValueError(SECRET),
        RuntimeError(f"Missing or empty required environment variable {SECRET}"),
        RuntimeError(f"Microgrid config directory not found: {SECRET}"),
        RuntimeError(f"active event loop {SECRET}"),
        RuntimeError(SECRET),
        OSError(SECRET),
        Exception(SECRET),
    ],
    ids=lambda exc: f"{type(exc).__name__}-{str(exc)[:20]}",
)
def test_data_loading_error_hides_raw_detail(exc: Exception) -> None:
    """Every branch shows the summary and an error id, never the raw text."""
    message = _format_data_loading_error(exc, 243)
    assert "/work/secret" not in message
    assert "internal.example" not in message
    assert "Details:" not in message
    assert "Fehler-ID:" in message


def test_day_ahead_price_failure_warning_hides_raw_detail() -> None:
    """A failed price sync warns with an id instead of the exception text."""
    future: Future[pd.Series] = Future()
    future.set_exception(OSError(SECRET))
    warnings: list[str] = []
    with (
        patch.object(dashboard, "_price_sync_range", return_value=(None, None)),
        patch.object(
            dashboard, "start_background_day_ahead_price_sync", return_value=future
        ),
        patch.object(st, "warning", side_effect=warnings.append),
    ):
        # pylint: disable-next=protected-access
        dashboard._render_day_ahead_price_sync_status(
            pd.DataFrame(), None, pd.Timedelta(hours=1)
        )
    assert len(warnings) == 1
    assert "internal.example" not in warnings[0] and "Fehler-ID:" in warnings[0]


@pytest.mark.parametrize(
    "relative_path",
    [
        "app_pages/reporting.py",
        "app_pages/battery_optimization.py",
        "views/dashboard.py",
    ],
)
def test_pages_never_interpolate_exceptions_into_ui_text(relative_path: str) -> None:
    """Exception objects must not be formatted into strings in page code."""
    source = (SOURCE_ROOT / relative_path).read_text(encoding="utf-8")
    offenders = re.findall(
        r"\{(?:exc|type\(exc\)[^{}]*|[^{}]*\.exception\(\))\}", source
    )
    assert offenders == []


def test_day_ahead_warning_lists_missing_cached_dates() -> None:
    """A failed sync warns with the dates the cache has no prices for."""
    future: Future[pd.Series] = Future()
    future.set_exception(OSError(SECRET))
    warnings: list[str] = []
    master_df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2020-01-01 00:00", "2020-01-02 00:00"]),
            "day_ahead_price": [10.0, None],
        }
    )
    with (
        patch.object(dashboard, "_price_sync_range", return_value=(None, None)),
        patch.object(
            dashboard, "start_background_day_ahead_price_sync", return_value=future
        ),
        patch.object(st, "warning", side_effect=warnings.append),
    ):
        # pylint: disable-next=protected-access
        dashboard._render_day_ahead_price_sync_status(
            master_df, None, pd.Timedelta(hours=1)
        )
    assert "2020-01-02" in warnings[0] and "2020-01-01" not in warnings[0]


def test_day_ahead_sync_still_runs_for_missing_past_dates() -> None:
    """A gap before today is still fetched even when today's prices are cached."""
    future: Future[pd.Series] = Future()
    future.set_result(pd.Series(dtype="float64"))
    now = pd.Timestamp.now(tz="UTC").floor("h")
    master_df = pd.DataFrame(
        {
            "timestamp": [now - pd.Timedelta(days=3), now],
            "day_ahead_price": [None, 50.0],
        }
    )
    with (
        patch.object(
            dashboard, "start_background_day_ahead_price_sync", return_value=future
        ) as sync,
        patch.object(st, "warning"),
    ):
        # pylint: disable-next=protected-access
        dashboard._render_day_ahead_price_sync_status(
            master_df, None, pd.Timedelta(hours=1)
        )
    sync.assert_called_once()


def test_missing_price_dates_collapse_consecutive_days_into_ranges() -> None:
    """Consecutive missing days become one range; isolated days stay single."""
    master_df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-05"]
            ),
            "day_ahead_price": [None, None, None, None],
        }
    )
    # pylint: disable-next=protected-access
    assert dashboard._missing_price_dates(master_df) == [
        "2020-01-01 bis 2020-01-03",
        "2020-01-05",
    ]


def test_missing_entsoe_key_warns_and_skips_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ENTSOE_API_KEY the dashboard warns and starts no sync."""
    monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
    warnings: list[str] = []
    master_df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2020-01-01"]),
            "day_ahead_price": [None],
        }
    )
    with (
        patch.object(dashboard, "start_background_day_ahead_price_sync") as sync,
        patch.object(st, "warning", side_effect=warnings.append),
    ):
        # pylint: disable-next=protected-access
        dashboard._render_day_ahead_price_sync_status(
            master_df, None, pd.Timedelta(hours=1)
        )
    sync.assert_not_called()
    assert "ENTSOE_API_KEY" in warnings[0] and "2020-01-01" in warnings[0]


def test_projected_value_metrics_ignore_unpriced_intervals() -> None:
    """Rows without a price are skipped; KPIs use the priced remainder."""
    master_df = pd.DataFrame(
        {
            "grid_consumption": [1000.0, 1000.0],
            "day_ahead_price": [100.0, None],
        }
    )
    metrics: dict[str, float | str | None] = {}
    # pylint: disable-next=protected-access
    dashboard._set_projected_value_metrics(
        metrics,
        master_df,
        timedelta(hours=1),
        power_column="grid_consumption",
        energy_key="e",
        value_key="v",
        average_price_key="a",
    )
    assert metrics == {"e": 2000.0, "v": 100.0, "a": 10.0}
