# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Dashboard view rendering and master dataframe construction."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterable

import pandas as pd
import streamlit as st
from frequenz.lib.notebooks.reporting.data_processing import create_energy_report_df
from frequenz.lib.notebooks.reporting.utils.column_mapper import ColumnMapper
from frequenz.lib.notebooks.reporting.utils.reporting_nb_functions import (
    aggregate_metrics,
    build_component_analysis,
    build_overview_df,
    compute_energy_summary,
)

from frequenz.cs_reporting.constants import COMPONENT_CONFIGS, TablesResult
from frequenz.cs_reporting.views import sections


def _section_divider() -> None:
    """Render a subtle divider between dashboard sections."""
    st.markdown(
        "<hr style='border:0; border-top:1px solid #d9e1ec; margin: 18px 0 16px;'>",
        unsafe_allow_html=True,
    )


@st.cache_data(show_spinner="Preparing analysis tables…")
def _build_tables(
    master_df: pd.DataFrame,
    resolution: timedelta,
    component_types: Iterable[str],
) -> TablesResult:
    """Build all analysis tables from master dataframe.

    Creates power summary, aggregated metrics, and component-specific time series
    analyses for all configured components (PV, Battery, CHP, Wind, EV). Uses a
    configuration-driven approach from COMPONENT_CONFIGS for maintainability.

    Args:
        master_df: Master dataframe with timestamp index and component data columns.
            Expected to contain energy/power values for all microgrid components.
        resolution: Time resolution for energy aggregation (e.g., timedelta(minutes=15)).
        component_types: List of component type strings present in the microgrid
            (e.g., ['pv', 'battery', 'chp']).

    Returns:
        Dictionary containing:
            - power_table: Energy summary table by source
            - metrics: Aggregated KPIs and summary metrics
            - pv_analysis: PV component time series analysis
            - batt_analysis: Battery component time series analysis
            - chp_analysis: CHP component time series analysis
            - wind_analysis: Wind component time series analysis
            - ev_analysis: EV component time series analysis
            - overview_df: Overview dataframe for main dashboard display

    Note:
        This function is cached with @st.cache_data for performance. The cache
        is automatically invalidated when any input parameters change.
    """
    power_table = compute_energy_summary(master_df, resolution)
    metrics = aggregate_metrics(master_df, resolution)

    # Build component analyses using configuration
    analyses = {
        f"{key}_analysis": build_component_analysis(
            master_df,
            selection_filter=["All"],
            component_label=config["label"],
            value_col_name=config["value_col"],
        )
        for key, config in COMPONENT_CONFIGS.items()
    }

    overview_df = build_overview_df(master_df, component_types)

    return {
        "power_table": power_table,
        "metrics": metrics,
        "pv_analysis": analyses["pv_analysis"],
        "batt_analysis": analyses["batt_analysis"],
        "chp_analysis": analyses["chp_analysis"],
        "wind_analysis": analyses["wind_analysis"],
        "ev_analysis": analyses["ev_analysis"],
        "overview_df": overview_df,
    }


def build_master_df(
    raw_df: pd.DataFrame,
    component_types: Iterable[str],
    mcfg: Any,
    mapper: ColumnMapper,
) -> pd.DataFrame:
    """Transform raw microgrid data into master analysis dataframe.

    Processes raw time-series data from the microgrid to create a comprehensive
    master dataframe suitable for analysis and visualization. Applies data cleaning,
    component aggregation, and column mapping.

    Args:
        raw_df: Raw dataframe with microgrid time-series data. Expected columns
            include timestamp, component IDs, and power/energy measurements.
        component_types: List of component type strings to include in analysis
            (e.g., ['pv', 'battery', 'grid']).
        mcfg: Microgrid configuration object containing component metadata and
            site-specific settings.
        mapper: Column name mapper for converting internal names to display names.

    Returns:
        Master dataframe with processed and aggregated component data, ready for
        analysis and visualization. Includes derived metrics and standardized
        column names.
    """
    component_types = [col for col in component_types if col in raw_df.columns]

    # Now drop components whose meters sum to zero
    component_types = [
        c
        for c in component_types
        if pd.to_numeric(raw_df[c], errors="coerce").fillna(0).sum() != 0
    ]

    master_df = create_energy_report_df(raw_df, component_types, mcfg, mapper)
    return master_df


def render_dashboard(
    master_df: pd.DataFrame,
    resolution: timedelta,
    component_types: Iterable[str],
    mapper: ColumnMapper,
) -> None:
    """Render the complete microgrid reporting dashboard.

    Displays a comprehensive three-section dashboard:
    1. Overview section with summary metric boxes
    2. Interactive plots section with time series and pie charts
    3. Data tables section with detailed component breakdowns

    Args:
        master_df: Master dataframe containing processed microgrid data with all
            component measurements and derived metrics.
        resolution: Time resolution for data aggregation (e.g., timedelta(minutes=15)).
        component_types: List of component types present in the microgrid for
            dynamic tab generation.
        mapper: Column name mapper for display name standardization.

    Returns:
        Renders Streamlit components directly to the app interface.

    Note:
        This function orchestrates the dashboard layout and delegates rendering
        to specialized section modules (summary_boxes, plots_tabs, data_tabs).
    """
    tables = _build_tables(master_df, resolution, component_types)

    # --- Overview section---
    _section_divider()
    sections.render_summary_boxes(tables["metrics"], component_types)

    # --- Plots section---
    _section_divider()
    sections.render_plots_tabs(tables, mapper)

    # --- Tables section---
    _section_divider()
    sections.render_data_tabs(master_df, tables)
