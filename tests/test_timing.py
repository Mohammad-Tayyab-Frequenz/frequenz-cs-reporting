# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for file-backed runtime duration diagnostics."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from frequenz.cs_reporting.utils import timing


def test_log_duration_appends_start_and_end_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Timing entries are appended below the configured metadata directory."""
    monkeypatch.setenv("PARQUET_STORAGE_PATH", str(tmp_path / "parquet"))
    values: Iterator[float] = iter((10.0, 12.3456))
    monkeypatch.setattr(timing, "perf_counter", lambda: next(values))

    with timing.log_duration("reporting.test_step"):
        pass

    lines = (
        (tmp_path / "metadata" / "duration_log.txt")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(lines) == 2
    assert "[timing] START reporting.test_step" in lines[0]
    assert "[timing] END reporting.test_step duration=2.346s" in lines[1]
    assert "pid=" in lines[0]
    assert "thread=" in lines[0]


def test_log_duration_records_end_when_operation_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The end entry is recorded when the measured operation raises."""
    monkeypatch.setenv("PARQUET_STORAGE_PATH", str(tmp_path / "parquet"))
    values: Iterator[float] = iter((4.0, 5.0))
    monkeypatch.setattr(timing, "perf_counter", lambda: next(values))

    with pytest.raises(RuntimeError, match="failure"):
        with timing.log_duration("reporting.failing_step"):
            raise RuntimeError("failure")

    contents = (tmp_path / "metadata" / "duration_log.txt").read_text(encoding="utf-8")
    assert "[timing] START reporting.failing_step" in contents
    assert "[timing] END reporting.failing_step duration=1.000s" in contents
