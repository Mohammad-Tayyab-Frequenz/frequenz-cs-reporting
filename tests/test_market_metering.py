# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for DSO market-metering integration."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from frequenz.cs_reporting.services import client_factory, market_metering
from frequenz.cs_reporting.views.dashboard import _aggregate_metrics


def test_market_location_ids_are_selected_by_microgrid_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The MaLo IDs come from the relations in the already-loaded AssetsConfig."""

    def relation(microgrid_id: int, market_location_id: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            microgrid_id=microgrid_id,
            market_location_id=market_location_id,
        )

    monkeypatch.setattr(
        client_factory,
        "_load_assets_config",
        lambda: SimpleNamespace(
            relations={
                "first": relation(251, "50003164650"),
                "second": relation(252, "50003807771"),
                "duplicate": relation(251, "50003164650"),
                "without_malo": relation(251, None),
            }
        ),
    )

    assert client_factory.get_market_location_ids(251) == ("50003164650",)


@pytest.mark.asyncio
async def test_market_metering_sums_locations_and_resamples_energy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Latest MaLo revisions are summed and rolled up to report resolution."""
    start = datetime(2026, 8, 21, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    disconnected = False

    class FakeClient:
        """Yield deterministic Market Metering series."""

        def __init__(self, **_kwargs: object) -> None:
            pass

        async def stream_samples(self, **kwargs: Any):  # type: ignore[no-untyped-def]
            locations = kwargs["market_locations"]
            assert kwargs["start_time"] == start
            assert kwargs["end_time"] == end
            yield SimpleNamespace(
                market_location_ref=locations[0],
                direction=SimpleNamespace(name="IMPORT"),
                samples=[
                    SimpleNamespace(sample_time=start, value=1.0, revision=1),
                    SimpleNamespace(sample_time=start, value=2.0, revision=2),
                    SimpleNamespace(
                        sample_time=start + timedelta(minutes=15),
                        value=3.0,
                        revision=1,
                    ),
                ],
            )
            yield SimpleNamespace(
                market_location_ref=locations[1],
                direction=SimpleNamespace(name="IMPORT"),
                samples=[
                    SimpleNamespace(sample_time=start, value=4.0, revision=1),
                    SimpleNamespace(
                        sample_time=start + timedelta(minutes=15),
                        value=5.0,
                        revision=1,
                    ),
                ],
            )
            yield SimpleNamespace(
                market_location_ref=locations[0],
                direction=SimpleNamespace(name="EXPORT"),
                samples=[
                    SimpleNamespace(sample_time=start, value=6.0, revision=1),
                    SimpleNamespace(
                        sample_time=start + timedelta(minutes=15),
                        value=7.0,
                        revision=1,
                    ),
                ],
            )

        async def disconnect(self) -> None:
            nonlocal disconnected
            disconnected = True

    client = FakeClient()
    monkeypatch.setattr(
        market_metering,
        "get_market_location_ids",
        lambda _microgrid_id: ("one", "two"),
    )
    monkeypatch.setattr(
        market_metering,
        "get_market_metering_client",
        lambda _timeout: client,
    )

    result = await market_metering.fetch_market_metering_data(
        251,
        start,
        end,
        timedelta(minutes=30),
    )

    assert disconnected
    assert result["timestamp"].tolist() == [pd.Timestamp(start)]
    assert result["dso_import_energy"].tolist() == [14.0]
    assert result["dso_export_energy"].tolist() == [13.0]


def test_dso_energy_is_merged_by_instant_and_aggregated_as_kpi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DSO data joins across timezones and its energy is exposed as a KPI."""
    master_df = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-08-21 02:00", periods=2, freq="15min", tz="Europe/Berlin"
            ),
            "grid_consumption": [10.0, 20.0],
        }
    )
    dso_df = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-08-21 00:00", periods=2, freq="15min", tz="UTC"
            ),
            "dso_import_energy": [169.2, 176.1],
            "dso_export_energy": [10.0, 11.0],
        }
    )
    merged = market_metering.merge_dso_energy(master_df, dso_df, timedelta(minutes=15))
    monkeypatch.setattr(
        "frequenz.cs_reporting.views.dashboard.aggregate_metrics",
        lambda *_args, **_kwargs: {"grid_consumption_sum": 30.0},
    )

    metrics = _aggregate_metrics(merged, timedelta(minutes=15))

    assert merged["dso_import_power"].tolist() == [676.8, 704.4]
    assert merged["dso_export_power"].tolist() == [40.0, 44.0]
    assert metrics["dso_import_energy_sum"] == pytest.approx(345.3)
    assert metrics["dso_export_energy_sum"] == pytest.approx(21.0)
    assert "dso_import_power" not in master_df
    assert "dso_export_power" not in master_df


def test_merge_dso_energy_keeps_latest_duplicate_without_double_counting() -> None:
    """Duplicate aggregate rows are replaced, not summed a second time."""
    timestamp = pd.Timestamp("2026-08-21 00:00", tz="UTC")
    master_df = pd.DataFrame({"timestamp": [timestamp]})
    dso_df = pd.DataFrame(
        {
            "timestamp": [timestamp, timestamp],
            "dso_import_energy": [100.0, 2.0],
        }
    )

    merged = market_metering.merge_dso_energy(
        master_df,
        dso_df,
        timedelta(minutes=30),
    )

    assert merged["dso_import_power"].tolist() == [4.0]


def test_merge_dso_energy_rejects_non_positive_resolution() -> None:
    """Energy-to-power conversion requires a positive interval duration."""
    with pytest.raises(ValueError, match="resolution must be greater than zero"):
        market_metering.merge_dso_energy(
            pd.DataFrame({"timestamp": []}),
            None,
            timedelta(0),
        )
