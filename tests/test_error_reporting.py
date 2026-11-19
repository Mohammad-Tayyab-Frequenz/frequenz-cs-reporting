# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests that raw exception text never reaches the user interface."""

import logging
import re
from concurrent.futures import Future
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
