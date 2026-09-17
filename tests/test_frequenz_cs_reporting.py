# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for the frequenz.cs_reporting package."""

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import plotly.graph_objects as go
import pytest
from frequenz.lib.notebooks.solar.maintenance import plot_manager, plot_styles

from frequenz.cs_reporting.app_pages.battery_optimization import (
    _SIDEBAR_KEY_PREFIX,
    _previous_month_date,
)
from frequenz.cs_reporting.app_pages.solar import capture_workflow_figures
from frequenz.cs_reporting.components.ui import (
    _plot_card_height,
    _plotly_component_height,
)
from frequenz.cs_reporting.services.data_service import (
    _battery_capacity_kwh_from_metric_data,
)
from frequenz.cs_reporting.utils import time
from frequenz.cs_reporting.views import dashboard
from frequenz.cs_reporting.views.battery_optimization import (
    aggregate_battery_optimization_summary,
    build_daily_battery_optimization_figure,
    build_normalized_battery_optimization_figure,
    calculate_battery_optimization_summary,
    calculate_normalized_battery_optimization_metrics,
)
from frequenz.cs_reporting.views.component_sources import default_component_plot_source
from frequenz.cs_reporting.views.dashboard import (
    _aggregate_metrics,
    _filter_component_types_for_master_df,
    split_periods,
)
from frequenz.cs_reporting.views.metric_renderers import (
    SECTION_SPECS,
    _build_consumption_breakdown,
    _delta_html,
    _filter_section_box_specs,
    _fmt_metric_value,
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
    ) -> list[int] | None:
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


def test_battery_optimization_default_start_uses_previous_month() -> None:
    """Battery optimization defaults start date to the previous month."""
    assert _previous_month_date(date(2026, 9, 16)) == date(2026, 8, 16)
    assert _previous_month_date(date(2026, 3, 31)) == date(2026, 2, 28)


def test_battery_optimization_sidebar_uses_page_specific_state() -> None:
    """Battery optimization sidebar state is isolated from reporting filters."""
    assert _SIDEBAR_KEY_PREFIX == "battery_optimization_"


def test_kpi_formatter_treats_non_finite_values_as_missing() -> None:
    """Missing numeric aggregates do not break the reporting dashboard."""
    assert _fmt_metric_value(float("nan")) == "—"
    assert _fmt_metric_value(float("inf")) == "—"
    assert _delta_html(100.0, float("nan")) == ""


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
    rendered_figures: list[go.Figure] = []

    def fake_render_plot_card(title: str, fig: object) -> None:
        rendered_titles.append(title)
        assert isinstance(fig, go.Figure)
        rendered_figures.append(fig)

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
    assert rendered_figures[0].layout.height == 650


def test_plotly_component_height_adds_room_around_fixed_height_figures() -> None:
    """Plotly charts render in a taller Streamlit slot than the figure itself."""
    figure = go.Figure()
    figure.update_layout(height=650)

    assert _plotly_component_height(figure) == 770


def test_plot_card_height_wraps_plotly_component_and_card_chrome() -> None:
    """The outer card grows with the Plotly component it contains."""
    figure = go.Figure()
    figure.update_layout(height=650)

    assert _plot_card_height(figure) == 862


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


def test_component_ids_for_plot_source_handles_missing_component_categories() -> None:
    """HTH plot source selection tolerates configs without category IDs."""

    class ConfigWithoutCategoryIds(_FakeMicrogridConfig):
        """Fake config that returns no PV meter category IDs."""

        def component_type_ids(
            self, component_type: str, component_category: str | None = None
        ) -> list[int] | None:
            if component_type == "pv" and component_category == "meter":
                return None
            return super().component_type_ids(component_type, component_category)

    ids = _component_ids_for_plot_source(
        ConfigWithoutCategoryIds(),
        component_types=["pv"],
        component_plot_source="meter",
    )

    assert ids == {"pv": ()}


def test_default_component_plot_source_prefers_inverters_without_meter_ids() -> None:
    """The default source uses inverters when meter IDs are unavailable."""

    class ConfigWithoutMeterIds(_FakeMicrogridConfig):
        """Fake config that returns no PV meter IDs."""

        def component_type_ids(
            self, component_type: str, component_category: str | None = None
        ) -> list[int] | None:
            if component_type == "pv" and component_category == "meter":
                return None
            return super().component_type_ids(component_type, component_category)

    selected_source = default_component_plot_source(
        ConfigWithoutMeterIds(),
        component_types=["pv"],
        analysis_key="pv",
    )

    assert selected_source == "inverter"


def test_default_component_plot_source_prefers_inverters_with_meterless_data() -> None:
    """The default source uses inverters when meter analysis has no data."""
    selected_source = default_component_plot_source(
        _FakeMicrogridConfig(),
        component_types=["pv"],
        analysis_key="pv",
        source_has_data=lambda source: source == "inverter",
    )

    assert selected_source == "inverter"


def test_battery_optimization_summary_uses_charge_and_discharge_prices() -> None:
    """Battery optimization savings are discharge value minus charge cost."""
    total_savings, daily_summary = calculate_battery_optimization_summary(
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    [
                        "2026-01-01T00:00:00Z",
                        "2026-01-01T00:15:00Z",
                        "2026-01-02T00:00:00Z",
                    ]
                ),
                "battery_power_flow": [4.0, -8.0, -4.0],
                "day_ahead_price": [50.0, 100.0, 200.0],
            }
        ),
        timedelta(minutes=15),
    )

    assert total_savings == pytest.approx(0.35)
    assert daily_summary["optimization_savings_eur"].tolist() == pytest.approx(
        [0.15, 0.2]
    )
    assert daily_summary["battery_charging_kwh"].tolist() == pytest.approx([1.0, 0.0])
    assert daily_summary["battery_discharging_kwh"].tolist() == pytest.approx(
        [2.0, 1.0]
    )


def test_normalized_battery_optimization_metrics_use_throughput_and_spread() -> None:
    """Battery optimization normalization reports throughput value and price spread."""
    metrics = calculate_normalized_battery_optimization_metrics(
        pd.DataFrame(
            {
                "battery_charging_kwh": [1000.0, 500.0],
                "battery_discharging_kwh": [800.0, 700.0],
                "charging_cost_eur": [50.0, 40.0],
                "discharging_value_eur": [120.0, 150.0],
                "optimization_savings_eur": [70.0, 110.0],
            }
        ),
        battery_capacity_kwh=600.0,
    )

    assert metrics["value_per_mwh_throughput"] == pytest.approx(60.0)
    assert metrics["value_per_mwh_discharged"] == pytest.approx(120.0)
    assert metrics["battery_price_spread_eur_per_mwh"] == pytest.approx(120.0)
    assert metrics["value_per_kwh_capacity"] == pytest.approx(0.3)
    assert metrics["battery_cycles"] == pytest.approx(2.5)


def test_normalized_battery_optimization_metrics_handle_missing_throughput() -> None:
    """Battery optimization normalization omits values without battery activity."""
    metrics = calculate_normalized_battery_optimization_metrics(
        pd.DataFrame(
            {
                "battery_charging_kwh": [0.0],
                "battery_discharging_kwh": [0.0],
                "charging_cost_eur": [0.0],
                "discharging_value_eur": [0.0],
                "optimization_savings_eur": [0.0],
            }
        )
    )

    assert metrics["value_per_mwh_throughput"] is None
    assert metrics["value_per_mwh_discharged"] is None
    assert metrics["battery_price_spread_eur_per_mwh"] is None
    assert metrics["value_per_kwh_capacity"] is None
    assert metrics["battery_cycles"] is None


def test_battery_capacity_uses_latest_reporting_metric_sample() -> None:
    """Reporting capacity samples are converted from Wh to kWh without summing."""
    capacity_data = pd.DataFrame(
        {
            "battery_one": [500_000.0, 500_000.0],
            "battery_two": [250_000.0, 250_000.0],
        }
    )

    assert _battery_capacity_kwh_from_metric_data(capacity_data) == pytest.approx(750.0)


def test_battery_optimization_summary_ignores_rows_without_prices() -> None:
    """Rows without day-ahead prices are excluded from monetary calculation."""
    total_savings, daily_summary = calculate_battery_optimization_summary(
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    ["2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"]
                ),
                "battery_power_flow": [4.0, -8.0],
                "day_ahead_price": [None, 100.0],
            }
        ),
        timedelta(minutes=15),
    )

    assert total_savings == pytest.approx(0.2)
    assert daily_summary["optimization_savings_eur"].tolist() == pytest.approx([0.2])


def test_battery_optimization_summary_requires_battery_and_price_columns() -> None:
    """Battery optimization calculation reports missing required inputs."""
    with pytest.raises(ValueError, match="battery_power_flow"):
        calculate_battery_optimization_summary(
            pd.DataFrame(
                {
                    "timestamp": pd.date_range("2026-01-01", periods=1),
                    "day_ahead_price": [100.0],
                }
            ),
            timedelta(minutes=15),
        )


def test_daily_battery_optimization_figure_has_legends_and_euro_labels() -> None:
    """Daily optimization chart renders legend traces and euro value labels."""
    fig = build_daily_battery_optimization_figure(
        pd.DataFrame(
            {
                "date": [date(2026, 1, 1), date(2026, 1, 2)],
                "optimization_savings_eur": [1234.34, -5678.67],
            }
        )
    )

    assert fig.layout.showlegend is True
    assert [trace.name for trace in fig.data] == ["Einsparung", "Kosten"]
    assert "€" in fig.layout.yaxis.title.text
    assert fig.layout.yaxis.tickprefix == "€"
    assert fig.data[0].y[0] == pytest.approx(1234.34)
    assert fig.data[1].y[1] == pytest.approx(-5678.67)
    assert fig.data[0].text[0] == "€1.234"
    assert fig.data[1].text[1] == "-€5.679"


def test_battery_optimization_summary_can_be_aggregated_weekly_and_monthly() -> None:
    """Daily savings summaries can be rolled up for the plot selector."""
    daily_summary = pd.DataFrame(
        {
            "date": [
                date(2026, 1, 1),
                date(2026, 1, 2),
                date(2026, 2, 1),
            ],
            "battery_charging_kwh": [1.0, 2.0, 3.0],
            "battery_discharging_kwh": [4.0, 5.0, 6.0],
            "charging_cost_eur": [0.1, 0.2, 0.3],
            "discharging_value_eur": [0.5, 0.6, 0.7],
            "optimization_savings_eur": [10.0, -2.0, 5.0],
        }
    )

    weekly_summary = aggregate_battery_optimization_summary(daily_summary, "weekly")
    monthly_summary = aggregate_battery_optimization_summary(daily_summary, "monthly")

    assert weekly_summary["optimization_savings_eur"].tolist() == pytest.approx(
        [8.0, 5.0]
    )
    assert monthly_summary["period_label"].tolist() == ["Jan 2026", "Feb 2026"]
    assert monthly_summary["optimization_savings_eur"].tolist() == pytest.approx(
        [8.0, 5.0]
    )


def test_battery_optimization_figure_uses_selected_aggregation() -> None:
    """The plot uses the requested aggregation for its visible bars."""
    fig = build_daily_battery_optimization_figure(
        pd.DataFrame(
            {
                "date": [date(2026, 1, 1), date(2026, 1, 2)],
                "battery_charging_kwh": [1.0, 2.0],
                "battery_discharging_kwh": [2.0, 3.0],
                "charging_cost_eur": [1.0, 2.0],
                "discharging_value_eur": [4.0, 5.0],
                "optimization_savings_eur": [12.34, -5.67],
            }
        ),
        "monthly",
    )

    assert fig.layout.xaxis.title.text == "Monatlich"
    assert fig.data[0].x[0] == "Jan 2026"
    assert fig.data[0].y[0] == pytest.approx(6.67)


def test_normalized_battery_optimization_figure_aggregates_metric_totals() -> None:
    """Normalized charts calculate each period from its aggregated totals."""
    daily_summary = pd.DataFrame(
        {
            "date": [date(2026, 1, 1), date(2026, 1, 2)],
            "battery_charging_kwh": [1000.0, 1000.0],
            "battery_discharging_kwh": [500.0, 1000.0],
            "charging_cost_eur": [50.0, 100.0],
            "discharging_value_eur": [100.0, 300.0],
            "optimization_savings_eur": [50.0, 200.0],
        }
    )

    fig = build_normalized_battery_optimization_figure(
        daily_summary,
        "value_per_mwh_discharged",
        "monthly",
        battery_capacity_kwh=500.0,
    )

    assert fig.layout.xaxis.title.text == "Monatlich"
    assert fig.layout.yaxis.title.text == "Wert pro MWh entladene Energie (€/MWh)"
    assert fig.data[0].x[0] == "Jan 2026"
    assert fig.data[0].y[0] == pytest.approx(250.0 / 1.5)
    assert fig.data[0].text[0] == "€167"


def test_battery_cycles_figure_uses_period_discharge_and_capacity() -> None:
    """Cycle charts aggregate discharged energy before normalizing by capacity."""
    fig = build_normalized_battery_optimization_figure(
        pd.DataFrame(
            {
                "date": [date(2026, 1, 1), date(2026, 1, 2)],
                "battery_discharging_kwh": [200.0, 300.0],
                "optimization_savings_eur": [0.0, 0.0],
            }
        ),
        "battery_cycles",
        "weekly",
        battery_capacity_kwh=500.0,
    )

    assert fig.layout.yaxis.title.text == "Batteriezyklen (Vollzyklen)"
    assert fig.layout.yaxis.tickprefix == ""
    assert fig.data[0].y[0] == pytest.approx(1.0)
    assert fig.data[0].text[0] == "1,00"
