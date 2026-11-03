# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""AgGrid helpers for rendering reporting tables."""

import json
from base64 import b64encode
from collections.abc import Iterable

import pandas as pd
import streamlit as st
from st_aggrid import (
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

_CSV_FORMATS = {
    "de": {"separator": ";", "decimal": ","},
    "en": {"separator": ",", "decimal": "."},
}

_LOCALE_NUMBER_FORMATTER = JsCode("""
    function(params) {
        if (params.value === null || params.value === undefined || params.value === "") {
            return "";
        }

        const value = Number(params.value);
        if (!Number.isFinite(value)) {
            return params.value;
        }

        const gridContext = params.api.getGridOption("context") || params.context || {};
        const language = gridContext.csvFormat;
        const locale = language === "en" ? "en-US" : "de-DE";
        return new Intl.NumberFormat(locale, {
            maximumFractionDigits: 3,
        }).format(value);
    }
""")


def _csv_download_urls(df: pd.DataFrame) -> dict[str, str]:
    """Return data URLs for the supported regional CSV formats.

    German CSV uses a semicolon delimiter and decimal comma, while English CSV
    uses a comma delimiter and decimal point.

    Args:
        df: Dataframe to serialize.

    Returns:
        A mapping from language code to a base64-encoded CSV data URL.
    """
    urls: dict[str, str] = {}
    for language in _CSV_FORMATS:
        csv_bytes = csv_export_bytes(df, language)
        urls[language] = "data:text/csv;charset=utf-8;base64," + b64encode(
            csv_bytes
        ).decode("ascii")
    return urls


def csv_export_bytes(df: pd.DataFrame, language: str) -> bytes:
    """Serialize a dataframe in the CSV format selected for an export."""
    csv_format = _CSV_FORMATS[language]
    return df.to_csv(
        index=False,
        sep=csv_format["separator"],
        decimal=csv_format["decimal"],
    ).encode("utf-8")


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
    csv_format: str = "de",
    column_selection: bool = False,
    initially_visible_columns: Iterable[str] | None = None,
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
        csv_format: Locale used to format numeric values in the grid.
        column_selection: Whether to offer a client-side column chooser in the
            table toolbar.  It does not trigger a Streamlit rerun.
        initially_visible_columns: Columns shown initially when
            ``column_selection`` is enabled.  All other columns remain loaded
            in the browser and can be shown from the column chooser.

    Returns:
        The selected component source when its selector is enabled, otherwise
        ``None``.
    """
    if df is None or not isinstance(df, pd.DataFrame):
        df = pd.DataFrame()

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

    for column_name in df.select_dtypes(include="number").columns:
        gb.configure_column(
            column_name,
            valueFormatter=_LOCALE_NUMBER_FORMATTER,
        )
    for timestamp_column in ("timestamp", "Zeitpunkt"):
        if timestamp_column in df.columns:
            gb.configure_column(timestamp_column, pinned="left")

    grid_options = gb.build()
    if column_selection:
        visible_columns = set(initially_visible_columns or ())
        for column in grid_options["columnDefs"]:
            column["hide"] = column["field"] not in visible_columns
    grid_options["context"] = {"csvFormat": csv_format}
    if component_source:
        grid_options["context"]["componentSource"] = component_source
    grid_options["onGridReady"] = JsCode(f"""
        function(params) {{
            const buttonId = {json.dumps(f"{key_prefix}_reset_table_filters")};
            const toolbarId = {json.dumps(f"{key_prefix}_table_toolbar")};
            const columnSelectionEnabled = {json.dumps(column_selection)};
            const toolbarHeight = {_GRID_TOOLBAR_HEIGHT};
            const gridRoot = document.querySelector(".ag-root-wrapper");
            const gridParent = gridRoot ? gridRoot.parentElement : null;
            if (!gridRoot || !gridParent) {{
                return;
            }}

            // Apply the grid styling inside the component iframe without adding
            // surrounding Streamlit containers, which introduce vertical gaps.
            const gridHeader = gridParent.querySelector(".ag-header");
            if (gridHeader) {{
                Object.assign(gridHeader.style, {{
                    background: {json.dumps(header_color)},
                    color: "#ffffff",
                    borderBottom: "1px solid #d9e1ec",
                }});
            }}
            gridParent.querySelectorAll(".ag-header-cell-label").forEach(
                (label) => {{ label.style.justifyContent = "center"; }}
            );
            gridParent.querySelectorAll(".ag-cell").forEach((cell) => {{
                cell.style.textAlign = "left";
                cell.style.borderColor = "#eef2f7";
            }});
            Object.assign(gridRoot.style, {{
                border: "1px solid #d9e1ec",
                borderRadius: "10px",
                overflow: "hidden",
            }});

            // Streamlit can reuse the component iframe while AgGrid is rebuilt.
            // Discard the toolbar bound to the old grid API before wiring a new one.
            const existingToolbar = document.getElementById(toolbarId);
            if (existingToolbar) {{
                existingToolbar.remove();
            }}

            let gridContext = params.api.getGridOption("context") || params.context || {{}};
            const updateGridContext = function(values) {{
                gridContext = Object.assign({{}}, gridContext, values);
                params.api.setGridOption("context", gridContext);
            }};

            const currentGridHeight = gridRoot.getBoundingClientRect().height;
            if (currentGridHeight > toolbarHeight) {{
                gridRoot.style.height = `${{currentGridHeight - toolbarHeight}}px`;
            }}

            const toolbar = document.createElement("div");
            toolbar.id = toolbarId;
            Object.assign(toolbar.style, {{
                alignItems: "center",
                backgroundColor: "transparent",
                boxSizing: "border-box",
                display: "flex",
                height: `${{toolbarHeight}}px`,
                justifyContent: "flex-start",
                padding: "4px 0 6px 0",
                position: "relative",
            }});

            const componentSource = gridContext.componentSource;
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
                    updateGridContext({{componentSource: sourceSelector.value}});
                    params.api.dispatchEvent({{type: "componentSourceChanged"}});
                }});
                toolbar.appendChild(sourceSelector);
            }}

            if (columnSelectionEnabled) {{
                const columnButton = document.createElement("button");
                columnButton.type = "button";
                columnButton.textContent = "Spalten auswählen";
                columnButton.title = "Datenfelder für Tabelle und CSV auswählen";
                columnButton.setAttribute("aria-label", "Spalten auswählen");
                Object.assign(columnButton.style, {{
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

                const columnPanel = document.createElement("div");
                columnPanel.hidden = true;
                Object.assign(columnPanel.style, {{
                    backgroundColor: "#ffffff",
                    border: "1px solid #d9e1ec",
                    borderRadius: "8px",
                    boxShadow: "0 8px 20px rgba(15, 23, 42, 0.15)",
                    display: "grid",
                    gap: "6px",
                    left: "0",
                    maxHeight: "260px",
                    minWidth: "260px",
                    overflowY: "auto",
                    padding: "10px",
                    position: "absolute",
                    top: "32px",
                    zIndex: "10",
                }});
                const columnPanelHeading = document.createElement("strong");
                columnPanelHeading.textContent = "Datenfelder für Vorschau und CSV";
                columnPanel.appendChild(columnPanelHeading);
                const columnPanelHint = document.createElement("span");
                columnPanelHint.textContent =
                    "Aktivieren Sie die Daten, die angezeigt und heruntergeladen werden sollen.";
                Object.assign(columnPanelHint.style, {{
                    color: "#64748b",
                    fontSize: "11px",
                    lineHeight: "1.35",
                }});
                columnPanel.appendChild(columnPanelHint);
                params.api.getColumns().forEach(function(column) {{
                    const label = document.createElement("label");
                    Object.assign(label.style, {{
                        alignItems: "center",
                        cursor: "pointer",
                        display: "flex",
                        fontSize: "12px",
                        gap: "6px",
                    }});
                    const checkbox = document.createElement("input");
                    checkbox.type = "checkbox";
                    checkbox.checked = column.isVisible();
                    checkbox.addEventListener("change", function() {{
                        params.api.setColumnsVisible([column.getColId()], checkbox.checked);
                    }});
                    label.appendChild(checkbox);
                    label.appendChild(document.createTextNode(column.getColDef().headerName));
                    columnPanel.appendChild(label);
                }});
                columnButton.addEventListener("click", function() {{
                    columnPanel.hidden = !columnPanel.hidden;
                }});
                toolbar.appendChild(columnButton);
                toolbar.appendChild(columnPanel);
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
            const downloadFileName = {json.dumps(download_file_name)};
            if (downloadFileName) {{
                const formatSelector = document.createElement("select");
                formatSelector.title = "CSV-Format auswählen";
                formatSelector.setAttribute("aria-label", "CSV-Format auswählen");
                const formatOptions = [
                    ["de", "Semikolon · Dezimalkomma"],
                    ["en", "Komma · Dezimalpunkt"],
                ];
                for (const [value, label] of formatOptions) {{
                    const option = document.createElement("option");
                    option.value = value;
                    option.textContent = label;
                    formatSelector.appendChild(option);
                }}
                Object.assign(formatSelector.style, {{
                    backgroundColor: "#f1f3f7",
                    border: "1px solid #d9e1ec",
                    borderRadius: "6px",
                    color: "#343845",
                    cursor: "pointer",
                    fontFamily: "inherit",
                    fontSize: "12px",
                    fontWeight: "600",
                    marginLeft: "8px",
                    minHeight: "26px",
                    padding: "4px 8px",
                }});

                const downloadButton = document.createElement("a");
                downloadButton.download = downloadFileName;
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
                const updateDownloadFormat = function() {{
                    updateGridContext({{csvFormat: formatSelector.value}});
                    params.api.refreshCells({{force: true}});
                }};
                downloadButton.addEventListener("click", function(event) {{
                    event.preventDefault();
                    params.api.exportDataAsCsv({{
                        columnKeys: params.api.getAllDisplayedColumns().map(
                            (column) => column.getColId()
                        ),
                        columnSeparator: formatSelector.value === "de" ? ";" : ",",
                        exportedRows: "filteredAndSorted",
                        fileName: downloadButton.download,
                    }});
                }});
                formatSelector.addEventListener("change", updateDownloadFormat);
                updateDownloadFormat();
                toolbar.appendChild(formatSelector);
                toolbar.appendChild(downloadButton);
            }}
            gridParent.insertBefore(toolbar, gridRoot);
        }}
    """)

    # Render the grid directly.  Surrounding it with Markdown/container elements
    # makes Streamlit add vertical gaps before the toolbar inside tab panels.
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

    if component_source and grid_response:
        selected_source = grid_response.get("component_source")
        if isinstance(selected_source, str):
            return selected_source
    return None
