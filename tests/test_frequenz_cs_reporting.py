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
from typing import cast

import pandas as pd
import plotly.graph_objects as go
import pytest
import streamlit as st
from frequenz.lib.notebooks.reporting.utils.column_mapper import ColumnMapper
from frequenz.lib.notebooks.solar.maintenance import plot_manager, plot_styles

from frequenz.cs_reporting.app_pages import (
    battery_optimization as battery_optimization_page,
)
from frequenz.cs_reporting.app_pages.battery_optimization import (
    _completed_price_range_end,
    _mid_caption,
)
from frequenz.cs_reporting.app_pages.solar import capture_workflow_figures
from frequenz.cs_reporting.components import inputs
from frequenz.cs_reporting.components.sidebar_inputs import (
    _default_reporting_date_range,
    _microgrid_option_label,
    _reconcile_microgrid_selection,
    _restore_reporting_widget_state,
)
from frequenz.cs_reporting.components.tables import (
    _LOCALE_NUMBER_FORMATTER,
    _csv_download_urls,
)
from frequenz.cs_reporting.components.ui import (
    _plot_card_height,
    _plotly_component_height,
)
from frequenz.cs_reporting.constants import TablesResult
from frequenz.cs_reporting.services import client_factory
from frequenz.cs_reporting.services.battery_optimization_calculations import (
    build_battery_optimization_results_table,
    calculate_battery_optimization_intervals,
    calculate_selection_metrics,
)
from frequenz.cs_reporting.services.data_service import (
    _battery_capacity_kwh_from_metric_data,
    _day_ahead_sync_range,
)
from frequenz.cs_reporting.ui_resources import load_tooltips
from frequenz.cs_reporting.utils import time
from frequenz.cs_reporting.views import (
    dashboard,
    metric_renderers,
)
from frequenz.cs_reporting.views import sections as reporting_sections
from frequenz.cs_reporting.views import (
    table_renderers,
)
from frequenz.cs_reporting.views.battery_optimization import (
    _BATTERY_PLOT_FRAGMENT_RENDERERS,
    _HIDDEN_NORMALIZED_METRICS,
    _KPI_CARDS_PER_ROW,
    _OPERATING_KPI_CARDS_PER_ROW,
    _PRIMARY_PLOT_METRICS,
    _SECONDARY_PLOT_METRICS,
    _build_battery_optimization_kpi_boxes,
    _render_battery_optimization_plot_tabs,
    aggregate_battery_optimization_summary,
    build_daily_battery_optimization_figure,
    build_normalized_battery_optimization_figure,
    calculate_battery_optimization_summary,
    calculate_normalized_battery_optimization_metrics,
)
from frequenz.cs_reporting.views.component_sources import default_component_plot_source
from frequenz.cs_reporting.views.dashboard import (
    _PRICE_SYNC_RERUN_STATE_KEY,
    _aggregate_metrics,
    _filter_component_types_for_master_df,
    _has_current_day_ahead_prices,
    _merge_cached_day_ahead_prices,
    _render_day_ahead_price_sync_status,
    split_periods,
)
from frequenz.cs_reporting.views.metric_renderers import (
    _DELTA_COMPARISONS,
    SECTION_SPECS,
    _build_consumption_breakdown,
    _card_html,
    _box_grid_html,
    _delta_html,
    _filter_available_optional_metric_specs,
    _filter_section_box_specs,
    _fmt_metric_value,
    _kpi_label_html,
    _kpi_tooltip_aria_label,
    _kpi_tooltip_content_html,
    _materialize_boxes,
    _prior_period_help_html,
)
from frequenz.cs_reporting.views.plot_renderers import (
    _component_ids_for_plot_source,
    _render_overview_plot,
)
from frequenz.cs_reporting.views.table_renderers import (
    _build_core_data_df,
    _filter_export_dates,
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


def test_data_export_uses_focused_export_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The export page renders the same predefined datasets as Reporting."""
    master_df = pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-01")]})
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        dashboard,
        "_filter_component_types_for_master_df",
        lambda component_types, _master_df: component_types,
    )
    monkeypatch.setattr(dashboard, "_has_current_day_ahead_prices", lambda _df: True)
    export_tables = {"power_table": pd.DataFrame()}
    monkeypatch.setattr(
        dashboard,
        "_build_tables",
        lambda *_args: export_tables,
    )

    def capture_data_export(*args: object) -> None:
        captured["args"] = args

    monkeypatch.setattr(reporting_sections, "render_data_export", capture_data_export)

    mapper = ColumnMapper.from_default()
    dashboard.render_data_export(
        master_df,
        timedelta(minutes=15),
        ["pv"],
        mapper,
    )

    assert captured["args"] == (
        master_df,
        mapper,
        export_tables,
        timedelta(minutes=15),
    )


def test_data_export_date_filter_is_inclusive() -> None:
    """A custom export range applies to all rows, including both endpoints."""
    dataframe = pd.DataFrame(
        {
            "Zeitpunkt": pd.to_datetime(
                ["2026-01-01T00:00:00Z", "2026-01-02T12:00:00Z", "2026-01-03T00:00:00Z"]
            ),
            "value": [1, 2, 3],
        }
    )

    filtered = _filter_export_dates(
        dataframe,
        date(2026, 1, 2),
        date(2026, 1, 3),
    )

    assert list(filtered["value"]) == [2, 3]


def test_core_data_table_contains_requested_columns_in_order() -> None:
    """The compact data table exposes only the requested reporting fields."""
    master_df = pd.DataFrame(
        {
            "timestamp": [pd.Timestamp("2026-01-01", tz="UTC")],
            "grid_consumption": [1.0],
            "dso_import_power": [2.0],
            "dso_export_power": [3.0],
            "mid_consumption": [4.0],
            "grid_feed_in": [5.0],
            "pv_asset_production": [6.0],
            "production_self_use": [7.0],
            "production_to_battery": [8.0],
            "grid_to_battery": [9.0],
            "battery_to_grid": [10.0],
            "battery_to_consumption": [11.0],
            "day_ahead_price": [12.0],
            "unrelated": [13.0],
        }
    )

    core_data = _build_core_data_df(master_df, ColumnMapper.from_default())

    assert list(core_data.columns) == [
        "Zeitpunkt",
        "Netzbezug",
        "DSO Netzbezug (kW)",
        "DSO Netzeinspeisung (kW)",
        "MID Gesamtverbrauch",
        "Netz Einspeisung",
        "PV-Erzeugung",
        "Eigenverbrauch",
        "Erzeugung zu Batterie",
        "Netz zu Batterie",
        "Batterie zu Netz",
        "Batterie zu Verbrauch",
        "Day Ahead Preis",
    ]
    assert core_data.iloc[0].tolist() == list(master_df.iloc[0, :13])


def test_core_data_table_omits_columns_when_source_data_is_unavailable() -> None:
    """Production and price columns are omitted without source data."""
    core_data = _build_core_data_df(
        pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2026-01-01", tz="UTC")],
                "grid_consumption": [1.0],
                "mid_consumption": [2.0],
            }
        ),
        ColumnMapper.from_default(),
    )

    assert list(core_data.columns) == [
        "Zeitpunkt",
        "Netzbezug",
        "MID Gesamtverbrauch",
    ]


def test_data_table_specs_render_after_overview_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Analysis tables do not render inside the two overview tabs."""
    active_tab: list[int] = []
    rendered: list[tuple[str, int]] = []

    class FakeTab:
        """Track which fake Streamlit tab is active."""

        def __init__(self, index: int) -> None:
            self.index = index

        def __enter__(self) -> None:
            active_tab.append(self.index)

        def __exit__(self, *_args: object) -> None:
            active_tab.pop()

    monkeypatch.setattr(
        st,
        "tabs",
        lambda labels, **_kwargs: [
            FakeTab(index) for index, _label in enumerate(labels)
        ],
    )
    monkeypatch.setattr(
        table_renderers,
        "_table_spec_has_data",
        lambda spec, *_args: spec["table_key"] in {"power_table", "pv_energy_table"},
    )
    monkeypatch.setattr(
        table_renderers,
        "render_core_data",
        lambda *_args: rendered.append(("core", active_tab[-1])),
    )
    monkeypatch.setattr(
        table_renderers,
        "render_master_df",
        lambda *_args: rendered.append(("master", active_tab[-1])),
    )
    monkeypatch.setattr(
        table_renderers,
        "render_table_section",
        lambda _value, **kwargs: rendered.append(
            (str(kwargs["key_prefix"]), active_tab[-1])
        ),
    )

    table_renderers.render_data_tabs(
        master_df=pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-01")]}),
        tables_dict=cast(
            TablesResult,
            {
                "power_table": pd.DataFrame({"value": [1.0]}),
                "pv_energy_table": pd.DataFrame({"value": [2.0]}),
            },
        ),
        mapper=object(),  # type: ignore[arg-type]
        mcfg=None,
        component_types=(),
    )

    assert rendered == [
        ("core", 0),
        ("master", 1),
        ("power_mix", 2),
        ("pv_energy", 3),
    ]


def test_data_tables_can_render_stacked_without_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The export layout presents every available dataset in sequence."""
    headings: list[str] = []
    rendered: list[str] = []

    monkeypatch.setattr(
        st,
        "tabs",
        lambda *_args, **_kwargs: pytest.fail("stacked tables must not use tabs"),
    )
    monkeypatch.setattr(st, "subheader", headings.append)
    monkeypatch.setattr(
        table_renderers,
        "_table_spec_has_data",
        lambda spec, *_args: spec["table_key"] == "power_table",
    )
    monkeypatch.setattr(
        table_renderers,
        "render_core_data",
        lambda *_args: rendered.append("core"),
    )
    monkeypatch.setattr(
        table_renderers,
        "render_master_df",
        lambda *_args: rendered.append("master"),
    )
    monkeypatch.setattr(
        table_renderers,
        "render_table_section",
        lambda _value, **kwargs: rendered.append(str(kwargs["key_prefix"])),
    )

    table_renderers.render_data_tabs(
        master_df=pd.DataFrame({"timestamp": [pd.Timestamp("2026-01-01")]}),
        tables_dict=cast(
            TablesResult,
            {"power_table": pd.DataFrame({"value": [1.0]})},
        ),
        mapper=object(),  # type: ignore[arg-type]
        mcfg=None,
        component_types=(),
        stacked=True,
    )

    assert headings == ["Kerndaten", "Gesamt-Datensatz", "Leistungsmix"]
    assert rendered == ["core", "master", "power_mix"]


def test_data_table_prepares_both_sources_for_fragment_switching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Meter and inverter tables are passed to the isolated table fragment."""
    rendered_source_keys: list[set[str]] = []

    class FakeTab:
        """Provide the context-manager interface expected by Streamlit tabs."""

        def __enter__(self) -> None:
            return None

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(
        table_renderers,
        "TABLE_TAB_SPECS",
        [
            {
                "label": "PV-Analyse",
                "table_key": "pv_analysis",
                "analysis_key": "pv",
                "key_prefix": "pv_analysis",
                "caption": "PV-Energieerzeugung (Zeitreihe)",
                "empty_info": "Keine PV-Analysedaten verfügbar.",
            }
        ],
    )
    monkeypatch.setattr(
        st,
        "tabs",
        lambda _labels, **_kwargs: [FakeTab()],
    )
    monkeypatch.setattr(table_renderers, "_table_spec_has_data", lambda *_args: True)

    monkeypatch.setattr(
        table_renderers,
        "_component_analysis_table_for_source",
        lambda *_args: pd.DataFrame({"value": [1.0]}),
    )
    monkeypatch.setattr(
        table_renderers,
        "render_component_source_table",
        lambda frames, **_kwargs: rendered_source_keys.append(set(frames)),
    )

    table_renderers.render_data_tabs(
        master_df=pd.DataFrame(),
        tables_dict=cast(TablesResult, {}),
        mapper=object(),  # type: ignore[arg-type]
        mcfg=None,
        component_types=("pv",),
    )

    assert rendered_source_keys == [{"meter", "inverter"}]


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
    """The microgrid list and names come directly from the Assets API."""
    client_factory._get_microgrid_names.clear()  # pylint: disable=protected-access
    monkeypatch.setattr(client_factory, "require_env", lambda _key: "value")

    class FakeAssetsClient:
        """Return the microgrid list and names from the Assets API."""

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def list_microgrids(
            self, microgrid_ids: Iterable[int] = ()
        ) -> list[SimpleNamespace]:
            assert not tuple(microgrid_ids)
            return [
                SimpleNamespace(
                    id=243,
                    name="Current API name",
                    enterprise_id=7,
                )
            ]

        async def disconnect(self) -> None:
            pass

    monkeypatch.setattr(client_factory, "AssetsApiClient", FakeAssetsClient)

    assert client_factory.get_microgrid_names() == {243: "Current API name"}
    assert getattr(client_factory, "_ENTERPRISE_IDS") == {243: 7}
    # Simulate a process-local reset while the Streamlit data cache survives.
    getattr(client_factory, "_ENTERPRISE_IDS").clear()
    assert client_factory.get_microgrid_names() == {243: "Current API name"}
    assert getattr(client_factory, "_ENTERPRISE_IDS") == {243: 7}
    assert client_factory.get_microgrid_ids() == [243]
    client_factory._get_microgrid_names.clear()  # pylint: disable=protected-access


def test_microgrid_names_refresh_when_api_credentials_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing integration secrets invalidates accessible microgrid names."""
    client_factory._get_microgrid_names.clear()  # pylint: disable=protected-access
    credentials = {
        "ASSETS_API_URL": "https://assets.example.com",
        "FREQUENZ_API_KEY": "first-key",
        "FREQUENZ_API_SECRET": "first-secret",
    }
    monkeypatch.setattr(client_factory, "require_env", credentials.__getitem__)
    api_calls: list[str] = []

    class FakeAssetsClient:
        """Return microgrids belonging to the supplied API key."""

        def __init__(
            self,
            _url: str,
            *,
            auth_key: str,
            sign_secret: str,
        ) -> None:
            del sign_secret
            self.auth_key = auth_key

        async def list_microgrids(self) -> list[SimpleNamespace]:
            api_calls.append(self.auth_key)
            microgrid_id = 243 if self.auth_key == "first-key" else 244
            return [SimpleNamespace(id=microgrid_id, name=self.auth_key)]

        async def disconnect(self) -> None:
            pass

    monkeypatch.setattr(client_factory, "AssetsApiClient", FakeAssetsClient)

    assert client_factory.get_microgrid_names() == {243: "first-key"}
    credentials["FREQUENZ_API_KEY"] = "second-key"
    credentials["FREQUENZ_API_SECRET"] = "second-secret"
    assert client_factory.get_microgrid_names() == {244: "second-key"}
    assert api_calls == ["first-key", "second-key"]
    client_factory._get_microgrid_names.clear()  # pylint: disable=protected-access


def test_invalid_microgrid_session_selection_is_reconciled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A credential change replaces unavailable widget and applied selections."""
    monkeypatch.setattr(
        st,
        "session_state",
        {
            "reporting_microgrid_id": 243,
            "reporting_applied_filters": {
                "microgrid_id": 243,
                "resolution": "15min",
            },
        },
    )

    _reconcile_microgrid_selection(
        [244, 245],
        "reporting_",
        "reporting_applied_filters",
    )

    assert st.session_state["reporting_microgrid_id"] == 244
    assert st.session_state["reporting_applied_filters"] == {
        "microgrid_id": 244,
        "resolution": "15min",
    }


def test_microgrid_config_loads_only_files_defining_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the TOML files defining the selected microgrid are loaded, once."""
    (tmp_path / "a.toml").write_text(
        '[assets.microgrids.231]\nname = "other"\n', encoding="utf-8"
    )
    (tmp_path / "b.toml").write_text(
        '[assets.microgrids.243]\nname = "wanted"\n', encoding="utf-8"
    )
    (tmp_path / "dotted.toml").write_text(
        'assets.microgrids.555.meta.name = "dotted"\n', encoding="utf-8"
    )
    (tmp_path / "legacy.toml").write_text(
        '# legacy\n86.meta.name = "legacy"\n', encoding="utf-8"
    )
    load_calls: list[list[str]] = []

    async def load_configs(*, default_files: list[str]) -> object:
        load_calls.append([Path(file).name for file in default_files])
        return SimpleNamespace(microgrids={243: SimpleNamespace(name="wanted")})

    monkeypatch.setenv("MICROGRID_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(client_factory, "load_configs", load_configs)
    cached_config = getattr(client_factory, "_load_microgrid_config_cached")
    cached_index = getattr(client_factory, "_microgrid_file_index_cached")
    cached_source = getattr(client_factory, "_microgrid_config_source_cached")
    load_config = getattr(client_factory, "_load_microgrid_config")
    for cache in (cached_config, cached_index, cached_source):
        cache.clear()

    index_calls: list[None] = []
    first = load_config(243)
    assert load_config(243) is first
    with pytest.raises(KeyError):
        load_config(999)
    index = getattr(client_factory, "_microgrid_file_index_cached")(
        getattr(client_factory, "_microgrid_config_source")()[0]
    )
    assert index[555] == (str(tmp_path.resolve() / "dotted.toml"),)
    assert index.get(86) == (str(tmp_path.resolve() / "legacy.toml"),)

    assert load_calls == [["b.toml"]]

    # With the enterprise ID known, the file is opened directly without a scan.
    (tmp_path / "eid7.toml").write_text(
        "assets.microgrids.777.name = 'direct'\n", encoding="utf-8"
    )
    monkeypatch.setitem(getattr(client_factory, "_ENTERPRISE_IDS"), 777, 7)
    getattr(client_factory, "_ENTERPRISE_FILES").clear()

    def empty_microgrid_index(*_args: object) -> dict[object, object]:
        """Record that the fallback index would have been used."""
        index_calls.append(None)
        return {}

    monkeypatch.setattr(
        client_factory,
        "_microgrid_file_index_cached",
        empty_microgrid_index,
    )
    # Only existence is checked; no file content is read for the lookup.
    assert getattr(client_factory, "_enterprise_config_files")(777) == (
        str((tmp_path / "eid7.toml").resolve()),
    )
    assert not index_calls
    for cache in (cached_config, cached_index, cached_source):
        cache.clear()


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


def test_reporting_sidebar_defaults_to_previous_week() -> None:
    """All reporting pages initially show the previous week."""
    assert _default_reporting_date_range(date(2026, 9, 16)) == (
        date(2026, 9, 9),
        date(2026, 9, 16),
    )


def test_reporting_sidebar_restores_last_applied_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reporting pages rebuild their widgets from shared durable state."""
    applied_filters = {
        "microgrid_id": 243,
        "start_date": date(2026, 9, 9),
        "end_date": date(2026, 9, 16),
        "timezone": "Europe/Berlin",
        "resolution": "30min",
    }
    monkeypatch.setattr(
        st,
        "session_state",
        {"reporting_applied_filters": applied_filters},
    )

    _restore_reporting_widget_state()

    assert st.session_state == {
        "reporting_applied_filters": applied_filters,
        "reporting_microgrid_id": 243,
        "reporting_start_date": date(2026, 9, 9),
        "reporting_end_date": date(2026, 9, 16),
        "reporting_timezone": "Europe/Berlin",
        "reporting_resolution": "30min",
    }


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


def test_battery_optimization_clears_previous_report_before_filter_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A new filter run removes KPI cards before waiting for fresh data."""
    selections = {
        "start_date": date(2026, 9, 1),
        "end_date": date(2026, 9, 5),
        "timezone": "UTC",
        "microgrid_id": 243,
        "resolution": "15min",
    }
    events: list[str] = []

    class ReportPlaceholder:
        """Record when the previous report is cleared and reused."""

        def empty(self) -> None:
            events.append("clear")

        def container(self) -> nullcontext[None]:
            return nullcontext()

    class FilterRunStopped(Exception):
        """Stand in for Streamlit's control-flow exception."""

    pending_price_sync: Future[pd.Series] = Future()

    def start_price_sync(*_args: object) -> Future[pd.Series]:
        events.append("sync")
        return pending_price_sync

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
        "start_background_day_ahead_price_sync",
        start_price_sync,
    )
    monkeypatch.setattr(st, "title", lambda *_args: None)
    monkeypatch.setattr(st, "caption", lambda *_args: None)
    monkeypatch.setattr(st, "empty", ReportPlaceholder)
    monkeypatch.setattr(
        battery_optimization_page,
        "_poll_day_ahead_price_sync",
        lambda _future: events.append("poll"),
    )

    def stop() -> None:
        events.append("stop")
        raise FilterRunStopped

    monkeypatch.setattr(st, "stop", stop)

    with pytest.raises(FilterRunStopped):
        battery_optimization_page.render()

    assert events == ["clear", "sync", "poll", "stop"]


def test_kpi_formatter_treats_non_finite_values_as_missing() -> None:
    """Missing numeric aggregates do not break the reporting dashboard."""
    assert _fmt_metric_value(float("nan")) == "—"
    assert _fmt_metric_value(float("inf")) == "—"
    assert _delta_html(100.0, float("nan")) == ""


def test_battery_kpi_section_is_temporarily_hidden() -> None:
    """Battery KPI cards remain disabled until they are explicitly restored."""
    assert not any(
        section["title"] == "Batteriekennzahlen" for section in SECTION_SPECS
    )


def test_total_production_kpi_is_hidden_for_one_production_source() -> None:
    """A single production source is not duplicated by Gesamterzeugung."""
    production_section = next(
        section
        for section in SECTION_SPECS
        if section["title"] == "(Eigen-)Erzeugungskennzahlen"
    )

    box_specs = _filter_section_box_specs(
        production_section,
        component_type_set={"grid", "pv"},
        component_types_provided=True,
        microgrid_id=123,
    )

    assert [spec.get("key") for spec in box_specs] == ["pv_production_sum"]


def test_total_production_kpi_is_shown_for_multiple_production_sources() -> None:
    """Gesamterzeugung is useful when multiple production sources contribute."""
    production_section = next(
        section
        for section in SECTION_SPECS
        if section["title"] == "(Eigen-)Erzeugungskennzahlen"
    )

    box_specs = _filter_section_box_specs(
        production_section,
        component_type_set={"grid", "pv", "wind"},
        component_types_provided=True,
        microgrid_id=123,
    )

    assert [spec.get("key") for spec in box_specs] == [
        "total_production_sum",
        "pv_production_sum",
        "wind_production_sum",
    ]


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


def test_kpi_cards_temporarily_hide_previous_period_and_percentage_delta() -> None:
    """The retained comparison data is intentionally not displayed in KPI cards."""
    markup = _card_html(
        "Netzbezug (kWh)",
        110.0,
        100.0,
        None,
        "#3b82f6",
        _DELTA_COMPARISONS,
        None,
    )

    assert "Vorperiode:" not in markup
    assert "kpi-card__previous" not in markup
    assert "kpi-card__delta" not in markup


def test_kpi_value_colour_can_be_set_for_one_metric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A metric-specific value colour is attached only to its KPI card."""
    rendered_markup: list[str] = []

    monkeypatch.setattr(metric_renderers, "_ensure_kpi_css", lambda: None)

    def capture_markup(markup: str, *, unsafe_allow_html: bool) -> None:
        assert unsafe_allow_html is True
        rendered_markup.append(markup)

    monkeypatch.setattr(st, "markdown", capture_markup)

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


def test_day_ahead_price_kpi_specs_are_shown_for_every_microgrid() -> None:
    """Day-ahead price KPI boxes are not limited to selected microgrids."""
    grid_section = next(
        section for section in SECTION_SPECS if section["title"] == "Netzkennzahlen"
    )
    box_specs = _filter_section_box_specs(
        grid_section,
        component_type_set={"grid"},
        component_types_provided=True,
        microgrid_id=123,
    )

    assert [spec.get("key") for spec in box_specs] == [
        "grid_consumption_sum",
        "grid_import_cost_sum",
        "average_da_price_grid_import",
        "grid_feed_in_sum",
        "grid_feed_in_revenue_sum",
        "average_da_price_grid_feed_in",
        "peak",
        "dso_import_energy_sum",
        "dso_export_energy_sum",
    ]


def test_grouped_kpi_cards_keep_grid_costs_and_prices_below_their_flow() -> None:
    """Import and feed-in KPI groups are rendered as independent vertical stacks."""
    markup = _box_grid_html(
        [
            ("Netzbezug (kWh)", 1.0),
            ("Prognostizierte Netzbezugskosten (€)", 2.0),
            ("Prognostizierter Preis (ct/kWh)", 3.0),
            ("Netzeinspeisung (kWh)", 4.0),
            ("Prognostizierte Einspeiseerloese (€)", 5.0),
            ("Prognostizierter Preis (ct/kWh)", 6.0),
        ],
        "#3b82f6",
        None,
        groups=["import", "import", "import", "feed-in", "feed-in", "feed-in"],
    )

    assert markup.count('class="kpi-card-stack"') == 2
    import_start = markup.index("Netzbezug")
    assert import_start < markup.index("Prognostizierte Netzbezugskosten")
    assert markup.index("Prognostizierte Netzbezugskosten") < markup.index(
        "Prognostizierter Preis"
    )
    feed_in_start = markup.index("Netzeinspeisung")
    assert feed_in_start < markup.index("Prognostizierte Einspeiseerloese")


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


def test_completed_price_sync_triggers_only_one_full_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial completed price sync cannot cause an infinite rerun loop."""
    future: Future[pd.Series] = Future()
    future.set_result(pd.Series([100.0], dtype="float64"))
    reruns: list[None] = []
    reuse_requests: list[None] = []
    warnings: list[str] = []
    monkeypatch.setattr(st, "session_state", {})
    monkeypatch.setattr(
        dashboard, "start_background_day_ahead_price_sync", lambda *_args: future
    )
    monkeypatch.setattr(
        dashboard, "request_reporting_data_reuse", lambda: reuse_requests.append(None)
    )
    monkeypatch.setattr(st, "rerun", lambda: reruns.append(None))
    monkeypatch.setattr(st, "warning", warnings.append)
    master_df = pd.DataFrame(
        {"timestamp": [pd.Timestamp("2026-10-16 00:00", tz="Europe/Berlin")]}
    )

    _render_day_ahead_price_sync_status(master_df, None, timedelta(minutes=15))
    _render_day_ahead_price_sync_status(master_df, None, timedelta(minutes=15))

    assert reruns == [None]
    assert reuse_requests == [None]
    assert st.session_state[_PRICE_SYNC_RERUN_STATE_KEY] is future
    assert len(warnings) == 1


def test_dso_kpi_is_shown_when_market_metering_data_exists() -> None:
    """The optional DSO card appears when its aggregate is available."""
    grid_section = next(
        section for section in SECTION_SPECS if section["title"] == "Netzkennzahlen"
    )
    box_specs = _filter_section_box_specs(
        grid_section,
        component_type_set={"grid"},
        component_types_provided=True,
        microgrid_id=123,
    )

    filtered_specs = _filter_available_optional_metric_specs(
        box_specs,
        metrics={
            "grid_consumption_sum": 10.0,
            "grid_feed_in_sum": 5.0,
            "dso_import_energy_sum": 9.5,
            "dso_export_energy_sum": 1.5,
        },
    )

    filtered_keys = [spec.get("key") for spec in filtered_specs]
    assert "dso_import_energy_sum" in filtered_keys
    assert "dso_export_energy_sum" in filtered_keys


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


def test_battery_optimization_hides_disabled_cards_and_plots() -> None:
    """Disabled throughput and capacity values are absent from visible output."""
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
    assert not any("Wert pro kWh Batteriekapazität" in label for label in labels)
    assert "value_per_mwh_throughput" in _HIDDEN_NORMALIZED_METRICS
    assert _KPI_CARDS_PER_ROW == 4
    assert labels[:_KPI_CARDS_PER_ROW][-1] == "Preis-Spread Batterie (€/MWh)"
    assert labels[_KPI_CARDS_PER_ROW:] == [
        "Batteriezyklen (Vollzyklen)",
        "Wirkungsgrad (%)",
        "Entladene Menge (kWh)",
        "Geladene Menge (kWh)",
    ]
    assert _OPERATING_KPI_CARDS_PER_ROW == 4
    assert _PRIMARY_PLOT_METRICS == ("battery_price_spread_eur_per_mwh",)
    assert _SECONDARY_PLOT_METRICS == ("battery_cycles",)


def test_battery_plot_aggregation_controls_use_independent_fragments() -> None:
    """Each visible battery plot has its own fragment-only rerun boundary."""
    expected_plot_keys = {
        "battery_optimization",
        "battery_optimization_battery_price_spread_eur_per_mwh",
        "battery_optimization_battery_cycles",
    }

    assert set(_BATTERY_PLOT_FRAGMENT_RENDERERS) == expected_plot_keys
    assert len(
        {id(renderer) for renderer in _BATTERY_PLOT_FRAGMENT_RENDERERS.values()}
    ) == len(expected_plot_keys)


def test_single_battery_plot_is_rendered_without_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The standalone cycles plot does not render a redundant tab control."""
    tab_calls: list[list[str]] = []
    render_calls: list[dict[str, object]] = []

    def no_tabs(labels: list[str]) -> list[object]:
        """Record the requested labels without creating tab contexts."""
        tab_calls.append(list(labels))
        return []

    monkeypatch.setattr(st, "tabs", no_tabs)
    monkeypatch.setitem(
        _BATTERY_PLOT_FRAGMENT_RENDERERS,
        "battery_optimization_battery_cycles",
        lambda **kwargs: render_calls.append(kwargs),
    )

    _render_battery_optimization_plot_tabs(
        pd.DataFrame(),
        None,
        ("battery_cycles",),
    )

    assert not tab_calls
    assert render_calls[0]["plot_key"] == "battery_optimization_battery_cycles"
    assert render_calls[0]["metric_key"] == "battery_cycles"


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
        "Entladewert (€)",
        "Netto-Einsparung (€)",
        "Batteriekapazität (kWh)",
        "Batteriezyklen (Vollzyklen)",
    ]
    assert results.loc[0, "Zeitpunkt"] == pd.Timestamp("2026-01-01T00:00:00Z")
    assert results.loc[0, "Gesamterzeugung (kW)"] == pytest.approx(60.0)
    assert results.loc[0, "Geladene Energie (kWh)"] == pytest.approx(100.0)
    assert "Day-Ahead-Preis verfügbar" not in results
    assert "Ladekosten (€)" not in results


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
