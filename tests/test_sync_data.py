# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for scheduled dataset synchronization."""

from datetime import datetime

import pandas as pd
import pytest

from frequenz.cs_reporting.services import sync_data


def test_price_sync_does_not_require_a_microgrid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The daily price job can run independently from microgrid datasets."""
    calls: list[tuple[str, datetime, datetime]] = []

    def sync_prices(country_code: str, start: datetime, end: datetime) -> pd.Series:
        calls.append((country_code, start, end))
        return pd.Series(dtype="float64")

    monkeypatch.setattr(sync_data, "get_day_ahead_prices", sync_prices)
    monkeypatch.setattr(
        "sys.argv",
        [
            "sync_data",
            "--dataset",
            "day-ahead-prices",
            "--country-code",
            "DE_LU",
            "--start",
            "2026-10-13T00:00:00Z",
            "--end",
            "2026-10-14T00:00:00Z",
        ],
    )

    sync_data.main()

    assert len(calls) == 1
    country_code, start, end = calls[0]
    assert country_code == "DE_LU"
    assert start.isoformat() == "2026-10-13T00:00:00+00:00"
    assert end.isoformat() == "2026-10-14T00:00:00+00:00"


def test_cache_is_persisted_even_when_a_microgrid_sync_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Data synchronized before a failure is still saved to persistent storage."""
    persisted: list[bool] = []

    def fail(*_args: object) -> pd.DataFrame:
        raise RuntimeError("api down")

    monkeypatch.setenv("DEEPNOTE", "1")
    monkeypatch.setattr(sync_data, "deepnote_hybrid_cache_enabled", lambda: True)
    monkeypatch.setattr(sync_data, "prepare_deepnote_hybrid_cache", lambda: None)
    monkeypatch.setattr(
        sync_data, "persist_deepnote_hybrid_cache", lambda: persisted.append(True)
    )
    monkeypatch.setattr(sync_data, "get_microgrid_data", fail)
    monkeypatch.setattr("sys.argv", ["sync_data", "--microgrid-id", "1"])

    with pytest.raises(RuntimeError, match="api down"):
        sync_data.main()

    assert persisted == [True]


def test_persist_error_does_not_replace_the_sync_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing snapshot copy must not hide why the synchronization failed."""

    def fail(*_args: object) -> pd.DataFrame:
        raise RuntimeError("api down")

    def fail_persist() -> None:
        raise OSError("disk full")

    monkeypatch.setenv("DEEPNOTE", "1")
    monkeypatch.setattr(sync_data, "deepnote_hybrid_cache_enabled", lambda: True)
    monkeypatch.setattr(sync_data, "prepare_deepnote_hybrid_cache", lambda: None)
    monkeypatch.setattr(sync_data, "persist_deepnote_hybrid_cache", fail_persist)
    monkeypatch.setattr(sync_data, "get_microgrid_data", fail)
    monkeypatch.setattr("sys.argv", ["sync_data", "--microgrid-id", "1"])

    with pytest.raises(RuntimeError, match="api down"):
        sync_data.main()
