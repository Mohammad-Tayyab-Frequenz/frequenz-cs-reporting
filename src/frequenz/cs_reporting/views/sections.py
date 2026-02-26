# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Reporting views sections - facade module for backward compatibility.

This module re-exports rendering functions from specialized modules:
- table_renderers: Table rendering functions
- plot_renderers: Plot rendering functions
- metric_renderers: Metric box rendering functions
"""

from __future__ import annotations

# Re-export from constants
from frequenz.cs_reporting.constants import COLOR_DICT as color_dict

# Re-export from metric_renderers
from .metric_renderers import render_box_grid, render_summary_boxes

# Re-export from plot_renderers
from .plot_renderers import (
    render_energy_pie_chart,
    render_plots_tabs,
    render_time_series,
)

# Re-export from table_renderers
from .table_renderers import render_data_tabs, render_master_df, render_table_section

__all__ = [
    # Table renderers
    "render_table_section",
    "render_master_df",
    "render_data_tabs",
    # Plot renderers
    "render_time_series",
    "render_energy_pie_chart",
    "render_plots_tabs",
    "color_dict",
    # Metric renderers
    "render_summary_boxes",
    "render_box_grid",
]
