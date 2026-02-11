# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Table rendering functions for the reporting views."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from frequenz.cs_reporting.components import tables
from frequenz.cs_reporting.constants import TablesResult


def _round_numeric_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of `df` with number columns rounded to three decimals."""
    rounded_df = df.copy()
    numeric_cols = rounded_df.select_dtypes(include="number").columns
    if not numeric_cols.empty:
        rounded_df[numeric_cols] = rounded_df[numeric_cols].round(3)
    return rounded_df


TABLE_TAB_SPECS = [
    {
        "label": "Power Mix",
        "table_key": "power_table",
        "key_prefix": "power_mix",
        "caption": "Aggregated energy mix from PV vs. grid",
    },
    {
        "label": "PV Energy (per component)",
        "table_key": "pv_energy_table",
        "key_prefix": "pv_energy",
        "caption": "Summary PV energy production (per component)",
        "empty_info": "No PV energy data available.",
    },
    {
        "label": "PV Analysis",
        "table_key": "pv_analysis",
        "key_prefix": "pv_analysis",
        "caption": "PV energy production (time series)",
        "empty_info": "No PV analysis data available.",
    },
    {
        "label": "Battery Analysis",
        "table_key": "batt_analysis",
        "key_prefix": "batt_analysis",
        "caption": "Battery components (time series)",
        "empty_info": "No battery data available.",
    },
    {
        "label": "Wind Analysis",
        "table_key": "wind_analysis",
        "key_prefix": "wind_analysis",
        "caption": "Wind components (time series)",
        "empty_info": "No wind data available.",
    },
    {
        "label": "BHKW Analysis",
        "table_key": "chp_analysis",
        "key_prefix": "chp_analysis",
        "caption": "BHKW components (time series)",
        "empty_info": "No BHKW data available.",
    },
    {
        "label": "EV Analysis",
        "table_key": "ev_analysis",
        "key_prefix": "ev_analysis",
        "caption": "EV components (time series)",
        "empty_info": "No EV data available.",
    },
]


def _style_download_button(
    column: st.delta_generator.DeltaGenerator,
    *,
    width: int = 170,
    color: str = "#1e88e5",
) -> None:
    """Inject CSS so the download button matches the dashboard styling."""
    column.markdown(
        f"""
        <style>
        div[data-testid="stDownloadButton"] {{
            float: right;
            margin-top: 0;
            margin-bottom: 0;
            display: inline-flex;
        }}
        div[data-testid="stDownloadButton"] button {{
            min-width: {width}px;
            background-color: {color} !important;
            color: #ffffff !important;
            border: 0 !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_table_section(
    df: pd.DataFrame | None,
    *,
    key_prefix: str,
    caption: str | None = None,
    empty_info: str | None = None,
) -> None:
    """Render a captioned AgGrid table, safely handling None/empty data.

    Args:
        df: The dataframe to display. If ``None`` or empty, an empty table is shown
            and an optional info message is rendered.
        key_prefix: Unique key prefix for the grid instance (used by Streamlit state).
        caption: Optional caption shown above the table.
        empty_info: Optional info message to show when ``df`` is ``None`` or empty.

    Returns:
        Streamlit components are rendered directly.
    """
    safe_df = df if (df is not None and not df.empty) else pd.DataFrame()
    display_df = _round_numeric_columns(safe_df)
    header_cols = st.columns([8, 1])
    if caption:
        header_cols[0].caption(caption)
    else:
        header_cols[0].markdown("", unsafe_allow_html=True)

    if not safe_df.empty:
        csv_bytes = display_df.to_csv(index=False).encode("utf-8")
        _style_download_button(header_cols[1])
        header_cols[1].download_button(
            label="Download table CSV",
            data=csv_bytes,
            file_name=f"{key_prefix}.csv",
            mime="text/csv",
            key=f"{key_prefix}_download",
        )

    tables.aggrid_table(display_df, key_prefix=key_prefix)

    if (df is None or df.empty) and empty_info:
        st.info(empty_info)


def render_master_df(master_df: pd.DataFrame) -> None:
    """Render the combined master dataframe in an AgGrid table.

    Args:
        master_df: Processed master dataframe to display.

    Returns:
        Streamlit components are rendered directly.
    """
    if master_df is not None and not master_df.empty:
        header_cols = st.columns([10, 1])
        header_cols[0].caption("Standardized master dataframe")
        display_df = _round_numeric_columns(master_df)
        master_csv = display_df.to_csv(index=False).encode("utf-8")
        _style_download_button(header_cols[1])
        header_cols[1].download_button(
            label="Download combined dataframe",
            data=master_csv,
            file_name="master_df.csv",
            mime="text/csv",
            key="master_df_download",
        )
        tables.aggrid_table(
            display_df,
            key_prefix="master_df",
        )
    else:
        st.info("Master DF unavailable (no MicrogridConfig).")


def render_data_tabs(master_df: pd.DataFrame, tables_dict: TablesResult) -> None:
    """Render tabbed data tables for overview and component analyses.

    Args:
        master_df: Processed master dataframe.
        tables_dict: Mapping of table names to dataframes for each analysis.

    Returns:
        Streamlit components are rendered directly.
    """
    st.subheader("Data Tables")
    available_specs = []
    for spec in TABLE_TAB_SPECS:
        value = tables_dict.get(spec["table_key"])
        if isinstance(value, pd.DataFrame) and not value.empty:
            available_specs.append(spec)

    include_master = master_df is not None and not master_df.empty

    if not available_specs and not include_master:
        st.info("No data tables available.")
        return

    tab_labels = [spec["label"] for spec in available_specs]
    if include_master:
        tab_labels.append("Combined DF")
    tabs = st.tabs(tab_labels)

    for tab, spec in zip(tabs, available_specs):
        value = tables_dict.get(spec["table_key"])
        with tab:
            render_table_section(
                value if isinstance(value, pd.DataFrame) else None,
                key_prefix=spec["key_prefix"],
                caption=spec.get("caption"),
                empty_info=spec.get("empty_info"),
            )

    if include_master:
        with tabs[-1]:
            render_master_df(master_df)
