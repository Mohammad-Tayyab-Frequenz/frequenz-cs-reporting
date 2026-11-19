# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Regression tests for hardening and correctness fixes."""

# pylint: disable=protected-access

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Lock, Thread
from time import sleep
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import streamlit as st

from frequenz.cs_reporting.app_pages.reporting import _parse_resolution
from frequenz.cs_reporting.components import ui
from frequenz.cs_reporting.rep_cs_core import config
from frequenz.cs_reporting.services import client_factory, data_service
from frequenz.cs_reporting.services.parquet_cache import SyncMetadata
from frequenz.cs_reporting.services.reporting_session import (
    ReportingDataKey,
    ReportingDataSnapshot,
    store_reporting_data_snapshot,
    take_reporting_data_snapshot,
)
from frequenz.cs_reporting.views.dashboard import split_periods

BERLIN = ZoneInfo("Europe/Berlin")
PAYLOAD = '<img src=x onerror="alert(1)"><script>alert(2)</script>'


def _hourly(start: str, end: str) -> pd.DataFrame:
    """Return hourly UTC timestamps in ``[start, end)`` with a constant value."""
    index = pd.date_range(start, end, freq="1h", tz="UTC", inclusive="left")
    return pd.DataFrame({"timestamp": index, "v": 1.0})


def test_section_divider_label_and_badge_are_escaped() -> None:
    """Divider label and badge never reach st.markdown as raw HTML."""
    fake_st = MagicMock()
    with patch.object(ui, "st", fake_st), patch.object(ui, "inject_style"):
        ui.render_section_divider(label=PAYLOAD, badge=PAYLOAD)
    rendered = " ".join(
        str(call.args[0]) for call in fake_st.markdown.call_args_list if call.args
    )
    assert "<script>" not in rendered and "<img" not in rendered


def test_symlinked_toml_outside_config_dir_is_not_followed(tmp_path: Path) -> None:
    """A .toml symlink pointing outside the config dir is not indexed."""
    root = tmp_path / "cfg"
    root.mkdir()
    outside = tmp_path / "outside.toml"
    outside.write_text("[microgrids.1]\n")
    (root / "evil.toml").symlink_to(outside)
    (root / "ok.toml").write_text("[microgrids.2]\n")

    files, _ = client_factory._discover_config_source(str(root))

    assert [Path(file).name for file in files] == ["ok.toml"]


def test_split_periods_across_dst_change_has_no_gap_or_overlap() -> None:
    """The selected period across the March DST change keeps every real hour once."""
    df = _hourly("2026-03-20", "2026-04-05")
    start = pd.Timestamp("2026-03-28", tz=BERLIN).to_pydatetime()
    end = pd.Timestamp("2026-03-31", tz=BERLIN).to_pydatetime()

    current, previous = split_periods(df, start, end, timedelta(hours=1))

    assert len(current) == 71  # 3 days minus the skipped hour
    assert current["timestamp"].is_unique and previous["timestamp"].is_unique
    assert set(current["timestamp"]).isdisjoint(set(previous["timestamp"]))


def test_split_periods_previous_period_covers_full_previous_days() -> None:
    """The previous period is the same calendar days shifted back."""
    df = _hourly("2026-03-20", "2026-04-05")
    start = pd.Timestamp("2026-03-28", tz=BERLIN).to_pydatetime()
    end = pd.Timestamp("2026-03-31", tz=BERLIN).to_pydatetime()

    _, previous = split_periods(df, start, end, timedelta(hours=1))

    assert len(previous) == 72  # 25-27 March are three full 24h days


def test_split_periods_naive_times_are_treated_as_utc() -> None:
    """Naive start and end are UTC, independent of the machine's local zone."""
    df = _hourly("2026-03-01", "2026-03-10")

    current, previous = split_periods(
        df,
        pd.Timestamp("2026-03-04").to_pydatetime(),
        pd.Timestamp("2026-03-07").to_pydatetime(),
        timedelta(hours=1),
    )

    assert len(current) == 72 and len(previous) == 72
    assert previous["timestamp"].min() == pd.Timestamp("2026-03-01", tz="UTC")


@pytest.mark.parametrize("value", ["0min", "0h", "00 min"])
def test_parse_resolution_rejects_zero(value: str) -> None:
    """A zero resolution is invalid and would break resampling."""
    with pytest.raises(ValueError):
        _parse_resolution(value)


def test_split_periods_empty_input_does_not_raise() -> None:
    """Empty input returns two empty frames."""
    current, previous = split_periods(
        pd.DataFrame(columns=["timestamp"]),
        pd.Timestamp("2026-01-01", tz="UTC").to_pydatetime(),
        pd.Timestamp("2026-01-02", tz="UTC").to_pydatetime(),
        timedelta(hours=1),
    )
    assert current.empty and previous.empty


def test_parse_resolution_rejects_unknown_value() -> None:
    """Unknown units are rejected."""
    with pytest.raises(ValueError):
        _parse_resolution("5days")


def test_empty_config_dir_gives_clear_error(tmp_path: Path) -> None:
    """An empty directory fails with a clear message."""
    with pytest.raises(RuntimeError, match="No microgrid config files"):
        client_factory._discover_config_source(str(tmp_path))


def test_missing_config_dir_gives_clear_error(tmp_path: Path) -> None:
    """A missing directory fails with a clear message."""
    with pytest.raises(RuntimeError, match="not found"):
        client_factory._discover_config_source(str(tmp_path / "nope"))


def test_microgrid_config_dir_honours_env_at_call_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The directory is read from the environment on every call."""
    monkeypatch.setenv("MICROGRID_CONFIG_DIR", str(tmp_path))
    assert config.microgrid_config_dir() == tmp_path


def test_concurrent_starts_run_one_job() -> None:
    """Many sessions starting the same key must share one job."""
    jobs: dict[Any, tuple[Future[Any], float]] = {}
    lock = Lock()
    runs: list[int] = []

    def work() -> int:
        sleep(0.2)
        runs.append(1)
        return 1

    with ThreadPoolExecutor(max_workers=1) as executor:
        futures: list[Future[Any]] = []
        threads = [
            Thread(
                target=lambda: futures.append(
                    data_service._start_shared_job(  # pylint: disable=protected-access
                        jobs, lock, executor, 60.0, ("k",), work, ()
                    )
                )
            )
            for _ in range(20)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len({id(f) for f in futures}) == 1
        futures[0].result()
    assert runs == [1]


def test_failed_job_is_retried_after_interval() -> None:
    """A failed job is held for the cooldown, then pruned and retried."""
    jobs: dict[Any, tuple[Future[Any], float]] = {}
    lock = Lock()
    attempts: list[int] = []

    def boom() -> None:
        attempts.append(1)
        raise ValueError("x")

    with ThreadPoolExecutor(max_workers=1) as executor:
        start = data_service._start_shared_job  # pylint: disable=protected-access
        first = start(jobs, lock, executor, 0.05, ("k",), boom, ())
        first.exception()
        assert start(jobs, lock, executor, 0.05, ("k",), boom, ()) is first
        sleep(0.06)
        second = start(jobs, lock, executor, 0.05, ("k",), boom, ())
        second.exception()
    assert second is not first and len(attempts) == 2


def test_snapshot_not_shared_between_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    """A snapshot stored in one session must not be returned in another."""
    key = ReportingDataKey(1, "a", "b", "UTC", 3600, "rev")
    snap = ReportingDataSnapshot(key, pd.DataFrame(), None, SyncMetadata(dataset="d"))
    session_a: dict[str, object] = {}
    session_b: dict[str, object] = {}
    monkeypatch.setattr(st, "session_state", session_a)
    store_reporting_data_snapshot(snap)
    session_a["_reuse_reporting_data_once"] = True
    monkeypatch.setattr(st, "session_state", session_b)
    session_b["_reuse_reporting_data_once"] = True
    assert take_reporting_data_snapshot(key) is None
