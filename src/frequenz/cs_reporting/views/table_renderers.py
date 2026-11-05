# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Table rendering functions for the reporting views."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Iterable

import pandas as pd
import streamlit as st
from frequenz.lib.notebooks.reporting.utils.column_mapper import ColumnMapper

from frequenz.cs_reporting.components import tables
from frequenz.cs_reporting.constants import COMPONENT_CONFIGS, TablesResult
from frequenz.cs_reporting.services.battery_optimization_calculations import (
    build_battery_optimization_results_table,
)
from frequenz.cs_reporting.ui_resources import inject_style
from frequenz.cs_reporting.views.component_sources import (
    PLOT_SOURCE_ANALYSIS_KEYS,
    PLOT_SOURCE_OPTIONS,
    component_analysis_for_source,
    component_source_has_data,
)

_MASTER_DF_DISPLAY_RENAMES = {
    "dso_import_power": "Netzbetreiber Netzbezug (kW)",
    "dso_export_power": "Netzbetreiber Netzeinspeisung (kW)",
    "production_self_use": "Eigenverbrauch",
    "production_self_usage": "Eigenverbrauch Share",
}

_CORE_DATA_COLUMNS = (
    "timestamp",
    "grid_consumption",
    "dso_import_power",
    "dso_export_power",
    "mid_consumption",
    "grid_feed_in",
    "pv_asset_production",
    "prod_self_consumption",
    "production_self_use",
    "production_to_battery",
    "grid_to_battery",
    "battery_to_grid",
    "battery_to_consumption",
    "day_ahead_price",
)

_CORE_DATA_CANONICAL_NAMES = {
    # ``add_energy_flows`` still emits this legacy name, while ColumnMapper uses
    # ``prod_self_consumption`` as the canonical field name.
    "production_self_use": "prod_self_consumption",
}

_CORE_DATA_DISPLAY_FALLBACKS = {
    "dso_import_power": "Netzbetreiber Netzbezug (kW)",
    "dso_export_power": "Netzbetreiber Netzeinspeisung (kW)",
    "production_to_battery": "Erzeugung zu Batterie",
    "grid_to_battery": "Netz zu Batterie",
    "battery_to_grid": "Batterie zu Netz",
    "battery_to_consumption": "Batterie zu Verbrauch",
    "day_ahead_price": "Day Ahead Preis",
}

_DSO_PRICE_DATA_COLUMNS = (
    "timestamp",
    "dso_export_power",
    "dso_import_power",
    "day_ahead_price",
)

_DSO_PRICE_DATA_RENAMES = {
    "timestamp": "Zeitpunkt",
    "dso_export_power": "Netzbetreiber Netzeinspeisung (kW)",
    "dso_import_power": "Netzbetreiber Netzbezug (kW)",
    "day_ahead_price": "Day Ahead Preis",
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
    {
        "label": "Netzeinspeisung",
        "table_key": "feed_in_table",
        "key_prefix": "feed_in",
        "caption": "Netzeinspeisung und zugehörige Day-Ahead-Preise",
        "empty_info": "Keine Netzeinspeisungs- oder Day-Ahead-Preisdaten verfügbar.",
    },
]


def render_table_section(
    df: pd.DataFrame | None,
    *,
    key_prefix: str,
    empty_info: str | None = None,
) -> None:
    """Render a captioned AgGrid table, safely handling None/empty data.

    Args:
        df: The dataframe to display. If ``None`` or empty, an empty table is shown
            and an optional info message is rendered.
        key_prefix: Unique key prefix for the grid instance (used by Streamlit state).
        empty_info: Optional info message to show when ``df`` is ``None`` or empty.

    Returns:
        Streamlit components are rendered directly.
    """
    safe_df = df if (df is not None and not df.empty) else pd.DataFrame()
    display_df = _round_numeric_columns(safe_df)
    tables.aggrid_table(
        display_df,
        key_prefix=key_prefix,
        download_file_name=f"{key_prefix}.csv",
    )

    if (df is None or df.empty) and empty_info:
        st.info(empty_info)


@st.fragment
def render_component_source_table(
    source_frames: dict[str, pd.DataFrame],
    *,
    key_prefix: str,
    default_source: str,
) -> None:
    """Render one source dataframe with fragment-scoped source selection."""
    available_sources = [
        source for source in PLOT_SOURCE_OPTIONS if not source_frames[source].empty
    ]
    selected_source = st.segmented_control(
        "Komponentenquelle",
        options=available_sources,
        default=(
            default_source
            if default_source in available_sources
            else available_sources[0]
        ),
        format_func=lambda source: {
            "meter": "Meter",
            "inverter": "Inverter / Komponenten",
        }[source],
        key=f"{key_prefix}_table_component_source",
        label_visibility="collapsed",
    )
    render_table_section(
        source_frames[str(selected_source)],
        key_prefix=key_prefix,
    )


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


def _build_core_data_df(master_df: pd.DataFrame, mapper: ColumnMapper) -> pd.DataFrame:
    """Return the compact subset of columns used by the core-data tab."""
    available_columns = [
        column
        for column in _CORE_DATA_COLUMNS
        if column in master_df.columns
        and not (
            column == "production_self_use"
            and "prod_self_consumption" in master_df.columns
        )
    ]
    canonical_names = {
        column: _CORE_DATA_CANONICAL_NAMES.get(
            column, mapper.raw_to_canonical.get(column, column)
        )
        for column in available_columns
    }
    display_names = {
        canonical_name: mapper.canonical_to_display.get(
            canonical_name,
            _CORE_DATA_DISPLAY_FALLBACKS.get(source_name, canonical_name),
        )
        for source_name, canonical_name in canonical_names.items()
    }
    return (
        master_df.loc[:, available_columns]
        .rename(columns=canonical_names)
        .rename(columns=display_names)
    )


def render_core_data(master_df: pd.DataFrame, mapper: ColumnMapper) -> None:
    """Render the most relevant reporting columns in a compact table."""
    render_table_section(
        _build_core_data_df(master_df, mapper),
        key_prefix="core_data",
    )


def _build_dso_price_data_df(master_df: pd.DataFrame) -> pd.DataFrame:
    """Return the compact DSO feed-in, import, and price export dataset."""
    available_columns = [
        column for column in _DSO_PRICE_DATA_COLUMNS if column in master_df.columns
    ]
    return master_df.loc[:, available_columns].rename(columns=_DSO_PRICE_DATA_RENAMES)


def _export_dataset(
    master_df: pd.DataFrame, mapper: ColumnMapper, dataset: str
) -> pd.DataFrame:
    """Return the selected export dataset with its display column names."""
    if dataset == "core":
        return _build_core_data_df(master_df, mapper)
    return mapper.to_display(master_df).rename(columns=_MASTER_DF_DISPLAY_RENAMES)


def _filter_export_dates(
    df: pd.DataFrame, start_date: date, end_date: date
) -> pd.DataFrame:
    """Limit an export dataframe to inclusive calendar dates when possible."""
    timestamp_column = next(
        (column for column in ("timestamp", "Zeitpunkt") if column in df.columns),
        None,
    )
    if timestamp_column is None:
        return df

    timestamps = pd.to_datetime(df[timestamp_column], errors="coerce", utc=True)
    matching_rows = (timestamps.dt.date >= start_date) & (
        timestamps.dt.date <= end_date
    )
    return df.loc[matching_rows].copy()


def _export_date_bounds(df: pd.DataFrame) -> tuple[date, date] | None:
    """Return the calendar-date bounds of a dataframe timestamp column."""
    timestamp_column = next(
        (column for column in ("timestamp", "Zeitpunkt") if column in df.columns),
        None,
    )
    if timestamp_column is None:
        return None
    timestamps = pd.to_datetime(
        df[timestamp_column], errors="coerce", utc=True
    ).dropna()
    if timestamps.empty:
        return None
    return timestamps.min().date(), timestamps.max().date()


def _battery_optimization_export(
    master_df: pd.DataFrame, resolution: Any
) -> pd.DataFrame | None:
    """Build the Battery Reporting calculation table when a battery is present."""
    if "battery_power_flow" not in master_df.columns or resolution is None:
        return None

    return build_battery_optimization_results_table(master_df, resolution)


def _available_export_datasets(
    master_df: pd.DataFrame,
    mapper: ColumnMapper,
    tables_dict: TablesResult | None,
    resolution: Any,
) -> dict[str, pd.DataFrame]:
    """Return every non-empty dataset available from Reporting and Battery Reporting."""
    datasets = {
        "Kerndaten": _build_core_data_df(master_df, mapper),
        "Gesamt-Datensatz": mapper.to_display(master_df).rename(
            columns=_MASTER_DF_DISPLAY_RENAMES
        ),
    }
    if tables_dict is not None:
        reporting_tables = (
            ("Leistungsmix", "power_table"),
            ("PV-Analyse", "pv_analysis"),
            ("Batterie-Analyse", "batt_analysis"),
            ("Wind-Analyse", "wind_analysis"),
            ("KWK-Analyse", "chp_analysis"),
            ("EV-Analyse", "ev_analysis"),
            ("Netzeinspeisung", "feed_in_table"),
        )
        datasets.update(
            {
                label: table
                for label, key in reporting_tables
                if isinstance((table := tables_dict.get(key)), pd.DataFrame)
                and not table.empty
            }
        )

    battery_export = _battery_optimization_export(master_df, resolution)
    if battery_export is not None and not battery_export.empty:
        datasets["Batterie-Reporting: Berechnungsdaten"] = battery_export
    return datasets


def render_data_export(
    master_df: pd.DataFrame,
    mapper: ColumnMapper,
    tables_dict: TablesResult | None = None,
    resolution: Any = None,
) -> None:
    """Render predefined and custom CSV exports for Reporting and Battery Reporting."""
    inject_style("data_export.css")
    datasets = _available_export_datasets(master_df, mapper, tables_dict, resolution)

    st.markdown("### Netzbetreiber Daten & DA Preise")
    tables.aggrid_table(
        _round_numeric_columns(_build_dso_price_data_df(master_df)),
        key_prefix="data_export_dso_price",
        download_file_name="netzbetreiber_day_ahead_preis.csv",
    )

    st.divider()
    st.markdown("### Exporte-Vorlagen")
    export_tabs = st.tabs(list(datasets), key="data_export_standard_tabs")
    for index, (tab, (dataset_name, dataset_df)) in enumerate(
        zip(export_tabs, datasets.items())
    ):
        with tab:
            tables.aggrid_table(
                _round_numeric_columns(dataset_df),
                key_prefix=f"data_export_standard_{index}",
                download_file_name=f"{dataset_name.lower().replace(' ', '_')}.csv",
            )

    st.divider()
    st.markdown("### Individueller Datenexport")
    full_df = datasets["Gesamt-Datensatz"]
    default_columns = ["Zeitpunkt"] if "Zeitpunkt" in full_df.columns else []
    tables.aggrid_table(
        _round_numeric_columns(full_df),
        key_prefix="data_export_custom",
        download_file_name="individueller_datenexport.csv",
        column_selection=True,
        initially_visible_columns=default_columns,
    )


# pylint: disable=too-many-locals,too-many-arguments
def render_data_tabs(
    master_df: pd.DataFrame,
    tables_dict: TablesResult,
    mapper: ColumnMapper,
    mcfg: Any,
    component_types: Iterable[str],
    *,
    stacked: bool = False,
) -> None:
    """Render data tables for overview and component analyses.

    Args:
        master_df: Processed master dataframe.
        tables_dict: Mapping of table names to dataframes for each analysis.
        mapper: Column mapper for standardizing Gesamt-Datensatz column names.
        mcfg: Microgrid configuration object containing component metadata.
        component_types: Component type identifiers present in the microgrid.
        stacked: Render each dataset beneath the preceding one instead of in tabs.

    Returns:
        Streamlit components are rendered directly.
    """
    available_specs = []
    component_source_frames_by_table: dict[str, dict[str, pd.DataFrame]] = {}
    for spec in TABLE_TAB_SPECS:
        analysis_key = spec.get("analysis_key")
        if analysis_key in PLOT_SOURCE_ANALYSIS_KEYS:
            table_key = str(spec["table_key"])
            source_frames = {
                source: _component_analysis_table_for_source(
                    master_df,
                    mcfg,
                    component_types,
                    str(analysis_key),
                    source,
                )
                for source in PLOT_SOURCE_OPTIONS
            }
            if any(not frame.empty for frame in source_frames.values()):
                available_specs.append(spec)
                component_source_frames_by_table[table_key] = source_frames
        elif _table_spec_has_data(spec, tables_dict, master_df, mcfg, component_types):
            available_specs.append(spec)

    include_master = master_df is not None and not master_df.empty
    if not available_specs and not include_master:
        st.info("Keine Datentabellen verfügbar.")
        return

    def render_spec(spec: dict[str, Any]) -> None:
        """Render a single predefined data table."""
        value = tables_dict.get(spec["table_key"])
        analysis_key = spec.get("analysis_key")
        empty_info = spec.get("empty_info")
        if analysis_key in PLOT_SOURCE_ANALYSIS_KEYS:
            table_key = str(spec["table_key"])
            analysis_key = str(analysis_key)
            source_frames = component_source_frames_by_table[table_key]
            selected_source = next(
                source
                for source in PLOT_SOURCE_OPTIONS
                if not source_frames[source].empty
            )
            render_component_source_table(
                source_frames,
                key_prefix=spec["key_prefix"],
                default_source=selected_source,
            )
        else:
            render_table_section(
                value if isinstance(value, pd.DataFrame) else None,
                key_prefix=spec["key_prefix"],
                empty_info=empty_info,
            )

    if stacked:
        if include_master:
            st.subheader("Kerndaten")
            render_core_data(master_df, mapper)
            st.subheader("Gesamt-Datensatz")
            render_master_df(master_df, mapper)
        for spec in available_specs:
            st.subheader(str(spec["label"]))
            render_spec(spec)
        return

    tab_labels: list[str] = []
    if include_master:
        tab_labels.extend(("Kerndaten", "Gesamt-Datensatz"))
    tab_labels.extend(spec["label"] for spec in available_specs)
    tabs = st.tabs(tab_labels, key="reporting_data_tabs", on_change="ignore")

    table_tabs = tabs
    if include_master:
        with tabs[0]:
            render_core_data(master_df, mapper)
        with tabs[1]:
            render_master_df(master_df, mapper)
        table_tabs = tabs[2:]

    for tab, spec in zip(table_tabs, available_specs):
        with tab:
            render_spec(spec)
