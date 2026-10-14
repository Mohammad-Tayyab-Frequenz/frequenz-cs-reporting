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
