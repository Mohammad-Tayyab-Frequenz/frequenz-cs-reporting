# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Plotly figures for the battery optimization page."""

from __future__ import annotations

from math import isfinite

import pandas as pd
import plotly.graph_objects as go

from frequenz.cs_reporting.services.battery_optimization_calculations import (
    AGGREGATION_OPTIONS,
    SUMMARY_VALUE_COLUMNS,
    aggregate_battery_optimization_intervals,
    aggregate_battery_optimization_summary,
    calculate_normalized_battery_optimization_metrics,
    with_plot_value_column_aliases,
)

NORMALIZED_PLOT_METRICS = (
    ("value_per_mwh_throughput", "Wert pro MWh Batteriedurchsatz (€/MWh)", "€"),
    ("value_per_mwh_discharged", "Wert pro MWh entladene Energie (€/MWh)", "€"),
    ("battery_price_spread_eur_per_mwh", "Preis-Spread Batterie (€/MWh)", "€"),
    ("value_per_kwh_capacity", "Wert pro kWh Batteriekapazität (€/kWh)", "€"),
    ("battery_cycles", "Batteriezyklen (Vollzyklen)", ""),
)
_HIDDEN_NORMALIZED_METRICS = frozenset(
    {"value_per_mwh_throughput", "value_per_mwh_discharged"}
)


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
        key: (label, unit_prefix) for key, label, unit_prefix in NORMALIZED_PLOT_METRICS
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
