# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for the frequenz.cs_reporting package."""

from base64 import b64decode
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
import pytest
from frequenz.lib.notebooks.solar.maintenance import plot_manager, plot_styles

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
from frequenz.cs_reporting.utils import time
from frequenz.cs_reporting.views import dashboard
from frequenz.cs_reporting.views.component_sources import default_component_plot_source
from frequenz.cs_reporting.views.dashboard import (
    _aggregate_metrics,
    _filter_component_types_for_master_df,
    split_periods,
)
from frequenz.cs_reporting.views.metric_renderers import (
    _DELTA_COMPARISONS,
    SECTION_SPECS,
    _build_consumption_breakdown,
    _delta_html,
    _filter_section_box_specs,
    _kpi_label_html,
    _materialize_boxes,
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
    ) -> int:
        """Store widget arguments and return the first option."""
        del key
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


def test_balance_and_battery_kpi_delta_comparisons() -> None:
    """Balance ratios improve when rising; battery flows remain neutral."""
    assert _DELTA_COMPARISONS["Autarkiegrad (%)"] == "more_is_good"
    assert _DELTA_COMPARISONS["Eigenverbrauchsquote (%)"] == "more_is_good"
    assert _DELTA_COMPARISONS["Erzeugung zu Batterie (kWh)"] == "neutral"
    assert _DELTA_COMPARISONS["Netz zu Batterie (kWh)"] == "neutral"
    assert _DELTA_COMPARISONS["Batterie zu Netz (kWh)"] == "neutral"
    assert _DELTA_COMPARISONS["Batterie zu Verbrauch (kWh)"] == "neutral"


def test_kpi_label_includes_prior_period_explanation() -> None:
    """Every KPI label carries the compact prior-period help tooltip."""
    label_html = _kpi_label_html("Netzbezug (kWh)")

    assert 'class="kpi-card__help"' in label_html
    assert ">?<span" in label_html
    assert "Vorperiode ist immer derselbe Zeitraum davor" in label_html
    assert "4 ausgewählten Tagen" in label_html


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
