# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Plot rendering functions for the reporting views."""

from __future__ import annotations

from functools import partial
from typing import Callable

import pandas as pd
import streamlit as st
from frequenz.lib.notebooks.reporting.plotter import (
    plot_energy_pie_chart,
    plot_time_series,
)
from frequenz.lib.notebooks.reporting.utils.column_mapper import ColumnMapper

from frequenz.cs_reporting.components.ui import render_plot_card
from frequenz.cs_reporting.constants import (
    COLOR_DICT,
    COLUMN_RENAME_MAP,
    COMPONENT_CONFIGS,
    TablesResult,
)

_DEFAULT_PLOT_ORDER = [
    "Zeitpunkt",
    "MID Gesamtverbrauch",
    "Netzbezug",
    "Netzeinspeisung",
    "PV-Erzeugung",
    "KWK-Erzeugung",
    "Wind-Erzeugung",
    "Batterie Leistungsfluss",
]

_DEFAULT_DOTTED_COLS = ["Netzbezug"]
_FILL_EXCLUDE = {
    "Zeitpunkt",
    "MID Gesamtverbrauch",
    "Netzbezug",
    "Netzeinspeisung",
    "Netz Einspeisung",
}
_OVERVIEW_ALIASES = {
    "BHKW-Erzeugung": "KWK-Erzeugung",
    "CHP": "KWK-Erzeugung",
    "Netz Einspeisung": "Netzeinspeisung",
}
_COMPONENT_TABS = [
    ("PV Leistung", "pv"),
    ("Batterie", "batt"),
    ("Wind", "wind"),
    ("KWK", "chp"),
    ("EV", "ev"),
]


# pylint: disable=too-many-arguments
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
        title=title,
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

    render_plot_card(title, fig)


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


# pylint: disable=too-many-arguments, too-many-positional-arguments
def _render_component_tab(
    tables: TablesResult,
    mapper: ColumnMapper,
    table_key: str,
    title: str,
    category_col: str,
    value_col: str,
    color_dict: dict[str, str] | None = None,
) -> None:
    """Render a component analysis tab with time series plot.

    Args:
        tables: Dictionary of analysis tables.
        mapper: Column mapper for display names.
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
    )


def _prepare_overview_df(
    tables: TablesResult, mapper: ColumnMapper
) -> pd.DataFrame | None:
    """Return overview dataframe with display-ready column names.

    Args:
        tables: Dictionary containing precomputed tables.
        mapper: Column mapper for converting internal names to display names.

    Returns:
        Overview dataframe with renamed columns, or ``None``
            when unavailable.
    """
    overview_df = tables.get("overview_df")
    if overview_df is None or overview_df.empty:
        return None

    overview_df = mapper.to_display(overview_df)
    # Compatibility shim until the latest lib notebooks update rolls out
    overview_df = overview_df.rename(columns=COLUMN_RENAME_MAP)

    # Normalize known legacy aliases so plot ordering always includes key series.
    for source, target in _OVERVIEW_ALIASES.items():
        if source in overview_df.columns and target not in overview_df.columns:
            overview_df = overview_df.rename(columns={source: target})

    return overview_df


def _render_overview_plot(
    overview_df: pd.DataFrame | None, color_dict: dict[str, str] | None
) -> None:
    """Render the main time-series overview plot.

    Args:
        overview_df: Overview dataframe in display naming convention.
        color_dict: Optional color mapping for plot series.

    Returns:
        Streamlit components are rendered directly.
    """
    if overview_df is None or overview_df.empty:
        st.info("Keine Übersichtsdaten zum Plotten verfügbar.")
        return

    palette = color_dict or COLOR_DICT
    plot_order = [col for col in _DEFAULT_PLOT_ORDER if col in overview_df.columns]
    fill_cols = [col for col in overview_df.columns if col not in _FILL_EXCLUDE]
    dotted_cols = [col for col in _DEFAULT_DOTTED_COLS if col in overview_df.columns]

    render_time_series(
        overview_df,
        title="Lastgang Übersicht",
        color_dict=palette,
        fill_cols=fill_cols,
        plot_order=plot_order,
        dotted_cols=dotted_cols,
    )


def _get_active_tabs(
    tables: TablesResult, mapper: ColumnMapper, palette: dict[str, str]
) -> list[tuple[str, Callable[[], None]]]:
    """Determine which tabs should be rendered based on data availability."""
    tabs = []

    # 1. Overview Tab
    overview_df = _prepare_overview_df(tables, mapper)
    if overview_df is not None and not overview_df.empty:
        tabs.append(
            ("Zeitreihen-Plot", lambda: _render_overview_plot(overview_df, palette))
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
                mapper=mapper,
                table_key=f"{key}_analysis",
                title=config["title"],
                category_col=config["label"],
                value_col=config["value_col"],
                color_dict=palette,
            )
            tabs.append((label, render_fn))

    return tabs


def render_plots_tabs(
    tables: TablesResult,
    mapper: ColumnMapper,
    color_dict: dict[str, str] | None = None,
) -> None:
    """
    Render the plot tabs.

    Args:
        tables: The tables result containing data for the plots.
        mapper: The column mapper for renaming columns.
        color_dict: Optional color mapping for the plots.
    """
    palette = color_dict or COLOR_DICT

    # Get configuration of what to render
    plot_tabs_config = _get_active_tabs(tables, mapper, palette)

    if not plot_tabs_config:
        st.info("Keine Plot-Daten verfügbar.")
        return

    # Render the UI
    tab_labels = [label for label, _ in plot_tabs_config]
    for tab, (_, render_fn) in zip(st.tabs(tab_labels), plot_tabs_config):
        with tab:
            render_fn()
