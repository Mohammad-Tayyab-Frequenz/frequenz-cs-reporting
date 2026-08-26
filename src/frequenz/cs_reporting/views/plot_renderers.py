# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Plot rendering functions for the reporting views."""

from __future__ import annotations

from functools import partial
from typing import Any, Callable, Iterable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from frequenz.lib.notebooks.reporting.plotter import (
    plot_energy_pie_chart,
    plot_time_series,
    plot_time_series_battery_soc,
    plot_time_series_battery_soc_and_usecase,
    plot_time_series_battery_usecase,
)
from frequenz.lib.notebooks.reporting.utils.column_mapper import ColumnMapper
from frequenz.lib.notebooks.reporting.utils.reporting_nb_functions import (
    build_component_analysis,
)

from frequenz.cs_reporting.components.ui import render_plot_card
from frequenz.cs_reporting.constants import COLOR_DICT, COMPONENT_CONFIGS, TablesResult

_COMPONENT_TABS = [
    ("PV Leistung", "pv"),
    ("Batterie", "batt"),
    ("Wind", "wind"),
    ("KWK", "chp"),
    ("EV", "ev"),
]
_TIME_SERIES_HEIGHT = 500
_TIME_SERIES_MARGIN = {"t": 80, "r": 64, "b": 96, "l": 64}
_TIME_SERIES_RANGE_SLIDER_THICKNESS = 0.15
_PLOT_SOURCE_OPTIONS = ("meter", "inverter")
_PLOT_SOURCE_ANALYSIS_KEYS = frozenset({"pv", "batt", "wind", "chp"})


def _component_type_from_analysis_key(analysis_key: str) -> str:
    """Return the microgrid component type for an analysis table key."""
    if analysis_key == "batt":
        return "battery"
    return analysis_key


def _component_ids_for_plot_source(
    mcfg: Any,
    component_types: Iterable[str],
    component_plot_source: str,
) -> dict[str, tuple[str, ...]]:
    """Return component ID filters for the selected HTH plot source."""
    component_type_set = set(component_types)
    analysis_ids: dict[str, tuple[str, ...]] = {}

    for analysis_key in _PLOT_SOURCE_ANALYSIS_KEYS:
        component_type = _component_type_from_analysis_key(analysis_key)
        if component_type not in component_type_set:
            continue

        category_ids = mcfg.component_type_ids(
            component_type,
            component_category=component_plot_source,
        )
        if component_plot_source == "inverter" and not category_ids:
            category_ids = mcfg.component_type_ids(
                component_type,
                component_category="component",
            )

        analysis_ids[analysis_key] = tuple(str(cid) for cid in sorted(category_ids))

    return analysis_ids


def _left_align_plot_title(fig: object) -> None:
    """Align Plotly figure titles with the left edge of the chart container."""
    if isinstance(fig, go.Figure):
        fig.update_layout(title={"x": 0, "xref": "container", "xanchor": "left"})


def _apply_compact_time_series_layout(fig: go.Figure) -> None:
    """Reduce time-series plot size without changing the visible data range."""
    fig.update_layout(
        height=_TIME_SERIES_HEIGHT,
        margin=_TIME_SERIES_MARGIN,
        xaxis_rangeslider_thickness=_TIME_SERIES_RANGE_SLIDER_THICKNESS,
    )
    fig.update_xaxes(autorange=True, range=None)
    fig.update_yaxes(autorange=True, range=None)


# pylint: disable=too-many-arguments, too-many-locals
def render_time_series(
    df: pd.DataFrame,
    *,
    time_col: str = "Zeitpunkt",
    cols: list[str] | None = None,
    title: str = "Zeitreihen-Plot",
    xaxis_title: str = "Zeitpunkt",
    yaxis_title: str = "kWh",
    legend_title: str | None = "Komponenten",
    color_dict: dict[str, str] | None = None,
    long_format_flag: bool = False,
    category_col: str | None = None,
    value_col: str | None = None,
    fill_cols: list[str] | None = None,
    plot_order: list[str] | None = None,
    dotted_cols: list[str] | None = None,
    header_control: Callable[[], None] | None = None,
    key: str | None = None,
) -> None:
    """Render a generic time-series plot inside a card.

    Args:
        df: Dataframe containing a datetime column and series to plot.
        time_col: Column name containing datetime values.
        cols: Optional list of series columns to include; defaults to all
            non-time columns.
        title: Title displayed above the plot.
        xaxis_title: X-axis label.
        yaxis_title: Y-axis label.
        legend_title: Legend title or ``None`` to hide the legend title.
        color_dict: Optional mapping from column names to colors.
        long_format_flag: Whether the dataframe is already in long format.
        category_col: Category column name when ``long_format_flag`` is ``True``.
        value_col: Value column name when ``long_format_flag`` is ``True``.
        fill_cols: Columns to fill under the curve for stacked plots.
        plot_order: Explicit ordering of series when rendering.
        dotted_cols: Columns to render with dotted lines.
        header_control: Optional Streamlit control rendered at the right side of
            the plot card header.
        key: Optional key used to style plot cards with header controls.

    Returns:
        Streamlit components are rendered directly.
    """
    if df is None or df.empty:
        st.info("Keine Daten zum Plotten verfügbar.")
        return

    if time_col not in df.columns:
        st.info(f"Keine gültige Zeitspalte gefunden (erwartet: '{time_col}').")
        return

    df = df.copy()
    if not pd.api.types.is_datetime64_any_dtype(df[time_col]):
        df[time_col] = pd.to_datetime(df[time_col], errors="coerce")

    fig = plot_time_series(
        df,
        time_col=time_col,
        cols=cols,
        title="",
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        legend_title=legend_title,
        color_dict=color_dict,
        long_format_flag=long_format_flag,
        category_col=category_col,
        value_col=value_col,
        fill_cols=fill_cols,
        dotted_cols=dotted_cols,
        plot_order=plot_order,
    )
    _apply_compact_time_series_layout(fig)
    _left_align_plot_title(fig)

    render_plot_card(title, fig, header_control=header_control, key=key)


def render_energy_pie_chart(
    power_df: pd.DataFrame | None,
    color_dict: dict[str, str] | None = None,
) -> None:
    """Render the energy mix pie chart from a power dataframe.

    Args:
        power_df: Dataframe containing ``Energy Source`` and ``Energy [kWh]``.
        color_dict: Optional color mapping for pie segments.

    Returns:
        Streamlit components are rendered directly.
    """
    if power_df is None or power_df.empty:
        st.info("Keine Daten für das Energie-Kreisdiagramm verfügbar.")
        return

    required_cols = {"Energy Source", "Energy [kWh]"}
    if not required_cols.issubset(set(power_df.columns)):
        st.info("Energiedaten enthalten nicht alle erforderlichen Spalten.")
        return

    power_df["Energy Source"] = power_df["Energy Source"].replace(
        {"CHP": "KWK", "Grid Consumption": "Netzbezug"}
    )
    power_df = power_df.rename(
        columns={"Energy Source": "Energiebezug", "Energy [kWh]": "Energie [kWh]"}
    )
    fig = plot_energy_pie_chart(power_df, color_dict=color_dict)
    render_plot_card("Energie-Mix", fig)


# pylint: disable=too-many-arguments, too-many-positional-arguments, too-many-locals
@st.fragment
def _render_component_tab(
    tables: TablesResult,
    master_df: pd.DataFrame,
    mapper: ColumnMapper,
    mcfg: Any,
    component_types: Iterable[str],
    analysis_key: str,
    table_key: str,
    title: str,
    category_col: str,
    value_col: str,
    color_dict: dict[str, str] | None = None,
) -> None:
    """Render a component analysis tab with time series plot.

    Args:
        tables: Dictionary of analysis tables.
        master_df: Master dataframe used to rebuild filtered plot analyses.
        mapper: Column mapper for display names.
        mcfg: Microgrid configuration object containing component metadata.
        component_types: Component type identifiers present in the microgrid.
        analysis_key: Component analysis key, such as ``pv`` or ``batt``.
        table_key: Key to lookup the table in ``tables``.
        title: Title for the plot.
        category_col: Category column name in the long-format dataframe.
        value_col: Value column name in the long-format dataframe.
        color_dict: Optional color mapping dictionary.

    Returns:
        Streamlit components are rendered directly.
    """
    df = tables.get(table_key)
    if not isinstance(df, pd.DataFrame) or df.empty:
        st.info(f"Keine Daten für {title}.")
        return

    selectbox_key = f"{table_key}_component_plot_source"
    selected_source = st.session_state.get(selectbox_key, _PLOT_SOURCE_OPTIONS[0])
    if analysis_key in _PLOT_SOURCE_ANALYSIS_KEYS:
        selected_ids = _component_ids_for_plot_source(
            mcfg,
            component_types,
            str(selected_source),
        ).get(analysis_key)
        df = build_component_analysis(
            master_df,
            selection_filter=["All"],
            component_label=category_col,
            value_col_name=value_col,
            allowed_component_ids=(
                set(selected_ids) if selected_ids is not None else None
            ),
        )

    def source_selector() -> None:
        st.selectbox(
            "Komponentenquelle",
            options=_PLOT_SOURCE_OPTIONS,
            format_func=lambda value: {
                "meter": "Meter",
                "inverter": "Inverter / Komponenten",
            }[value],
            key=selectbox_key,
            label_visibility="collapsed",
        )

    palette = color_dict or COLOR_DICT
    df = mapper.to_display(df)
    render_time_series(
        df,
        time_col="Zeitpunkt",
        title=title,
        yaxis_title="kWh",
        xaxis_title="Zeitpunkt",
        legend_title=None,
        long_format_flag=True,
        category_col=category_col,
        value_col=value_col,
        color_dict=palette,
        header_control=(
            source_selector if analysis_key in _PLOT_SOURCE_ANALYSIS_KEYS else None
        ),
        key=table_key,
    )


def _prepare_battery_usecase_df(tables: TablesResult) -> pd.DataFrame | None:
    """Return the overview dataframe prepared for the battery-usecase plot.

    Args:
        tables: Dictionary containing precomputed tables.

    Returns:
        Battery-usecase dataframe, or ``None`` when unavailable.
    """
    battery_usecase_df = tables.get("overview_df")
    if battery_usecase_df is None or battery_usecase_df.empty:
        return None

    return battery_usecase_df.drop(columns={"grid_feed_in"}, errors="ignore")


def _render_overview_plot(battery_usecase_df: pd.DataFrame | None) -> None:
    """Render the main time-series overview plot.

    Args:
        battery_usecase_df: Battery-usecase dataframe in canonical naming convention.

    Returns:
        Streamlit components are rendered directly.
    """
    if battery_usecase_df is None or battery_usecase_df.empty:
        st.info("Keine Übersichtsdaten zum Plotten verfügbar.")
        return

    cols_list = battery_usecase_df.columns.tolist()
    price_cols = (
        ["day_ahead_price"] if "day_ahead_price" in battery_usecase_df.columns else []
    )
    if price_cols:
        fig = plot_time_series_battery_soc_and_usecase(
            battery_usecase_df,
            cols=cols_list,
            time_col="timestamp",
            battery_power_flow="battery_power_flow",
            soc_pct="battery_soc_pct",
            legend_title=None,
            secondary_y_cols=price_cols,
            secondary_y_title="EUR/MWh",
            title="",
            dotted_cols=[
                "grid_consumption_without_battery",
                "peak_before_optimization",
                *price_cols,
            ],
            stack_mode="psc",
            xaxis_title="Zeitpunkt",
            yaxis_title="kW",
            soc_secondary_y_title="SOC [%]",
        )
    else:
        fig = plot_time_series_battery_usecase(
            battery_usecase_df,
            cols=cols_list,
            time_col="timestamp",
            battery_power_flow="battery_power_flow",
            legend_title=None,
            title="",
            dotted_cols=[
                "grid_consumption_without_battery",
                "peak_before_optimization",
            ],
            stack_mode="psc",
            xaxis_title="Zeitpunkt",
            yaxis_title="kW",
        )
    _apply_compact_time_series_layout(fig)
    _left_align_plot_title(fig)
    render_plot_card("Lastgang Übersicht", fig)


def _render_battery_soc_plot(battery_usecase_df: pd.DataFrame | None) -> None:
    """Render the battery power flow and SOC plot.

    Args:
        battery_usecase_df: Battery-usecase dataframe in canonical naming convention.

    Returns:
        Streamlit components are rendered directly.
    """
    if battery_usecase_df is None or battery_usecase_df.empty:
        st.info("Keine Batteriedaten zum Plotten verfügbar.")
        return

    required_cols = {"timestamp", "battery_power_flow", "battery_soc_pct"}
    missing_cols = required_cols.difference(battery_usecase_df.columns)
    if missing_cols:
        st.info("Keine gültigen Batteriedaten für den SOC-Plot verfügbar.")
        return

    fig = plot_time_series_battery_soc(
        battery_usecase_df,
        time_col="timestamp",
        title="",
        xaxis_title="Zeitpunkt",
        yaxis_title="kW",
        battery_power_flow="battery_power_flow",
        soc_pct="battery_soc_pct",
        legend_title=None,
        secondary_y_title="SOC [%]",
    )
    _apply_compact_time_series_layout(fig)
    _left_align_plot_title(fig)
    render_plot_card("Batterie Ladezustand", fig)


# pylint: disable=too-many-locals
def _get_active_tabs(
    tables: TablesResult,
    master_df: pd.DataFrame,
    mapper: ColumnMapper,
    mcfg: Any,
    palette: dict[str, str],
    component_types: Iterable[str],
) -> list[tuple[str, Callable[[], None]]]:
    """Determine which tabs should be rendered based on data availability."""
    tabs = []
    battery_soc_tab: tuple[str, Callable[[], None]] | None = None
    component_type_set = set(component_types)

    # 1. Overview Tab
    overview_df = _prepare_battery_usecase_df(tables)
    if overview_df is not None and not overview_df.empty:
        tabs.append(("Zeitreihen-Plot", lambda: _render_overview_plot(overview_df)))
        if "battery" in component_type_set:
            battery_soc_tab = (
                "Batterie SOC",
                lambda: _render_battery_soc_plot(overview_df),
            )

    # 2. Energy Mix Tab
    power_table = tables.get("power_table")
    required = {"Energy Source", "Energy [kWh]"}
    if (
        isinstance(power_table, pd.DataFrame)
        and not power_table.empty
        and required.issubset(power_table.columns)
    ):
        tabs.append(
            (
                "Energie-Mix",
                lambda: render_energy_pie_chart(power_table, color_dict=palette),
            )
        )

    # 3. Dynamic Component Tabs
    for label, key in _COMPONENT_TABS:
        df = tables.get(f"{key}_analysis")
        config = COMPONENT_CONFIGS.get(key)

        if isinstance(df, pd.DataFrame) and not df.empty and config:
            # partial creates a typed callable and captures 'key' and 'config' correctly
            render_fn = partial(
                _render_component_tab,
                tables=tables,
                master_df=master_df,
                mapper=mapper,
                mcfg=mcfg,
                component_types=component_types,
                analysis_key=key,
                table_key=f"{key}_analysis",
                title=config["title"],
                category_col=config["label"],
                value_col=config["value_col"],
                color_dict=palette,
            )
            tabs.append((label, render_fn))

    if battery_soc_tab is not None:
        tabs.append(battery_soc_tab)

    return tabs


def render_plots_tabs(
    tables: TablesResult,
    mapper: ColumnMapper,
    component_types: Iterable[str],
    master_df: pd.DataFrame,
    mcfg: Any,
    color_dict: dict[str, str] | None = None,
) -> None:
    """
    Render the plot tabs.

    Args:
        tables: The tables result containing data for the plots.
        mapper: The column mapper for renaming columns.
        component_types: Component type identifiers present in the microgrid.
        master_df: Master dataframe used to rebuild filtered plot analyses.
        mcfg: Microgrid configuration object containing component metadata.
        color_dict: Optional color mapping for the plots.
    """
    palette = color_dict or COLOR_DICT

    # Get configuration of what to render
    plot_tabs_config = _get_active_tabs(
        tables,
        master_df,
        mapper,
        mcfg,
        palette,
        component_types,
    )

    if not plot_tabs_config:
        st.info("Keine Plot-Daten verfügbar.")
        return

    # Render the UI
    tab_labels = [label for label, _ in plot_tabs_config]
    for tab, (_, render_fn) in zip(st.tabs(tab_labels), plot_tabs_config):
        with tab:
            render_fn()
