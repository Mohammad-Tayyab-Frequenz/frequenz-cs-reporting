# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Battery optimization savings calculations and rendering."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import streamlit as st

from frequenz.cs_reporting.components.battery_plots import (
    NORMALIZED_PLOT_METRICS,
    build_daily_battery_optimization_figure,
    build_normalized_battery_optimization_figure,
)
from frequenz.cs_reporting.components.ui import (
    render_plot_card,
    render_section_divider,
)
from frequenz.cs_reporting.services.battery_optimization_calculations import (
    AGGREGATION_OPTIONS,
    build_battery_optimization_results_table,
    calculate_battery_optimization_intervals,
    calculate_selection_metrics,
)
from frequenz.cs_reporting.utils.timing import log_duration
from frequenz.cs_reporting.views.battery_kpis import (
    build_battery_optimization_kpi_boxes,
)
from frequenz.cs_reporting.views.metric_renderers import render_box_section
from frequenz.cs_reporting.views.table_renderers import render_table_section

_KPI_CARDS_PER_ROW = 4
_OPERATING_KPI_CARDS_PER_ROW = 4
_PRIMARY_PLOT_METRICS = ("battery_price_spread_eur_per_mwh",)
_SECONDARY_PLOT_METRICS = (
    # "value_per_kwh_capacity",  # Temporarily hidden.
    "battery_cycles",
)


def render_battery_optimization(
    master_df: pd.DataFrame,
    resolution: timedelta,
    battery_capacity_kwh: float | None = None,
    battery_capacity_data: pd.DataFrame | None = None,
) -> None:
    """Render the battery optimization savings KPI and daily summary plot."""
    try:
        with log_duration("battery.calculate_intervals"):
            interval_data = calculate_battery_optimization_intervals(
                master_df, resolution, battery_capacity_data
            )
    except ValueError as exc:
        st.info(str(exc))
        return

    with log_duration("battery.calculate_selection_metrics"):
        normalized_metrics = calculate_selection_metrics(interval_data)
    kpi_boxes = build_battery_optimization_kpi_boxes(normalized_metrics)
    st.subheader("Batterie Reporting")
    with log_duration("battery.render_kpis_primary"):
        render_box_section(
            "Speichermehrwert",
            kpi_boxes[:_KPI_CARDS_PER_ROW],
            accent="#14b8a6",
            icon="🔋",
            value_colors={"Netto-Einsparung (€)": "#16a34a"},
            grid_class="kpi-grid--featured-first",
        )
    render_section_divider("Diagramme")
    with log_duration("battery.render_plots_primary"):
        _render_battery_optimization_plot_tabs(
            interval_data,
            battery_capacity_kwh,
            _PRIMARY_PLOT_METRICS,
            include_optimization=True,
        )

    with log_duration("battery.render_kpis_operating"):
        render_box_section(
            "Betriebskennzahlen",
            kpi_boxes[
                _KPI_CARDS_PER_ROW : _KPI_CARDS_PER_ROW + _OPERATING_KPI_CARDS_PER_ROW
            ],
            accent="#14b8a6",
            icon="⚙",
            grid_class="kpi-grid--two-by-two",
        )
    render_section_divider("Diagramme")
    with log_duration("battery.render_plots_secondary"):
        _render_battery_optimization_plot_tabs(
            interval_data,
            battery_capacity_kwh,
            _SECONDARY_PLOT_METRICS,
        )

    render_section_divider("Datentabellen")
    with log_duration("battery.build_results_table"):
        results_table = build_battery_optimization_results_table(
            interval_data,
            resolution,
            battery_capacity_kwh=battery_capacity_kwh,
        )
    with log_duration("battery.render_results_table"):
        render_table_section(
            results_table,
            key_prefix="battery_optimization_results",
            empty_info="Keine Berechnungsdaten verfügbar.",
        )


def _render_battery_optimization_plot_tabs(
    interval_data: pd.DataFrame,
    battery_capacity_kwh: float | None,
    metric_keys: tuple[str, ...],
    *,
    include_optimization: bool = False,
) -> None:
    """Render one ordered group of battery optimization plot tabs."""
    metric_labels = {
        metric_key: label for metric_key, label, _ in NORMALIZED_PLOT_METRICS
    }
    tab_labels = {
        "battery_price_spread_eur_per_mwh": "Preis-Spread",
        "value_per_kwh_capacity": "Kapazität",
        "battery_cycles": "Zyklen",
    }
    plot_configs: list[tuple[str, str, str | None]] = []
    if include_optimization:
        plot_configs.append(("battery_optimization", "Netto-Einsparung", None))
    plot_configs.extend(
        (
            f"battery_optimization_{metric_key}",
            metric_labels[metric_key],
            metric_key,
        )
        for metric_key in metric_keys
    )
    labels = (["Netto-Einsparung"] if include_optimization else []) + [
        tab_labels[metric_key] for metric_key in metric_keys
    ]
    if len(plot_configs) == 1:
        plot_key, title, metric_key = plot_configs[0]
        _BATTERY_PLOT_FRAGMENT_RENDERERS[plot_key](
            interval_data=interval_data,
            battery_capacity_kwh=battery_capacity_kwh,
            plot_key=plot_key,
            title=title,
            metric_key=metric_key,
        )
        return

    plot_tabs = st.tabs(labels)
    for tab, (plot_key, title, metric_key) in zip(plot_tabs, plot_configs):
        with tab:
            _BATTERY_PLOT_FRAGMENT_RENDERERS[plot_key](
                interval_data=interval_data,
                battery_capacity_kwh=battery_capacity_kwh,
                plot_key=plot_key,
                title=title,
                metric_key=metric_key,
            )


def _render_battery_optimization_plot(
    interval_data: pd.DataFrame,
    battery_capacity_kwh: float | None,
    plot_key: str,
    title: str,
    metric_key: str | None,
) -> None:
    """Render one independently refreshable battery optimization plot."""
    aggregation_key = f"{plot_key}_aggregation"
    aggregation = str(st.session_state.get(aggregation_key, "daily"))

    def aggregation_selector() -> None:
        st.selectbox(
            "Aggregation",
            options=tuple(AGGREGATION_OPTIONS),
            format_func=lambda value: AGGREGATION_OPTIONS[str(value)],
            key=aggregation_key,
            label_visibility="collapsed",
        )

    with log_duration(f"battery.plot.{plot_key}.build_figure"):
        if metric_key is None:
            fig = build_daily_battery_optimization_figure(interval_data, aggregation)
        else:
            fig = build_normalized_battery_optimization_figure(
                interval_data,
                metric_key,
                aggregation,
                battery_capacity_kwh=battery_capacity_kwh,
            )
    with log_duration(f"battery.plot.{plot_key}.render_card"):
        render_plot_card(
            title,
            fig,
            header_control=aggregation_selector,
            key=plot_key,
        )


_BATTERY_PLOT_FRAGMENT_RENDERERS = {
    # Do not pass ``key=`` here: the project and existing Deepnote image support
    # Streamlit 1.49, whose fragment API only accepts ``func`` and ``run_every``.
    # Each call is still an independent fragment because it occupies a distinct
    # tab/render location in the Streamlit element tree.
    plot_key: st.fragment(_render_battery_optimization_plot)
    for plot_key in (
        "battery_optimization",
        "battery_optimization_battery_price_spread_eur_per_mwh",
        # "battery_optimization_value_per_kwh_capacity",  # Temporarily hidden.
        "battery_optimization_battery_cycles",
    )
}
