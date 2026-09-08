# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Render helpers for solar workflow results."""

from __future__ import annotations

import math
from typing import Any
from urllib.parse import quote

import plotly.graph_objects as go
import streamlit as st
from frequenz.lib.notebooks.solar.maintenance.microgrid_dashboard import (
    MicrogridOverviewDashboard,
)
from frequenz.lib.notebooks.solar.maintenance.solar_maintenance_app import (
    SolarAnalysisData,
)

from frequenz.cs_reporting.components.ui import render_plot_card


def _render_production_table(plot_data: SolarAnalysisData) -> None:
    """Render the production statistics dashboard, if available.

    Displays the production statistics using the card-based microgrid overview
    dashboard provided by ``frequenz.lib.notebooks``. If no production table is
    present or it is empty, the function returns without rendering anything.

    Args:
        plot_data: Solar analysis result object that may contain a
            ``production_table_view`` attribute with tabular production statistics.

    Returns:
        None. The dashboard is rendered directly in the Streamlit UI.
    """
    table_view = getattr(plot_data, "production_table_view", None)
    if table_view is None or table_view.empty:
        return

    st.markdown("#### Produktionsstatistiken")
    dashboard = MicrogridOverviewDashboard(table_view, 1)
    dashboard_html = dashboard.to_html().replace(
        "justify-content: center;",
        "justify-content: flex-start;",
    )

    # The notebook implementation uses IPython display(). In Streamlit we need
    # the same generated HTML rendered through the component API instead.
    cards_per_row = 2
    estimated_rows = max(1, math.ceil(len(table_view) / cards_per_row))
    height = min(140 + estimated_rows * 430, 1600)

    st.iframe(
        f"data:text/html;charset=utf-8,{quote(dashboard_html)}",
        height=height,
    )


def _plot_title(fig: go.Figure, fallback: str) -> str:
    """Return the Plotly layout title when available, otherwise a fallback."""
    title = fig.layout.title.text
    return str(title) if title else fallback


# pylint: disable=too-many-branches
def render_workflow_results(plot_data: Any, figures: list[go.Figure]) -> None:
    """Render and display results returned by the solar workflow.

    Handles multiple possible result types produced by the workflow and renders
    them appropriately in the Streamlit UI. Supported outputs include structured
    analysis objects, dictionaries, lists of figures or tables, Plotly figures,
    and generic displayable values. Plotly figures emitted during the workflow
    are displayed in a dedicated section.

    Args:
        plot_data:
            Result object returned by the workflow. This may be a
            ``SolarAnalysisData`` instance, a dictionary, a list of renderable
            objects, a Plotly figure, or a generic displayable value.
        figures:
            Plotly figures collected from the workflow's plot managers.

    Returns:
        None. All outputs are rendered directly in the Streamlit UI.
    """
    if not plot_data:
        st.warning("Vom Workflow wurden keine Daten zurückgegeben.")
        return

    if isinstance(plot_data, SolarAnalysisData):
        _render_production_table(plot_data)

    elif isinstance(plot_data, dict):
        for key, value in plot_data.items():
            st.subheader(key)
            if isinstance(value, go.Figure):
                render_plot_card(str(key), value)
            else:
                st.write(value)

    elif isinstance(plot_data, list):
        for idx, item in enumerate(plot_data, start=1):
            if isinstance(item, go.Figure):
                render_plot_card(_plot_title(item, f"Diagramm {idx}"), item)
            else:
                st.write(item)
    elif isinstance(plot_data, go.Figure):
        render_plot_card(_plot_title(plot_data, "Solar-Diagramm"), plot_data)
    else:
        st.write(plot_data)

    populated_figures = [figure for figure in figures if figure.data]
    if populated_figures:
        st.divider()
        st.markdown("#### Workflow-Abbildungen")

        for idx, fig in enumerate(populated_figures, start=1):
            render_plot_card(_plot_title(fig, f"Abbildung {idx}"), fig)
    elif isinstance(plot_data, SolarAnalysisData):
        st.warning("Der Workflow hat keine darstellbaren Diagramme erzeugt.")
