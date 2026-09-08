# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for the frequenz.cs_reporting package."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import pytest
from frequenz.lib.notebooks.solar.maintenance import plot_manager, plot_styles

from frequenz.cs_reporting.app_pages.solar import capture_workflow_figures
from frequenz.cs_reporting.utils import time
from frequenz.cs_reporting.views import dashboard
from frequenz.cs_reporting.views.dashboard import (
    _aggregate_metrics,
    _filter_component_types_for_master_df,
    split_periods,
)
from frequenz.cs_reporting.views.metric_renderers import (
    SECTION_SPECS,
    _build_consumption_breakdown,
    _filter_section_box_specs,
    _materialize_boxes,
    _skip_missing_day_ahead_price_specs,
)
from frequenz.cs_reporting.views.plot_renderers import (
    _component_ids_for_plot_source,
    _render_overview_plot,
)


class _FakeMicrogridConfig:
    """Small test double for component category lookup."""

    def __init__(self) -> None:
        self._ids = {
            ("pv", "meter"): [10, 2],
            ("pv", "inverter"): [3, 4],
            ("wind", "meter"): [20],
            ("wind", "inverter"): [],
            ("wind", "component"): [21],
            ("chp", "meter"): [30],
            ("chp", "inverter"): [],
            ("chp", "component"): [31, 32],
            ("battery", "meter"): [40],
            ("battery", "inverter"): [41],
            ("ev", "meter"): [50],
            ("ev", "inverter"): [51],
        }

    def component_type_ids(
        self, component_type: str, component_category: str | None = None
    ) -> list[int]:
        """Return configured fake IDs for a component type/category pair."""
        return self._ids.get((component_type, component_category or ""), [])


def test_capture_workflow_figures_redirects_notebook_displays() -> None:
    """Solar workflow output is captured without leaking notebook display calls."""
    original_show_all = plot_manager.PlotManager.show_all
    original_table_display = getattr(plot_styles, "display")
    figure = go.Figure(go.Scatter(x=[1, 2], y=[3, 4]))
    manager = plot_manager.PlotManager()
    manager.figures["test"] = figure

    with capture_workflow_figures() as figures:
        manager.show_all()
        getattr(plot_styles, "display")("table output")

    assert figures == [figure]
    assert plot_manager.PlotManager.show_all is original_show_all
    assert getattr(plot_styles, "display") is original_table_display


def test_validate_range_accepts_chronological_values() -> None:
    """validate_range returns converted datetimes when start < end."""
    start = date(2024, 1, 1)
    end = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)

    start_dt, end_dt = time.validate_range(start, end)

    assert start_dt == datetime(2024, 1, 1, tzinfo=UTC)
    assert end_dt == datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
    assert end_dt - start_dt == timedelta(days=1, hours=12)


def test_validate_range_rejects_invalid_order() -> None:
    """validate_range raises when end is not after start."""
    with pytest.raises(ValueError):
        time.validate_range("2024-01-02", "2024-01-02")
    with pytest.raises(ValueError):
        time.validate_range("2024-01-03", "2024-01-02")


def test_battery_kpi_section_is_hidden_without_battery_component() -> None:
    """Battery KPI specs are removed when the MID has no battery component."""
    battery_section = next(
        section for section in SECTION_SPECS if section["title"] == "Batteriekennzahlen"
    )

    box_specs = _filter_section_box_specs(
        battery_section,
        component_type_set={"grid", "pv"},
        component_types_provided=True,
        microgrid_id=123,
    )

    assert box_specs == []


def test_battery_kpi_section_is_shown_with_battery_component() -> None:
    """Battery KPI specs are kept when the MID has a battery component."""
    battery_section = next(
        section for section in SECTION_SPECS if section["title"] == "Batteriekennzahlen"
    )

    box_specs = _filter_section_box_specs(
        battery_section,
        component_type_set={"battery", "grid", "pv"},
        component_types_provided=True,
        microgrid_id=123,
    )

    assert box_specs


def test_consumption_breakdown_shows_sources_serving_consumption() -> None:
    """The Stromverbrauch bar is split by sources that serve local consumption."""
    breakdown = _build_consumption_breakdown(
        {
            "mid_consumption_sum": 100.0,
            "grid_consumption_sum": 70.0,
            "grid_to_battery_sum": 10.0,
            "prod_self_consumption_sum": 30.0,
            "battery_to_consumption_sum": 10.0,
            "grid_feed_in_sum": 5.0,
            "pv_production_sum": 40.0,
        }
    )

    assert breakdown == {
        "Stromverbrauch (kWh)": 100.0,
        "Netz zu Verbrauch (kWh)": 60.0,
        "Erzeugung zu Verbrauch (kWh)": 30.0,
        "Batterie zu Verbrauch (kWh)": 10.0,
    }


def test_component_types_exclude_battery_without_master_battery_power_flow() -> None:
    """Battery is removed when the master dataframe lacks battery power flow."""
    master_df = pd.DataFrame(
        columns=[
            "timestamp",
            "grid_consumption",
            "mid_consumption",
            "grid_feed_in",
            "pv_asset_production",
        ]
    )

    component_types = _filter_component_types_for_master_df(
        ["grid", "consumption", "pv", "battery"], master_df
    )

    assert component_types == ("grid", "consumption", "pv")


def test_aggregate_metrics_omits_day_ahead_price_metrics_when_prices_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Day-ahead price metrics are removed when no price column is available."""
    captured_price_columns: list[str | None] = []

    def fake_aggregate_metrics(
        energy_report_df: pd.DataFrame,
        resolution: timedelta,
        *,
        price_column: str | None = None,
    ) -> dict[str, float | None | str]:
        del energy_report_df, resolution
        captured_price_columns.append(price_column)
        return {
            "grid_consumption_sum": 10.0,
            "grid_feed_in_sum": 5.0,
            "grid_import_cost_sum": 0.0,
            "grid_feed_in_revenue_sum": 0.0,
        }

    monkeypatch.setattr(dashboard, "aggregate_metrics", fake_aggregate_metrics)

    metrics = _aggregate_metrics(
        pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=1)}),
        timedelta(minutes=15),
    )

    assert captured_price_columns == [None]
    assert metrics == {
        "grid_consumption_sum": 10.0,
        "grid_feed_in_sum": 5.0,
    }


def test_aggregate_metrics_omits_day_ahead_price_metrics_when_prices_are_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Day-ahead price metrics are removed when the price column is all null."""
    captured_price_columns: list[str | None] = []

    def fake_aggregate_metrics(
        energy_report_df: pd.DataFrame,
        resolution: timedelta,
        *,
        price_column: str | None = None,
    ) -> dict[str, float | None | str]:
        del energy_report_df, resolution
        captured_price_columns.append(price_column)
        return {
            "grid_consumption_sum": 10.0,
            "grid_feed_in_sum": 5.0,
            "grid_import_cost_sum": 0.0,
            "grid_feed_in_revenue_sum": 0.0,
        }

    monkeypatch.setattr(dashboard, "aggregate_metrics", fake_aggregate_metrics)

    metrics = _aggregate_metrics(
        pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=1),
                "day_ahead_price": [None],
            }
        ),
        timedelta(minutes=15),
    )

    assert captured_price_columns == [None]
    assert metrics == {
        "grid_consumption_sum": 10.0,
        "grid_feed_in_sum": 5.0,
    }


def test_aggregate_metrics_uses_day_ahead_price_when_prices_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Day-ahead average price metrics are added when prices are available."""
    captured_price_columns: list[str | None] = []

    def fake_aggregate_metrics(
        energy_report_df: pd.DataFrame,
        resolution: timedelta,
        *,
        price_column: str | None = None,
    ) -> dict[str, float | None | str]:
        del energy_report_df, resolution
        captured_price_columns.append(price_column)
        return {
            "grid_consumption_sum": 10.0,
            "grid_feed_in_sum": 5.0,
            "grid_import_cost_sum": 2.0,
            "grid_feed_in_revenue_sum": 0.5,
        }

    monkeypatch.setattr(dashboard, "aggregate_metrics", fake_aggregate_metrics)

    metrics = _aggregate_metrics(
        pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=1),
                "day_ahead_price": [100.0],
            }
        ),
        timedelta(minutes=15),
    )

    assert captured_price_columns == ["day_ahead_price"]
    assert metrics["average_da_price_grid_import"] == 20.0
    assert metrics["average_da_price_grid_feed_in"] == 10.0


def test_split_periods_returns_selected_and_previous_ranges() -> None:
    """Fetched data is split into equal-length previous and selected periods."""
    master_df = pd.DataFrame(
        {
            "timestamp": pd.date_range(
                "2026-01-01T00:00:00Z",
                periods=4,
                freq="D",
            ),
            "grid_consumption": [1.0, 2.0, 3.0, 4.0],
        }
    )

    current_df, previous_df = split_periods(
        master_df,
        datetime(2026, 1, 3, tzinfo=UTC),
        datetime(2026, 1, 5, tzinfo=UTC),
        timedelta(days=1),
    )

    assert previous_df["grid_consumption"].tolist() == [1.0, 2.0]
    assert current_df["grid_consumption"].tolist() == [3.0, 4.0]


def test_split_periods_caps_previous_range_to_available_current_data() -> None:
    """Previous-period comparison does not use a full day for partial current data."""
    master_df = pd.DataFrame(
        {
            "timestamp": [
                datetime(2026, 1, 1, 0, tzinfo=UTC),
                datetime(2026, 1, 1, 6, tzinfo=UTC),
                datetime(2026, 1, 1, 12, tzinfo=UTC),
                datetime(2026, 1, 2, 0, tzinfo=UTC),
                datetime(2026, 1, 2, 6, tzinfo=UTC),
            ],
            "grid_consumption": [1.0, 2.0, 3.0, 4.0, 5.0],
        }
    )

    current_df, previous_df = split_periods(
        master_df,
        datetime(2026, 1, 2, tzinfo=UTC),
        datetime(2026, 1, 3, tzinfo=UTC),
        timedelta(hours=6),
    )

    assert previous_df["grid_consumption"].tolist() == [1.0, 2.0]
    assert current_df["grid_consumption"].tolist() == [4.0, 5.0]


def test_materialize_boxes_includes_previous_metric_values() -> None:
    """KPI box materialization preserves matching previous-period values."""
    boxes = _materialize_boxes(
        [{"label": "Netzbezug (kWh)", "key": "grid_consumption_sum"}],
        {"grid_consumption_sum": 110.0},
        {"grid_consumption_sum": 100.0},
    )

    assert boxes == [("Netzbezug (kWh)", 110.0, 100.0)]


def test_day_ahead_price_kpi_specs_are_skipped_when_metrics_missing() -> None:
    """Day-ahead price KPI boxes are hidden when ENTSOE prices are unavailable."""
    grid_section = next(
        section for section in SECTION_SPECS if section["title"] == "Netzkennzahlen"
    )
    box_specs = _filter_section_box_specs(
        grid_section,
        component_type_set={"grid"},
        component_types_provided=True,
        microgrid_id=231,
    )

    filtered_specs = _skip_missing_day_ahead_price_specs(
        box_specs,
        metrics={"grid_consumption_sum": 10.0, "grid_feed_in_sum": 5.0},
    )

    assert [spec.get("key") for spec in filtered_specs] == [
        "grid_consumption_sum",
        "grid_feed_in_sum",
        "peak",
    ]


def test_overview_plot_renders_without_day_ahead_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The overview plot does not require a secondary price y-axis."""
    rendered_titles: list[str] = []

    def fake_render_plot_card(title: str, fig: object) -> None:
        del fig
        rendered_titles.append(title)

    monkeypatch.setattr(
        "frequenz.cs_reporting.views.plot_renderers.render_plot_card",
        fake_render_plot_card,
    )

    _render_overview_plot(
        pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=2, freq="h"),
                "grid_consumption": [10.0, 8.0],
                "mid_consumption": [12.0, 9.0],
                "battery_power_flow": [1.0, -1.0],
                "battery_charge": [1.0, 0.0],
                "battery_discharge": [0.0, -1.0],
                "battery_soc_pct": [50.0, 55.0],
                "peak_before_optimization": [12.0, 12.0],
                "peak_after_optimization": [10.0, 10.0],
            }
        )
    )

    assert rendered_titles == ["Lastgang Übersicht"]


def test_component_ids_for_plot_source_filters_requested_hth_components() -> None:
    """HTH plot source selection returns IDs only for requested plot components."""
    config = _FakeMicrogridConfig()

    meter_ids = _component_ids_for_plot_source(
        config,
        component_types=["pv", "wind", "chp", "battery", "ev"],
        component_plot_source="meter",
    )
    inverter_ids = _component_ids_for_plot_source(
        config,
        component_types=["pv", "wind", "chp", "battery", "ev"],
        component_plot_source="inverter",
    )

    assert meter_ids == {
        "pv": ("2", "10"),
        "wind": ("20",),
        "chp": ("30",),
        "batt": ("40",),
    }
    assert inverter_ids == {
        "pv": ("3", "4"),
        "wind": ("21",),
        "chp": ("31", "32"),
        "batt": ("41",),
    }
