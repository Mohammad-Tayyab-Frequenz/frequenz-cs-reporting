# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Battery optimization savings calculations and rendering."""

from __future__ import annotations

from datetime import timedelta
from math import isfinite

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frequenz.cs_reporting.components.ui import (
    render_plot_card,
    render_section_divider,
)
from frequenz.cs_reporting.services.battery_optimization_calculations import (
    AGGREGATION_OPTIONS,
    SUMMARY_VALUE_COLUMNS,
    aggregate_battery_optimization_intervals,
    aggregate_battery_optimization_summary,
    build_battery_optimization_results_table,
    calculate_battery_optimization_intervals,
    calculate_normalized_battery_optimization_metrics,
    calculate_selection_metrics,
    with_plot_value_column_aliases,
)
from frequenz.cs_reporting.ui_resources import load_tooltips
from frequenz.cs_reporting.utils.timing import log_duration
from frequenz.cs_reporting.views.metric_renderers import render_box_section
from frequenz.cs_reporting.views.table_renderers import render_table_section

_KPI_CARDS_PER_ROW = 4
_OPERATING_KPI_CARDS_PER_ROW = 4
_PRIMARY_PLOT_METRICS = ("battery_price_spread_eur_per_mwh",)
_SECONDARY_PLOT_METRICS = (
    # "value_per_kwh_capacity",  # Temporarily hidden.
    "battery_cycles",
)
_NORMALIZED_PLOT_METRICS = (
    ("value_per_mwh_throughput", "Wert pro MWh Batteriedurchsatz (€/MWh)", "€"),
    ("value_per_mwh_discharged", "Wert pro MWh entladene Energie (€/MWh)", "€"),
    ("battery_price_spread_eur_per_mwh", "Preis-Spread Batterie (€/MWh)", "€"),
    ("value_per_kwh_capacity", "Wert pro kWh Batteriekapazität (€/kWh)", "€"),
    ("battery_cycles", "Batteriezyklen (Vollzyklen)", ""),
)
_HIDDEN_NORMALIZED_METRICS = frozenset(
    {"value_per_mwh_throughput", "value_per_mwh_discharged"}
)
_KPI_TOOLTIPS = load_tooltips("battery_optimization")


def _format_full_eur(value: float) -> str:
    """Format a monetary value as whole euros."""
    if pd.isna(value) or not isfinite(float(value)):
        return ""
    rounded_value = round(value)
    formatted_value = f"{abs(rounded_value):,}".replace(",", ".")
    if rounded_value < 0:
        return f"-€{formatted_value}"
    return f"€{formatted_value}"


def _format_eur_with_decimals(value: float) -> str:
    """Format a monetary value with two decimal places."""
    if pd.isna(value) or not isfinite(float(value)):
        return ""
    formatted_value = f"{abs(value):,.2f}".replace(",", "X")
    formatted_value = formatted_value.replace(".", ",").replace("X", ".")
    return f"-€{formatted_value}" if value < 0 else f"€{formatted_value}"


def _format_cycle_count(value: float) -> str:
    """Format an equivalent full-cycle count for a bar label."""
    if pd.isna(value) or not isfinite(float(value)):
        return ""
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_daily_battery_optimization_figure(
    daily_summary: pd.DataFrame,
    aggregation: str = "daily",
) -> go.Figure:
    """Build the battery values and optimization result combination chart."""
    fig = go.Figure()
    summary_with_aliases = with_plot_value_column_aliases(daily_summary)
    period_summary = with_plot_value_column_aliases(
        aggregate_battery_optimization_intervals(summary_with_aliases, aggregation)
        if "timestamp" in summary_with_aliases.columns
        else aggregate_battery_optimization_summary(summary_with_aliases, aggregation)
    )
    if period_summary.empty:
        fig.update_layout(
            height=420,
            paper_bgcolor="#ffffff",
            plot_bgcolor="#f8fafc",
            showlegend=False,
            annotations=[
                {
                    "text": "Keine Tagesdaten zur Anzeige",
                    "x": 0.5,
                    "xref": "paper",
                    "y": 0.5,
                    "yref": "paper",
                    "showarrow": False,
                    "font": {"size": 13, "color": "#94a3b8"},
                }
            ],
        )
        return fig

    x_values = period_summary["period_label"]
    bar_specs = (
        ("charging_value_eur", "Wert Entladung", "rgba(236,0,140,1)"),
        ("discharging_cost_eur", "Wert Beladung", "rgba(146,219,68,1)"),
    )
    for column, name, color in bar_specs:
        values = period_summary[column]
        fig.add_trace(
            go.Bar(
                x=x_values,
                y=values,
                marker={
                    "color": color,
                    "line": {"color": color, "width": 1},
                },
                text=values.map(_format_full_eur),
                textposition="outside",
                textangle=270,
                cliponaxis=False,
                hovertemplate=(f"<b>%{{x}}</b><br>{name}: €%{{y:,.2f}}<extra></extra>"),
                name=name,
            )
        )

    savings = period_summary["optimization_savings_eur"]
    fig.add_trace(
        go.Scatter(
            x=x_values,
            y=savings,
            mode="lines+markers",
            line={"color": "rgba(100,116,139,1)", "width": 3},
            marker={
                "color": "rgba(100,116,139,1)",
                "line": {"color": "rgba(71,85,105,1)", "width": 1},
                "size": 9,
            },
            hovertemplate=(
                "<b>%{x}</b><br>Netto-Einsparung: " "€%{y:,.2f}<extra></extra>"
            ),
            name="Netto-Einsparung",
        )
    )
    fig.update_layout(
        barmode="group",
        height=460,
        margin={"t": 40, "r": 36, "b": 82, "l": 72},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#fbfdff",
        font={
            "family": "Inter, Segoe UI, Arial, sans-serif",
            "size": 12,
            "color": "#374151",
        },
        showlegend=True,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "bgcolor": "rgba(255,255,255,0.85)",
            "bordercolor": "#e2e8f0",
            "borderwidth": 1,
            "font": {"size": 11, "color": "#374151"},
        },
        xaxis_title=AGGREGATION_OPTIONS[aggregation],
        yaxis_title="Wert / Kostenwirkung (€)",
        hoverlabel={
            "bgcolor": "#1e293b",
            "font_size": 12,
            "font_color": "#f8fafc",
            "bordercolor": "#334155",
        },
        separators=",.",
        uniformtext={"mode": "show", "minsize": 10},
    )
    fig.update_xaxes(
        gridcolor="#edf2f7",
        linecolor="#cbd5e1",
        tickfont={"size": 11, "color": "#64748b"},
        title_font={"size": 12, "color": "#475569"},
    )
    fig.update_yaxes(
        gridcolor="#e2e8f0",
        linecolor="#cbd5e1",
        tickfont={"size": 11, "color": "#64748b"},
        tickprefix="€",
        title_font={"size": 12, "color": "#475569"},
        zeroline=True,
        zerolinecolor="#64748b",
        zerolinewidth=1.5,
    )
    return fig


def build_normalized_battery_optimization_figure(
    daily_summary: pd.DataFrame,
    metric_key: str,
    aggregation: str = "daily",
    battery_capacity_kwh: float | None = None,
) -> go.Figure:
    """Build a normalized battery optimization metric chart."""
    metric_specs = {
        key: (label, unit_prefix)
        for key, label, unit_prefix in _NORMALIZED_PLOT_METRICS
    }
    if metric_key not in metric_specs:
        raise ValueError(f"Unsupported normalized battery metric: {metric_key}")

    fig = go.Figure()
    period_summary = (
        aggregate_battery_optimization_intervals(daily_summary, aggregation)
        if "timestamp" in daily_summary.columns
        else aggregate_battery_optimization_summary(daily_summary, aggregation)
    )
    if period_summary.empty:
        fig.update_layout(
            height=420,
            paper_bgcolor="#ffffff",
            plot_bgcolor="#f8fafc",
            annotations=[
                {
                    "text": "Keine Daten zur Anzeige",
                    "x": 0.5,
                    "xref": "paper",
                    "y": 0.5,
                    "yref": "paper",
                    "showarrow": False,
                    "font": {"size": 13, "color": "#94a3b8"},
                }
            ],
        )
        return fig

    if metric_key in period_summary:
        values = period_summary[metric_key].tolist()
    else:
        period_metrics = [
            calculate_normalized_battery_optimization_metrics(
                pd.DataFrame([period[SUMMARY_VALUE_COLUMNS].to_dict()]),
                battery_capacity_kwh=battery_capacity_kwh,
            )
            for _, period in period_summary.iterrows()
        ]
        values = [metrics[metric_key] for metrics in period_metrics]
    title, unit_prefix = metric_specs[metric_key]
    labels = [
        (
            (
                _format_eur_with_decimals(value)
                if metric_key == "value_per_kwh_capacity"
                else (
                    _format_full_eur(value)
                    if unit_prefix
                    else _format_cycle_count(value)
                )
            )
            if value is not None and pd.notna(value)
            else ""
        )
        for value in values
    ]
    colors = [
        "#10b981" if value is not None and value >= 0 else "#ef4444" for value in values
    ]
    hover_value = f"{unit_prefix}%{{y:,.2f}}"
    fig.add_trace(
        go.Bar(
            x=period_summary["period_label"],
            y=values,
            marker={"color": colors, "line": {"color": "#047857", "width": 1}},
            text=labels,
            textposition="outside",
            hovertemplate=(f"<b>%{{x}}</b><br>{title}: {hover_value}<extra></extra>"),
            name=title,
        )
    )
    fig.update_layout(
        height=460,
        margin={"t": 40, "r": 36, "b": 82, "l": 72},
        paper_bgcolor="#ffffff",
        plot_bgcolor="#fbfdff",
        font={
            "family": "Inter, Segoe UI, Arial, sans-serif",
            "size": 12,
            "color": "#374151",
        },
        showlegend=False,
        xaxis_title=AGGREGATION_OPTIONS[aggregation],
        yaxis_title=title,
        hoverlabel={
            "bgcolor": "#1e293b",
            "font_size": 12,
            "font_color": "#f8fafc",
            "bordercolor": "#334155",
        },
        separators=",.",
        uniformtext={"mode": "hide", "minsize": 10},
    )
    fig.update_xaxes(
        gridcolor="#edf2f7",
        linecolor="#cbd5e1",
        tickfont={"size": 11, "color": "#64748b"},
        title_font={"size": 12, "color": "#475569"},
    )
    fig.update_yaxes(
        gridcolor="#e2e8f0",
        linecolor="#cbd5e1",
        tickfont={"size": 11, "color": "#64748b"},
        tickprefix=unit_prefix,
        title_font={"size": 12, "color": "#475569"},
        zeroline=True,
        zerolinecolor="#64748b",
        zerolinewidth=1.5,
    )
    return fig


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
    kpi_boxes = _build_battery_optimization_kpi_boxes(normalized_metrics)
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
        metric_key: label for metric_key, label, _ in _NORMALIZED_PLOT_METRICS
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


def _build_battery_optimization_kpi_boxes(
    metrics: dict[str, float | None],
) -> list[tuple[str, object, object, str | None]]:
    """Build the visible KPI cards for the selected reporting period."""
    return [
        (
            "Netto-Einsparung (€)",
            round(metrics["total_savings"] or 0.0),
            None,
            _KPI_TOOLTIPS["total_savings"],
        ),
        (
            "Wert Entladung (€)",
            metrics["discharging_value_eur"],
            None,
            _KPI_TOOLTIPS["discharging_value_eur"],
        ),
        (
            "Wert Beladung (€)",
            metrics["charging_cost_eur"],
            None,
            _KPI_TOOLTIPS["charging_cost_eur"],
        ),
        (
            "Preis-Spread Batterie (€/MWh)",
            metrics["battery_price_spread_eur_per_mwh"],
            None,
            _KPI_TOOLTIPS["battery_price_spread_eur_per_mwh"],
        ),
        (
            "Batteriezyklen (Vollzyklen)",
            metrics["battery_cycles"],
            None,
            _KPI_TOOLTIPS["battery_cycles"],
        ),
        (
            "Wirkungsgrad (%)",
            metrics["battery_efficiency_pct"],
            None,
            _KPI_TOOLTIPS["battery_efficiency_pct"],
        ),
        (
            "Entladene Menge (kWh)",
            metrics["battery_discharging_kwh"],
            None,
            _KPI_TOOLTIPS["battery_discharging_kwh"],
        ),
        (
            "Geladene Menge (kWh)",
            metrics["battery_charging_kwh"],
            None,
            _KPI_TOOLTIPS["battery_charging_kwh"],
        ),
        # (
        #     "Wert pro kWh Batteriekapazität (€/kWh)",
        #     metrics["value_per_kwh_capacity"],
        #     None,
        #     _KPI_TOOLTIPS["value_per_kwh_capacity"],
        # ),
    ]
