# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""AgGrid helpers for rendering reporting tables."""

import pandas as pd
import streamlit as st
from st_aggrid import (  # type: ignore[import-untyped]
    AgGrid,
    ColumnsAutoSizeMode,
    GridOptionsBuilder,
    GridUpdateMode,
)


# pylint: disable=too-many-arguments
def aggrid_table(
    df: pd.DataFrame,
    *,
    key_prefix: str,
    page_size: int = 12,
    header_color: str = "#1e4f87",
    height: int = 420,
    theme: str = "balham",  # 'alpine' | 'balham' | 'material' | etc.
    default_col_width: int = 180,
    min_col_width: int = 160,
) -> None:
    """Render a dataframe using AgGrid with sensible defaults.

    Args:
        df: Dataframe to display; an empty dataframe is used when invalid.
        key_prefix: Unique prefix for Streamlit state keys.
        page_size: Preferred page size for pagination controls.
        header_color: Header background color.
        height: Height of the grid container in pixels.
        theme: AgGrid theme name.
        default_col_width: Default column width in pixels.
        min_col_width: Minimum column width in pixels.

    Returns:
        Streamlit components are rendered directly.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()

    # Initialize session state for page size if it doesn't exist
    if f"{key_prefix}_page_size" not in st.session_state:
        st.session_state[f"{key_prefix}_page_size"] = page_size

    # --- Build grid options from dataframe ---
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_pagination(
        enabled=True,
        paginationAutoPageSize=True,
        # paginationPageSize=st.session_state[f'{key_prefix}_page_size'],
    )

    gb.configure_default_column(
        resizable=True,
        sortable=True,
        filter=True,
        wrapText=False,
        autoHeight=False,
        width=default_col_width,
        minWidth=min_col_width,
        cellStyle={"textAlign": "left"},  # left-align body cells
        suppressSizeToFit=True,
        suppressAutoSize=True,
    )

    # Fit columns on first load
    grid_options = gb.build()

    # --- Scoped CSS: restrained header + clean grid lines ---
    container_id = f"agc_{key_prefix}"
    st.markdown(
        f"""
        <style>
        /* scope to this grid instance only */
        #{container_id} .ag-theme-{theme} .ag-header {{
            background: {header_color} !important;
            color: #fff !important;
            border-bottom: 1px solid #d9e1ec !important;
        }}
        #{container_id} .ag-theme-{theme} .ag-header-cell-label {{
            justify-content: center;     /* center header text */
        }}
        #{container_id} .ag-theme-{theme} .ag-cell {{
            text-align: left !important; /* left align body */
            border-color: #eef2f7 !important;
        }}
        #{container_id} .ag-theme-{theme} .ag-root-wrapper {{
            border: 1px solid #d9e1ec !important;
            border-radius: 10px !important;
            overflow: hidden !important;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    # --- Render grid ---
    with st.container():
        st.markdown(f'<div id="{container_id}">', unsafe_allow_html=True)
        _ = AgGrid(
            df,
            gridOptions=grid_options,
            height=height,
            theme=theme,
            update_mode=GridUpdateMode.NO_UPDATE,
            fit_columns_on_grid_load=False,
            columns_auto_size_mode=ColumnsAutoSizeMode.NO_AUTOSIZE,
            key=key_prefix,
        )
        st.markdown("</div>", unsafe_allow_html=True)
