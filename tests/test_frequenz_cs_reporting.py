# pylint: disable=too-many-lines

# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for the frequenz.cs_reporting package."""

from base64 import b64decode
from collections.abc import Callable, Iterable
from concurrent.futures import Future
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
import pytest
import streamlit as st
from frequenz.lib.notebooks.solar.maintenance import plot_manager, plot_styles

from frequenz.cs_reporting.app_pages import (
    battery_optimization as battery_optimization_page,
)
from frequenz.cs_reporting.app_pages.battery_optimization import (
    _SIDEBAR_KEY_PREFIX,
    _completed_price_range_end,
    _mid_caption,
    _previous_week_date,
)
from frequenz.cs_reporting.app_pages.solar import capture_workflow_figures
from frequenz.cs_reporting.components import inputs
from frequenz.cs_reporting.components.sidebar_inputs import _microgrid_option_label
from frequenz.cs_reporting.components.tables import (
    _LOCALE_NUMBER_FORMATTER,
    _csv_download_urls,
)
from frequenz.cs_reporting.components.ui import (
    _plot_card_height,
    _plotly_component_height,
)
from frequenz.cs_reporting.services import client_factory
from frequenz.cs_reporting.services.battery_optimization_calculations import (
    calculate_battery_optimization_intervals,
    calculate_selection_metrics,
)
from frequenz.cs_reporting.services.data_service import (
    _battery_capacity_kwh_from_metric_data,
    _day_ahead_sync_range,
)
from frequenz.cs_reporting.ui_resources import load_tooltips
from frequenz.cs_reporting.utils import time
from frequenz.cs_reporting.views import dashboard, metric_renderers
from frequenz.cs_reporting.views.battery_optimization import (
    _HIDDEN_NORMALIZED_METRICS,
    _KPI_CARDS_PER_ROW,
    _OPERATING_KPI_CARDS_PER_ROW,
    _PRIMARY_PLOT_METRICS,
    _SECONDARY_PLOT_METRICS,
    _build_battery_optimization_kpi_boxes,
    aggregate_battery_optimization_summary,
    build_battery_optimization_results_table,
    build_daily_battery_optimization_figure,
    build_normalized_battery_optimization_figure,
    calculate_battery_optimization_summary,
    calculate_normalized_battery_optimization_metrics,
)
from frequenz.cs_reporting.views.component_sources import default_component_plot_source
from frequenz.cs_reporting.views.dashboard import (
    _aggregate_metrics,
    _filter_component_types_for_master_df,
    _has_current_day_ahead_prices,
    _merge_cached_day_ahead_prices,
    split_periods,
)
from frequenz.cs_reporting.views.metric_renderers import (
    _DELTA_COMPARISONS,
    SECTION_SPECS,
    _build_consumption_breakdown,
    _delta_html,
    _filter_section_box_specs,
    _fmt_metric_value,
    _kpi_label_html,
    _kpi_tooltip_aria_label,
    _kpi_tooltip_content_html,
    _materialize_boxes,
    _prior_period_help_html,
    _skip_missing_day_ahead_price_specs,
)
from frequenz.cs_reporting.views.plot_renderers import (
    _component_ids_for_plot_source,
    _render_overview_plot,
)
from frequenz.cs_reporting.views.table_renderers import _build_core_data_df


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


class _FakeSelectboxContainer:
    """Capture selectbox arguments without rendering a Streamlit widget."""

    def __init__(self) -> None:
        self.format_func: Callable[[int], str] | None = None

    def selectbox(
        self,
        _label: str,
        *,
        options: list[int],
        index: int,
        format_func: Callable[[int], str],
        key: str,
        label_visibility: str,
    ) -> int:
        """Store widget arguments and return the first option."""
        del key, label_visibility
        self.format_func = format_func
        return options[index]


def _decode_csv_data_url(data_url: str) -> str:
    """Decode a base64 CSV data URL for assertions."""
    _, encoded_csv = data_url.split(",", maxsplit=1)
    return b64decode(encoded_csv).decode("utf-8")


def test_core_data_table_contains_requested_columns_in_order() -> None:
    """The compact data table exposes only the requested reporting fields."""
    master_df = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2026-01-01", tz="UTC")],
            "grid_consumption": [1.0],
            "mid_consumption": [2.0],
            "grid_feed_in": [3.0],
            "pv_asset_production": [4.0],
            "production_self_use": [5.0],
            "day_ahead_price": [6.0],
            "unrelated": [7.0],
        }
    )

    core_data = _build_core_data_df(master_df)

    assert list(core_data.columns) == [
        "timestamp",
        "Netzbezug",
        "Gesamtverbrauch",
        "Netz Einspeisung",
        "PV-Erzeugung",
        "production_self_use",
        "Day Ahead Preis",
    ]
    assert core_data.iloc[0].tolist() == list(master_df.iloc[0, :7])


def test_core_data_table_omits_columns_when_source_data_is_unavailable() -> None:
    """Production and price columns are omitted without source data."""
    core_data = _build_core_data_df(
        pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2026-01-01", tz="UTC")],
                "grid_consumption": [1.0],
                "mid_consumption": [2.0],
            }
        )
    )

    assert list(core_data.columns) == [
        "timestamp",
        "Netzbezug",
        "Gesamtverbrauch",
    ]


def test_csv_download_urls_support_german_and_english_formats() -> None:
    """CSV downloads use the delimiter and decimal mark selected by the user."""
    dataframe = pd.DataFrame({"Leistung": [1.5], "Standort": ["Berlin"]})

    urls = _csv_download_urls(dataframe)

    assert set(urls) == {"de", "en"}
    assert _decode_csv_data_url(urls["de"]) == ("Leistung;Standort\n1,5;Berlin\n")
    assert _decode_csv_data_url(urls["en"]) == ("Leistung,Standort\n1.5,Berlin\n")


def test_table_number_formatter_uses_selected_csv_language() -> None:
    """The table and CSV export read their format from the same selection."""
    formatter_code = str(_LOCALE_NUMBER_FORMATTER.js_code)

    assert 'params.api.getGridOption("context")' in formatter_code
    assert "gridContext.csvFormat" in formatter_code
    assert 'language === "en" ? "en-US" : "de-DE"' in formatter_code


def test_microgrid_option_label_includes_configured_name() -> None:
    """A configured microgrid name is displayed beside its ID."""
    assert _microgrid_option_label(243, {243: "Solarlandbau Priegendorf"}) == (
        "243 — Solarlandbau Priegendorf"
    )
    assert _microgrid_option_label(244, {243: "Solarlandbau Priegendorf"}) == "244"


def test_microgrid_selector_uses_custom_option_formatter() -> None:
    """The selector preserves IDs while allowing descriptive option labels."""
    container = _FakeSelectboxContainer()

    selected_id = inputs.microgrid_selector(
        ids=[243],
        format_func=lambda microgrid_id: f"{microgrid_id} — Site name",
        container=container,
    )

    assert selected_id == 243
    assert container.format_func is not None
    assert container.format_func(243) == "243 — Site name"


def test_microgrid_names_prefer_current_assets_api_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only accessible configs are returned, using current Assets API names."""
    client_factory._get_microgrid_names.clear()  # pylint: disable=protected-access
    monkeypatch.setattr(
        client_factory,
        "get_microgrid_config_revision",
        lambda: ("test", (("microgrid.toml", "revision"),)),
    )
    monkeypatch.setattr(
        client_factory,
        "_load_microgrid_configs",
        lambda: {
            243: SimpleNamespace(name="Configured name"),
            244: SimpleNamespace(name="Inaccessible config"),
        },
    )
    monkeypatch.setattr(client_factory, "require_env", lambda _key: "value")

    class FakeAssetsClient:
        """Return a current microgrid name from the Assets API."""

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def list_microgrids(
            self, microgrid_ids: Iterable[int] = ()
        ) -> list[SimpleNamespace]:
            assert not tuple(microgrid_ids)
            return [SimpleNamespace(id=243, name="Current API name")]

        async def disconnect(self) -> None:
            pass

    monkeypatch.setattr(client_factory, "AssetsApiClient", FakeAssetsClient)

    assert client_factory.get_microgrid_names() == {243: "Current API name"}
    assert client_factory.get_microgrid_ids() == [243]
    client_factory._get_microgrid_names.clear()  # pylint: disable=protected-access


def test_static_microgrid_configs_are_discovered_and_loaded_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The TOML catalog remains cached until the Streamlit process cache resets."""
    config_file = tmp_path / "microgrid.toml"
    first_contents = """\
[assets.microgrids.231]
name = "inaccessible"

[assets.microgrids.243]
name = "first"
"""
    second_contents = first_contents.replace('name = "first"', 'name = "second"')
    config_file.write_text(first_contents, encoding="utf-8")
    load_calls: list[str] = []

    async def load_configs(
        *,
        default_files: list[str],
        assets_client: object | None = None,
        microgrid_ids: list[int] | None = None,
    ) -> object:
        assert assets_client is None
        assert microgrid_ids is None
        contents = Path(default_files[0]).read_text(encoding="utf-8")
        load_calls.append(contents)
        return SimpleNamespace(
            microgrids={
                231: SimpleNamespace(name="inaccessible"),
                243: SimpleNamespace(name=contents),
            }
        )

    monkeypatch.setenv("MICROGRID_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(client_factory, "load_configs", load_configs)
    cached_loader = getattr(client_factory, "_load_microgrid_configs_cached")
    cached_source = getattr(client_factory, "_microgrid_config_source_cached")
    load_from_disk = getattr(client_factory, "_load_microgrid_configs")
    cached_loader.clear()
    cached_source.clear()

    first = load_from_disk()
    unchanged = load_from_disk()
    config_file.write_text(second_contents, encoding="utf-8")
    still_cached = load_from_disk()

    cached_loader.clear()
    cached_source.clear()
    after_process_cache_reset = load_from_disk()

    assert first[243].name == first_contents
    assert unchanged is first
    assert still_cached is first
    assert after_process_cache_reset[243].name == second_contents
    assert load_calls == [first_contents, second_contents]
    cached_loader.clear()
    cached_source.clear()


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


def test_battery_optimization_default_start_uses_previous_week() -> None:
    """Battery optimization defaults start date to the previous week."""
    assert _previous_week_date(date(2026, 9, 16)) == date(2026, 9, 9)
    assert _previous_week_date(date(2026, 3, 3)) == date(2026, 2, 24)


def test_battery_optimization_sidebar_uses_page_specific_state() -> None:
    """Battery optimization sidebar state is isolated from reporting filters."""
    assert _SIDEBAR_KEY_PREFIX == "battery_optimization_"


def test_battery_price_sync_excludes_the_incomplete_current_day() -> None:
    """Battery price backfill stops at today's local midnight."""
    sync_end = _completed_price_range_end(
        datetime(2026, 10, 16, 9, 30, tzinfo=UTC),
        "Europe/Berlin",
        date(2026, 10, 16),
    )

    assert sync_end.isoformat() == "2026-10-16T00:00:00+02:00"


def test_day_ahead_sync_range_does_not_request_unpublished_future_prices() -> None:
    """A current-day price sync stops at the latest complete interval."""
    start, end = _day_ahead_sync_range(
        datetime(2026, 9, 15, 22, 0, tzinfo=UTC),
        datetime(2026, 10, 16, 9, 20, tzinfo=UTC),
        now=datetime(2026, 10, 16, 9, 22, tzinfo=UTC),
    )

    assert start == datetime(2026, 9, 15, 22, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 16, 9, 15, tzinfo=UTC)


def test_day_ahead_sync_range_keeps_historical_exclusive_end() -> None:
    """Historical price syncs do not add an unnecessary trailing day."""
    start, end = _day_ahead_sync_range(
        datetime(2026, 9, 15, 22, 0, tzinfo=UTC),
        datetime(2026, 10, 15, 22, 0, tzinfo=UTC),
        now=datetime(2026, 10, 16, 9, 22, tzinfo=UTC),
    )

    assert start == datetime(2026, 9, 15, 22, 0, tzinfo=UTC)
    assert end == datetime(2026, 10, 15, 22, 0, tzinfo=UTC)


def test_battery_optimization_mid_caption_includes_name_and_number() -> None:
    """The page subtitle identifies the selected MID by name and number."""
    assert _mid_caption(243, "Solarlandbau Priegendorf") == (
        "MID243 - Solarlandbau Priegendorf"
    )
    assert _mid_caption(244, None) == ("MID244 - Nicht verfügbar")


def test_battery_optimization_loads_prices_for_the_complete_selected_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The battery page fills prices for the same range as active-power data."""
    selections = {
        "start_date": date(2026, 9, 1),
        "end_date": date(2026, 9, 5),
        "timezone": "UTC",
        "microgrid_id": 243,
        "resolution": "15min",
    }
    power_range: list[datetime] = []
    price_range: list[datetime] = []
    raw_data = pd.DataFrame(
        {"timestamp": pd.date_range("2026-09-01", periods=2, freq="15min")}
    )

    monkeypatch.setattr(
        battery_optimization_page,
        "collect_sidebar_inputs",
        lambda **_kwargs: selections,
    )
    monkeypatch.setattr(
        battery_optimization_page, "get_microgrid_names", lambda: {243: "Test"}
    )
    monkeypatch.setattr(
        battery_optimization_page,
        "get_component_types",
        lambda _microgrid_id: ("battery",),
    )
    monkeypatch.setattr(
        battery_optimization_page,
        "get_battery_capacity_data_kwh",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        battery_optimization_page,
        "get_microgrid_config",
        lambda _microgrid_id: SimpleNamespace(
            ctype={"battery": SimpleNamespace(formula=None)}
        ),
    )

    def get_microgrid_data(
        *,
        microgrid_id: int,
        start_date: datetime,
        end_date: datetime,
        resolution: timedelta,
    ) -> pd.DataFrame:
        del microgrid_id, resolution
        power_range.extend([start_date, end_date])
        return raw_data

    price_future: Future[pd.Series] = Future()
    price_future.set_result(pd.Series(dtype="float64"))

    def start_day_ahead_price_sync(
        _country_code: str, start: datetime, end: datetime
    ) -> Future[pd.Series]:
        price_range.extend([start, end])
        return price_future

    monkeypatch.setattr(
        battery_optimization_page, "get_microgrid_data", get_microgrid_data
    )
    monkeypatch.setattr(
        battery_optimization_page,
        "start_background_day_ahead_price_sync",
        start_day_ahead_price_sync,
    )
    monkeypatch.setattr(
        battery_optimization_page, "build_master_df", lambda *_args, **_kwargs: raw_data
    )
    monkeypatch.setattr(
        battery_optimization_page,
        "split_periods",
        lambda master_df, *_args: (master_df, pd.DataFrame()),
    )
    monkeypatch.setattr(
        battery_optimization_page,
        "render_battery_optimization",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(st, "title", lambda *_args: None)
    monkeypatch.setattr(st, "caption", lambda *_args: None)
    monkeypatch.setattr(st, "spinner", lambda *_args: nullcontext())

    battery_optimization_page.render()

    assert price_range == power_range
    assert price_range[1] - price_range[0] > timedelta(days=2)


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


def test_kpi_delta_colours_follow_metric_comparison_semantics() -> None:
    """KPI delta colours reflect each metric's intended interpretation."""
    assert "kpi-card__delta--neutral" in _delta_html(110.0, 100.0, "neutral")
    assert "kpi-card__delta--positive" in _delta_html(110.0, 100.0, "more_is_good")
    assert "kpi-card__delta--negative" in _delta_html(90.0, 100.0, "more_is_good")


def test_kpi_value_colour_can_be_set_for_one_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A metric-specific value colour is attached only to its KPI card."""
    rendered_markup: list[str] = []

    class FakeColumn:
        """Capture KPI markup rendered into a Streamlit column."""

        def markdown(self, markup: str, *, unsafe_allow_html: bool) -> None:
            assert unsafe_allow_html is True
            rendered_markup.append(markup)

    monkeypatch.setattr(metric_renderers, "_ensure_kpi_css", lambda: None)
    monkeypatch.setattr(
        st,
        "columns",
        lambda count, gap: [FakeColumn() for _ in range(count)],
    )

    metric_renderers.render_box_grid(
        [("Netto-Einsparung (€)", 42.0)],
        per_row=1,
        value_colors={"Netto-Einsparung (€)": "#16a34a"},
    )

    assert "--kpi-value-color:#16a34a;" in rendered_markup[0]


def test_balance_and_battery_kpi_delta_comparisons() -> None:
    """Balance ratios improve when rising; battery flows remain neutral."""
    assert _DELTA_COMPARISONS["Autarkiegrad (%)"] == "more_is_good"
    assert _DELTA_COMPARISONS["Eigenverbrauchsquote (%)"] == "more_is_good"
    assert _DELTA_COMPARISONS["Erzeugung zu Batterie (kWh)"] == "neutral"
    assert _DELTA_COMPARISONS["Netz zu Batterie (kWh)"] == "neutral"
    assert _DELTA_COMPARISONS["Batterie zu Netz (kWh)"] == "neutral"
    assert _DELTA_COMPARISONS["Batterie zu Verbrauch (kWh)"] == "neutral"


def test_prior_period_explanation_is_rendered_as_a_separate_tooltip() -> None:
    """The prior-period help can be placed beside its lower card text."""
    label_html = _kpi_label_html("Netzbezug (kWh)")
    tooltip_html = _prior_period_help_html()

    assert 'class="kpi-card__help"' not in label_html
    assert 'class="kpi-card__help"' in tooltip_html
    assert ">i<span" in tooltip_html
    assert "Vorperiode ist immer derselbe Zeitraum davor" in tooltip_html
    assert "4 ausgewählten Tagen" in tooltip_html


def test_kpi_tooltip_content_renders_heading_sections() -> None:
    """Structured KPI help text renders headings and escaped body copy."""
    tooltip_html = _kpi_tooltip_content_html(
        "Berechnung\nMenge × Preis\n\nBedeutung\nWert der Energie."
    )

    assert tooltip_html.count('class="kpi-card__tooltip-heading"') == 2
    assert ">Berechnung</span>" in tooltip_html
    assert ">Bedeutung</span>" in tooltip_html
    assert "Menge × Preis" in tooltip_html

    plain_html = _kpi_tooltip_content_html("Erste Zeile.\nZweite Zeile.")
    assert plain_html == "Erste Zeile. Zweite Zeile."


def test_multiline_kpi_tooltip_has_a_single_line_aria_label() -> None:
    """Blank lines cannot escape the tooltip's HTML attribute in Markdown."""
    aria_label = _kpi_tooltip_aria_label(
        'Berechnung\nMenge × Preis\n\nBedeutung\nText mit "Anführung".'
    )

    assert "\n" not in aria_label
    assert aria_label == (
        "Berechnung Menge × Preis Bedeutung Text mit &quot;Anführung&quot;."
    )


def test_tooltip_copy_is_loaded_from_the_content_catalogue() -> None:
    """Editable tooltip copy is available from the packaged TOML resource."""
    battery_tooltips = load_tooltips("battery_optimization")

    assert "Berechnung\nJe Viertelstunde" in battery_tooltips["discharging_value_eur"]
    assert (
        "Berechnung\nJe Viertelstunde: geladene Menge *"
        in battery_tooltips["charging_cost_eur"]
    )
    assert (
        "aus dem Netz oder aus Eigenerzeugung stammt"
        in battery_tooltips["charging_cost_eur"]
    )
    assert load_tooltips("common")["prior_period"].startswith("Vorperiode")
    assert "Netzbetreiber" in load_tooltips("reporting")["invoicing_warning"]


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


def test_stale_day_ahead_price_is_not_filled_across_missing_intervals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial Deepnote snapshot remains visibly incomplete and refreshable."""
    timestamps = pd.date_range(
        "2026-10-16 00:00", periods=4, freq="15min", tz="Europe/Berlin"
    )
    master_df = pd.DataFrame({"timestamp": timestamps, "grid_consumption": 1.0})
    cached = pd.Series(
        [191.33],
        index=pd.DatetimeIndex([timestamps[0]]).tz_convert("UTC"),
        name="day_ahead_price",
    )
    monkeypatch.setattr(dashboard, "get_cached_day_ahead_prices", lambda *_args: cached)

    merged = _merge_cached_day_ahead_prices(master_df, "DE_LU")

    assert merged["day_ahead_price"].notna().tolist() == [True, False, False, False]
    assert not _has_current_day_ahead_prices(merged)


def test_overview_plot_renders_without_day_ahead_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The overview plot does not require a secondary price y-axis."""
    rendered_titles: list[str] = []
    rendered_figures: list[go.Figure] = []
    rendered_configs: list[dict[str, object] | None] = []

    def fake_render_plot_card(title: str, fig: object, **kwargs: object) -> None:
        rendered_titles.append(title)
        assert isinstance(fig, go.Figure)
        rendered_figures.append(fig)
        plotly_config = kwargs.get("plotly_config")
        assert plotly_config is None or isinstance(plotly_config, dict)
        rendered_configs.append(plotly_config)

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
    assert rendered_figures[0].layout.xaxis.tickformat == "%a, %d.%m.%Y<br>%H:%M"
    assert rendered_configs == [{"locale": "de"}]


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


def test_battery_optimization_selection_metrics_include_charge_and_discharge_value() -> (
    None
):
    """Selection KPIs expose the charging cost and discharging value totals."""
    intervals = calculate_battery_optimization_intervals(
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    ["2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"]
                ),
                "battery_power_flow": [4.0, -8.0],
                "day_ahead_price": [50.0, 100.0],
            }
        ),
        timedelta(minutes=15),
    )

    metrics = calculate_selection_metrics(intervals)

    assert metrics["charging_cost_eur"] == pytest.approx(0.05)
    assert metrics["discharging_value_eur"] == pytest.approx(0.2)
    assert metrics["battery_charging_kwh"] == pytest.approx(1.0)
    assert metrics["battery_discharging_kwh"] == pytest.approx(2.0)
    assert metrics["battery_efficiency_pct"] == pytest.approx(200.0)


def test_battery_optimization_hides_throughput_card_and_plot() -> None:
    """The battery throughput value is absent from both KPI and plot output."""
    metrics: dict[str, float | None] = {
        "total_savings": 10.0,
        "charging_cost_eur": 20.0,
        "discharging_value_eur": 30.0,
        "battery_charging_kwh": 70.0,
        "battery_discharging_kwh": 80.0,
        "battery_efficiency_pct": 90.0,
        "battery_price_spread_eur_per_mwh": 40.0,
        "value_per_kwh_capacity": 50.0,
        "battery_cycles": 60.0,
    }

    labels = [box[0] for box in _build_battery_optimization_kpi_boxes(metrics)]

    assert "Wert Entladung (€)" in labels
    assert "Wert Beladung (€)" in labels
    assert not any("Batteriedurchsatz" in label for label in labels)
    assert "value_per_mwh_throughput" in _HIDDEN_NORMALIZED_METRICS
    assert _KPI_CARDS_PER_ROW == 4
    assert labels[:_KPI_CARDS_PER_ROW][-1] == "Preis-Spread Batterie (€/MWh)"
    assert labels[_KPI_CARDS_PER_ROW:] == [
        "Batteriezyklen (Vollzyklen)",
        "Wirkungsgrad (%)",
        "Entladene Menge (kWh)",
        "Geladene Menge (kWh)",
        "Wert pro kWh Batteriekapazität (€/kWh)",
    ]
    assert _OPERATING_KPI_CARDS_PER_ROW == 4
    assert _PRIMARY_PLOT_METRICS == ("battery_price_spread_eur_per_mwh",)
    assert _SECONDARY_PLOT_METRICS == (
        "value_per_kwh_capacity",
        "battery_cycles",
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


def test_battery_optimization_results_table_includes_interval_inputs_and_calculations() -> (
    None
):
    """Export data contains timestamped source values and interval calculations."""
    results = build_battery_optimization_results_table(
        pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2026-01-01T00:00:00Z")],
                "grid_consumption": [100.0],
                "mid_consumption": [120.0],
                "pv_asset_production": [20.0],
                "wind_asset_production": [30.0],
                "chp_asset_production": [10.0],
                "battery_power_flow": [400.0],
                "day_ahead_price": [50.0],
            }
        ),
        timedelta(minutes=15),
        battery_capacity_kwh=500.0,
    )

    assert results.columns.tolist() == [
        "Zeitpunkt",
        "Netzbezug (kW)",
        "Gesamtverbrauch (kW)",
        "Gesamterzeugung (kW)",
        "PV-Erzeugung (kW)",
        "Wind-Erzeugung (kW)",
        "KWK-Erzeugung (kW)",
        "Batterieleistungsfluss (kW)",
        "Day-Ahead-Preis (€/MWh)",
        "Geladene Energie (kWh)",
        "Entladene Energie (kWh)",
        "Batteriedurchsatz (kWh)",
        "Day-Ahead-Preis verfügbar",
        "Ladekosten (€)",
        "Entladewert (€)",
        "Netto-Einsparung (€)",
        "Batteriekapazität (kWh)",
        "Batteriezyklen (Vollzyklen)",
    ]
    assert results.loc[0, "Zeitpunkt"] == pd.Timestamp("2026-01-01T00:00:00Z")
    assert results.loc[0, "Gesamterzeugung (kW)"] == pytest.approx(60.0)
    assert results.loc[0, "Geladene Energie (kWh)"] == pytest.approx(100.0)
    assert results.loc[0, "Ladekosten (€)"] == pytest.approx(5.0)


def test_battery_optimization_results_table_is_timestamp_descending() -> None:
    """Interval export always starts with the newest timestamp."""
    results = build_battery_optimization_results_table(
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    ["2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"]
                ),
                "battery_power_flow": [0.0, 0.0],
                "day_ahead_price": [50.0, 50.0],
            }
        ),
        timedelta(minutes=15),
    )

    assert results["Zeitpunkt"].tolist() == [
        pd.Timestamp("2026-01-01T00:15:00Z"),
        pd.Timestamp("2026-01-01T00:00:00Z"),
    ]


def test_interval_calculations_use_nearest_capacity_before_first_sample() -> None:
    """Capacity stays available when the first sample follows the date-range start."""
    intervals = calculate_battery_optimization_intervals(
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(
                    ["2026-01-01T00:15:00Z", "2026-01-01T00:00:00Z"]
                ),
                "battery_power_flow": [-4.0, -4.0],
                "day_ahead_price": [50.0, 50.0],
            }
        ),
        timedelta(minutes=15),
        pd.DataFrame(
            {
                "timestamp": pd.to_datetime(["2026-01-01T00:15:00Z"]),
                "battery_capacity_kwh": [500.0],
            }
        ),
    )

    assert intervals["battery_capacity_kwh"].tolist() == [500.0, 500.0]


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


def test_daily_battery_optimization_figure_combines_value_bars_and_result_line() -> (
    None
):
    """Charging/discharging values are grouped bars and savings is a point line."""
    fig = build_daily_battery_optimization_figure(
        pd.DataFrame(
            {
                "date": [date(2026, 1, 1), date(2026, 1, 2)],
                "charging_cost_eur": [1000.0, 2000.0],
                "discharging_value_eur": [2234.34, -3678.67],
                "optimization_savings_eur": [1234.34, -5678.67],
            }
        )
    )

    assert fig.layout.showlegend is True
    assert [trace.name for trace in fig.data] == [
        "Wert Entladung",
        "Wert Beladung",
        "Netto-Einsparung",
    ]
    assert [trace.type for trace in fig.data] == ["bar", "bar", "scatter"]
    assert fig.layout.barmode == "group"
    assert "€" in fig.layout.yaxis.title.text
    assert fig.layout.yaxis.tickprefix == "€"
    assert fig.data[0].y[0] == pytest.approx(2234.34)
    assert fig.data[1].y[0] == pytest.approx(1000.0)
    assert fig.data[2].y[1] == pytest.approx(-5678.67)
    assert fig.data[2].mode == "lines+markers"
    assert fig.data[0].text[0] == "€2.234"
    assert fig.data[1].text[1] == "€2.000"
    assert fig.data[0].textangle == -90
    assert fig.data[1].textangle == -90
    assert fig.data[0].cliponaxis is False
    assert fig.data[1].cliponaxis is False
    assert fig.layout.uniformtext.mode == "show"
    assert fig.data[0].marker.color == "rgba(146,219,68,1)"
    assert fig.data[1].marker.color == "rgba(236,0,140,1)"
    assert fig.data[2].line.color == "rgba(100,116,139,1)"


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
    assert fig.data[0].y[0] == pytest.approx(9.0)
    assert fig.data[1].y[0] == pytest.approx(3.0)
    assert fig.data[2].y[0] == pytest.approx(6.67)


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

    capacity_fig = build_normalized_battery_optimization_figure(
        daily_summary,
        "value_per_kwh_capacity",
        "monthly",
        battery_capacity_kwh=500.0,
    )
    assert capacity_fig.data[0].text[0] == "€0,50"


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
    assert fig.data[0].y[0] == pytest.approx(0.5)
    assert fig.data[0].text[0] == "0,50"
