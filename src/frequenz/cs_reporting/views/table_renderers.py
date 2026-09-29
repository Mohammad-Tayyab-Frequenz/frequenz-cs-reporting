# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Table rendering functions for the reporting views."""

from __future__ import annotations

from typing import Any, Callable, Iterable

import pandas as pd
import streamlit as st
from frequenz.lib.notebooks.reporting.utils.column_mapper import ColumnMapper

from frequenz.cs_reporting.components import tables
from frequenz.cs_reporting.constants import COMPONENT_CONFIGS, TablesResult
from frequenz.cs_reporting.views.component_sources import (
    PLOT_SOURCE_ANALYSIS_KEYS,
    PLOT_SOURCE_OPTIONS,
    component_analysis_for_source,
    component_source_has_data,
    selected_component_plot_source,
)

_MASTER_DF_DISPLAY_RENAMES = {
    "production_self_use": "Eigenverbrauch",
    "production_self_usage": "Eigenverbrauch Share",
}


def _round_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `df` with number columns rounded to three decimals."""
    rounded_df = df.copy()
    numeric_cols = rounded_df.select_dtypes(include="number").columns
    if not numeric_cols.empty:
        rounded_df[numeric_cols] = rounded_df[numeric_cols].round(3)
    return rounded_df


TABLE_TAB_SPECS = [
    {
        "label": "Leistungsmix",
        "table_key": "power_table",
        "key_prefix": "power_mix",
        "caption": "Aggregierter Energiemix aus PV und Netz",
    },
    {
        "label": "PV-Energie (pro Komponente)",
        "table_key": "pv_energy_table",
        "key_prefix": "pv_energy",
        "caption": "Zusammenfassung der PV-Energieerzeugung (pro Komponente)",
        "empty_info": "Keine PV-Energiedaten verfügbar.",
    },
    {
        "label": "PV-Analyse",
        "table_key": "pv_analysis",
        "analysis_key": "pv",
        "key_prefix": "pv_analysis",
        "caption": "PV-Energieerzeugung (Zeitreihe)",
        "empty_info": "Keine PV-Analysedaten verfügbar.",
    },
    {
        "label": "Batterie-Analyse",
        "table_key": "batt_analysis",
        "analysis_key": "batt",
        "key_prefix": "batt_analysis",
        "caption": "Batterie-Komponenten (Zeitreihe)",
        "empty_info": "Keine Batteriedaten verfügbar.",
    },
    {
        "label": "Wind-Analyse",
        "table_key": "wind_analysis",
        "analysis_key": "wind",
        "key_prefix": "wind_analysis",
        "caption": "Wind-Komponenten (Zeitreihe)",
        "empty_info": "Keine Winddaten verfügbar.",
    },
    {
        "label": "KWK-Analyse",
        "table_key": "chp_analysis",
        "analysis_key": "chp",
        "key_prefix": "chp_analysis",
        "caption": "KWK-Komponenten (Zeitreihe)",
        "empty_info": "Keine KWK-Daten verfügbar.",
    },
    {
        "label": "EV-Analyse",
        "table_key": "ev_analysis",
        "analysis_key": "ev",
        "key_prefix": "ev_analysis",
        "caption": "EV-Komponenten (Zeitreihe)",
        "empty_info": "Keine EV-Daten verfügbar.",
    },
]


def render_table_section(
    df: pd.DataFrame | None,
    *,
    key_prefix: str,
    empty_info: str | None = None,
    component_source: str | None = None,
    component_source_state_key: str | None = None,
) -> None:
    """Render a captioned AgGrid table, safely handling None/empty data.

    Args:
        df: The dataframe to display. If ``None`` or empty, an empty table is shown
            and an optional info message is rendered.
        key_prefix: Unique key prefix for the grid instance (used by Streamlit state).
        empty_info: Optional info message to show when ``df`` is ``None`` or empty.
        component_source: Selected component source shown in the table toolbar.
        component_source_state_key: Session-state key updated when the source
            selector in the table toolbar changes.

    Returns:
        Streamlit components are rendered directly.
    """
    safe_df = df if (df is not None and not df.empty) else pd.DataFrame()
    display_df = _round_numeric_columns(safe_df)
    selected_source = tables.aggrid_table(
        display_df,
        key_prefix=key_prefix,
        download_file_name=f"{key_prefix}.csv",
        component_source=component_source,
    )

    if (
        component_source_state_key
        and selected_source
        and selected_source != component_source
    ):
        st.session_state[component_source_state_key] = selected_source
        st.rerun()

    if (df is None or df.empty) and empty_info:
        st.info(empty_info)


def _component_analysis_table_for_source(
    master_df: pd.DataFrame,
    mcfg: Any,
    component_types: Iterable[str],
    analysis_key: str,
    selected_source: str,
) -> pd.DataFrame:
    """Build a component analysis dataframe for the selected source."""
    config = COMPONENT_CONFIGS[analysis_key]
    return component_analysis_for_source(
        master_df,
        mcfg,
        component_types,
        analysis_key,
        config["label"],
        config["value_col"],
        selected_source,
    )


def _component_source_has_data_callback(
    master_df: pd.DataFrame,
    mcfg: Any,
    component_types: Iterable[str],
    analysis_key: str,
) -> Callable[[str], bool]:
    """Return a source data predicate for a component analysis table."""
    config = COMPONENT_CONFIGS[analysis_key]

    def source_has_data(source: str) -> bool:
        return component_source_has_data(
            master_df,
            mcfg,
            component_types,
            analysis_key,
            config["label"],
            config["value_col"],
            source,
        )

    return source_has_data


def _table_spec_has_data(
    spec: dict[str, str],
    tables_dict: TablesResult,
    master_df: pd.DataFrame,
    mcfg: Any,
    component_types: Iterable[str],
) -> bool:
    """Return whether a table spec has data available for display."""
    analysis_key = spec.get("analysis_key")
    if analysis_key in PLOT_SOURCE_ANALYSIS_KEYS:
        config = COMPONENT_CONFIGS[str(analysis_key)]
        return any(
            component_source_has_data(
                master_df,
                mcfg,
                component_types,
                str(analysis_key),
                config["label"],
                config["value_col"],
                source,
            )
            for source in PLOT_SOURCE_OPTIONS
        )

    value = tables_dict.get(spec["table_key"])
    return isinstance(value, pd.DataFrame) and not value.empty


def render_master_df(master_df: pd.DataFrame, mapper: ColumnMapper) -> None:
    """Render the combined master dataframe in an AgGrid table.

    Args:
        master_df: Processed master dataframe to display.
        mapper: Column mapper for converting canonical names to standard display labels.

    Returns:
        Streamlit components are rendered directly.
    """
    if master_df is not None and not master_df.empty:
        display_df = _round_numeric_columns(
            mapper.to_display(master_df).rename(columns=_MASTER_DF_DISPLAY_RENAMES)
        )
        tables.aggrid_table(
            display_df,
            key_prefix="master_df",
            download_file_name="master_df.csv",
        )
    else:
        st.info("Master-DF nicht verfügbar (keine MicrogridConfig).")


# pylint: disable=too-many-locals
def render_data_tabs(
    master_df: pd.DataFrame,
    tables_dict: TablesResult,
    mapper: ColumnMapper,
    mcfg: Any,
    component_types: Iterable[str],
) -> None:
    """Render tabbed data tables for overview and component analyses.

    Args:
        master_df: Processed master dataframe.
        tables_dict: Mapping of table names to dataframes for each analysis.
        mapper: Column mapper for standardizing Gesamt-Datensatz column names.
        mcfg: Microgrid configuration object containing component metadata.
        component_types: Component type identifiers present in the microgrid.

    Returns:
        Streamlit components are rendered directly.
    """
    available_specs = []
    for spec in TABLE_TAB_SPECS:
        if _table_spec_has_data(spec, tables_dict, master_df, mcfg, component_types):
            available_specs.append(spec)

    include_master = master_df is not None and not master_df.empty

    if not available_specs and not include_master:
        st.info("Keine Datentabellen verfügbar.")
        return

    tab_labels = []
    if include_master:
        tab_labels.append("Gesamt-Datensatz")
    tab_labels.extend(spec["label"] for spec in available_specs)
    tabs = st.tabs(tab_labels)

    table_tabs = tabs
    if include_master:
        with tabs[0]:
            render_master_df(master_df, mapper)
        table_tabs = tabs[1:]

    for tab, spec in zip(table_tabs, available_specs):
        value = tables_dict.get(spec["table_key"])
        with tab:
            analysis_key = spec.get("analysis_key")
            empty_info = spec.get("empty_info")
            if analysis_key in PLOT_SOURCE_ANALYSIS_KEYS:
                table_key = str(spec["table_key"])
                analysis_key = str(analysis_key)
                selected_source = selected_component_plot_source(
                    mcfg,
                    component_types,
                    analysis_key,
                    state_key=f"{table_key}_component_plot_source",
                    source_has_data=_component_source_has_data_callback(
                        master_df,
                        mcfg,
                        component_types,
                        analysis_key,
                    ),
                )
                value = _component_analysis_table_for_source(
                    master_df,
                    mcfg,
                    component_types,
                    analysis_key,
                    selected_source,
                )

            render_table_section(
                value if isinstance(value, pd.DataFrame) else None,
                key_prefix=spec["key_prefix"],
                empty_info=(
                    None
                    if (
                        analysis_key in PLOT_SOURCE_ANALYSIS_KEYS
                        and selected_source == "meter"
                        and (not isinstance(value, pd.DataFrame) or value.empty)
                    )
                    else empty_info
                ),
                component_source=(
                    selected_source
                    if analysis_key in PLOT_SOURCE_ANALYSIS_KEYS
                    else None
                ),
                component_source_state_key=(
                    f"{table_key}_component_plot_source"
                    if analysis_key in PLOT_SOURCE_ANALYSIS_KEYS
                    else None
                ),
            )
            if (
                analysis_key in PLOT_SOURCE_ANALYSIS_KEYS
                and selected_source == "meter"
                and (not isinstance(value, pd.DataFrame) or value.empty)
            ):
                st.warning("Meter-Daten sind nicht verfügbar.")
