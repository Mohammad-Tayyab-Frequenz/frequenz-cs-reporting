# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""AgGrid helpers for rendering reporting tables."""

import json
from base64 import b64encode

import pandas as pd
import streamlit as st
from st_aggrid import (  # type: ignore[import-untyped]
    AgGrid,
    ColumnsAutoSizeMode,
    DataReturnMode,
    GridOptionsBuilder,
    GridUpdateMode,
    JsCode,
)

_GRID_HEADER_HEIGHT = 40
_GRID_ROW_HEIGHT = 44
_GRID_PAGINATION_HEIGHT = 56
_GRID_BORDER_HEIGHT = 2
_GRID_TOOLBAR_HEIGHT = 40


# pylint: disable=too-many-arguments, too-many-locals
def aggrid_table(
    df: pd.DataFrame,
    *,
    key_prefix: str,
    page_size: int = 7,
    header_color: str = "#1e4f87",
    height: int | None = None,
    theme: str = "balham",  # 'alpine' | 'balham' | 'material' | etc.
    default_col_width: int = 180,
    min_col_width: int = 160,
    download_file_name: str | None = None,
    component_source: str | None = None,
) -> str | None:
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
        download_file_name: Optional CSV filename. When provided, a download
            button is rendered beside the filter-reset button.
        component_source: Selected component source. When provided, its selector
            is rendered before the reset and download buttons.

    Returns:
        The selected component source when its selector is enabled, otherwise
        ``None``.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()

    # Initialize session state for page size if it doesn't exist
    if f"{key_prefix}_page_size" not in st.session_state:
        st.session_state[f"{key_prefix}_page_size"] = page_size
    page_size = int(st.session_state[f"{key_prefix}_page_size"])
    visible_rows = min(max(len(df), 1), page_size)
    if height is None:
        height = (
            _GRID_HEADER_HEIGHT
            + (visible_rows * _GRID_ROW_HEIGHT)
            + _GRID_PAGINATION_HEIGHT
            + _GRID_BORDER_HEIGHT
        )

    # --- Build grid options from dataframe ---
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_pagination(
        enabled=True,
        paginationAutoPageSize=False,
        paginationPageSize=page_size,
    )
    gb.configure_grid_options(
        headerHeight=_GRID_HEADER_HEIGHT,
        rowHeight=_GRID_ROW_HEIGHT,
        paginationPageSizeSelector=False,
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

    grid_options = gb.build()
    if component_source:
        grid_options["context"] = {"componentSource": component_source}
    download_url = None
    if download_file_name:
        csv_bytes = df.to_csv(index=False, sep=";", decimal=",").encode("utf-8")
        download_url = "data:text/csv;charset=utf-8;base64," + b64encode(
            csv_bytes
        ).decode("ascii")
    grid_options["onGridReady"] = JsCode(f"""
        function(params) {{
            const buttonId = {json.dumps(f"{key_prefix}_reset_table_filters")};
            const toolbarHeight = {_GRID_TOOLBAR_HEIGHT};
            const existingButton = document.getElementById(buttonId);
            if (existingButton) {{
                return;
            }}

            const gridRoot = document.querySelector(".ag-root-wrapper");
            const gridParent = gridRoot ? gridRoot.parentElement : null;
            if (!gridRoot || !gridParent) {{
                return;
            }}

            const currentGridHeight = gridRoot.getBoundingClientRect().height;
            if (currentGridHeight > toolbarHeight) {{
                gridRoot.style.height = `${{currentGridHeight - toolbarHeight}}px`;
            }}

            const toolbar = document.createElement("div");
            Object.assign(toolbar.style, {{
                alignItems: "center",
                backgroundColor: "transparent",
                boxSizing: "border-box",
                display: "flex",
                height: `${{toolbarHeight}}px`,
                justifyContent: "flex-start",
                padding: "4px 0 6px 0",
            }});

            const componentSource = params.context && params.context.componentSource;
            if (componentSource) {{
                const sourceSelector = document.createElement("select");
                sourceSelector.title = "Komponentenquelle auswählen";
                sourceSelector.setAttribute("aria-label", "Komponentenquelle auswählen");
                const sourceOptions = [
                    ["meter", "Meter"],
                    ["inverter", "Inverter / Komponenten"],
                ];
                for (const [value, label] of sourceOptions) {{
                    const option = document.createElement("option");
                    option.value = value;
                    option.textContent = label;
                    option.selected = value === componentSource;
                    sourceSelector.appendChild(option);
                }}
                Object.assign(sourceSelector.style, {{
                    backgroundColor: "#f1f3f7",
                    border: "1px solid #d9e1ec",
                    borderRadius: "6px",
                    color: "#343845",
                    cursor: "pointer",
                    fontFamily: "inherit",
                    fontSize: "12px",
                    fontWeight: "600",
                    minHeight: "26px",
                    padding: "4px 8px",
                }});
                sourceSelector.addEventListener("change", function() {{
                    params.context.componentSource = sourceSelector.value;
                    params.api.dispatchEvent({{type: "componentSourceChanged"}});
                }});
                toolbar.appendChild(sourceSelector);
            }}

            const button = document.createElement("button");
            button.id = buttonId;
            button.type = "button";
            button.textContent = "Filter zurücksetzen";
            button.title = "Filter der Tabelle zurücksetzen";
            button.setAttribute("aria-label", "Filter der Tabelle zurücksetzen");

            Object.assign(button.style, {{
                backgroundColor: "#fff4bf",
                border: "1px solid #e4c34a",
                color: "#4f3f00",
                borderRadius: "6px",
                cursor: "pointer",
                fontFamily: "inherit",
                fontSize: "12px",
                fontWeight: "600",
                lineHeight: "1.1",
                minHeight: "26px",
                padding: "4px 8px",
                whiteSpace: "nowrap",
            }});

            button.addEventListener("mouseenter", function() {{
                button.style.backgroundColor = "#ffe88a";
                button.style.borderColor = "#c7a629";
                button.style.color = "#3f3200";
            }});
            button.addEventListener("mouseleave", function() {{
                button.style.backgroundColor = "#fff4bf";
                button.style.borderColor = "#e4c34a";
                button.style.color = "#4f3f00";
            }});

            button.addEventListener("click", function(event) {{
                event.preventDefault();
                event.stopPropagation();

                params.api.setFilterModel(null);
                params.api.onFilterChanged();
                params.api.paginationGoToFirstPage();
            }});

            toolbar.appendChild(button);
            const downloadUrl = {json.dumps(download_url)};
            if (downloadUrl) {{
                const downloadButton = document.createElement("a");
                downloadButton.href = downloadUrl;
                downloadButton.download = {json.dumps(download_file_name)};
                downloadButton.textContent = "CSV herunterladen";
                downloadButton.title = "Tabelle als CSV herunterladen";
                downloadButton.setAttribute("aria-label", "Tabelle als CSV herunterladen");

                Object.assign(downloadButton.style, {{
                    alignItems: "center",
                    backgroundColor: "#1e4f87",
                    border: "1px solid #1e4f87",
                    borderRadius: "6px",
                    color: "#ffffff",
                    cursor: "pointer",
                    display: "inline-flex",
                    fontFamily: "inherit",
                    fontSize: "12px",
                    fontWeight: "600",
                    lineHeight: "1.1",
                    marginLeft: "8px",
                    minHeight: "26px",
                    padding: "4px 8px",
                    textDecoration: "none",
                    whiteSpace: "nowrap",
                }});

                downloadButton.addEventListener("mouseenter", function() {{
                    downloadButton.style.backgroundColor = "#163d6a";
                    downloadButton.style.borderColor = "#163d6a";
                }});
                downloadButton.addEventListener("mouseleave", function() {{
                    downloadButton.style.backgroundColor = "#1e4f87";
                    downloadButton.style.borderColor = "#1e4f87";
                }});
                toolbar.appendChild(downloadButton);
            }}
            gridParent.insertBefore(toolbar, gridRoot);
        }}
    """)

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
        grid_response = AgGrid(
            df,
            gridOptions=grid_options,
            height=height + _GRID_TOOLBAR_HEIGHT,
            theme=theme,
            allow_unsafe_jscode=True,
            update_mode=GridUpdateMode.NO_UPDATE,
            update_on=(["componentSourceChanged"] if component_source else []),
            data_return_mode=(
                DataReturnMode.CUSTOM if component_source else DataReturnMode.FILTERED
            ),
            custom_jscode_for_grid_return=(JsCode("""
                    function({eventData}) {
                        return {component_source: eventData.context.componentSource};
                    }
                    """) if component_source else None),
            fit_columns_on_grid_load=False,
            columns_auto_size_mode=ColumnsAutoSizeMode.NO_AUTOSIZE,
            key=key_prefix,
        )
        st.markdown("</div>", unsafe_allow_html=True)

    if component_source and grid_response:
        selected_source = grid_response.get("component_source")
        if isinstance(selected_source, str):
            return selected_source
    return None
