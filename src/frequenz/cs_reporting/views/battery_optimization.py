# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Battery optimization savings calculations and rendering."""

from __future__ import annotations

from datetime import timedelta
from math import isfinite

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from frequenz.cs_reporting.components.ui import render_plot_card
from frequenz.cs_reporting.services.battery_optimization_calculations import (
    aggregate_battery_optimization_intervals,
    calculate_battery_optimization_intervals,
    calculate_selection_metrics,
)
from frequenz.cs_reporting.views.metric_renderers import render_box_grid
from frequenz.cs_reporting.views.table_renderers import render_table_section

_BATTERY_POWER_FLOW_COLUMN = "battery_power_flow"
_DAY_AHEAD_PRICE_COLUMN = "day_ahead_price"
_SUMMARY_VALUE_COLUMNS = [
    "battery_charging_kwh",
    "battery_discharging_kwh",
    "charging_cost_eur",
    "discharging_value_eur",
    "optimization_savings_eur",
]
_AGGREGATION_OPTIONS = {
    "daily": "Täglich",
    "weekly": "Wöchentlich",
    "monthly": "Monatlich",
}
_GERMAN_MONTH_ABBREVIATIONS = (
    "Jan",
    "Feb",
    "Mär",
    "Apr",
    "Mai",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Okt",
    "Nov",
    "Dez",
)
_KWH_PER_MWH = 1000.0
_NORMALIZED_PLOT_METRICS = (
    ("value_per_mwh_throughput", "Wert pro MWh Batteriedurchsatz (€/MWh)", "€"),
    ("value_per_mwh_discharged", "Wert pro MWh entladene Energie (€/MWh)", "€"),
    ("battery_price_spread_eur_per_mwh", "Preis-Spread Batterie (€/MWh)", "€"),
    ("value_per_kwh_capacity", "Wert pro kWh Batteriekapazität (€/kWh)", "€"),
    ("battery_cycles", "Batteriezyklen (Vollzyklen)", ""),
)
_KPI_TOOLTIPS = {
    "total_savings": (
        "Entladewert minus Ladekosten. "
        "Berechnung: Summe(entladene kWh * Day-Ahead-Preis / 1000) - "
        "Summe(geladene kWh * Day-Ahead-Preis / 1000)."
    ),
    "value_per_mwh_throughput": (
        "Kostenwirkung je bewegter Batterieenergie. "
        "Berechnung: Kostenwirkung / ((geladene kWh + entladene kWh) / 1000)."
    ),
    "battery_price_spread_eur_per_mwh": (
        "Durchschnittlicher Entladepreis minus durchschnittlicher Ladepreis. "
        "Berechnung: Entladewert / entladene MWh - Ladekosten / geladene MWh."
    ),
    "value_per_mwh_discharged": (
        "Kostenwirkung je abgegebener Batterieenergie. "
        "Berechnung: Kostenwirkung / (entladene kWh / 1000)."
    ),
    "value_per_kwh_capacity": (
        "Kostenwirkung relativ zur installierten Batteriekapazität. "
        "Berechnung: Kostenwirkung / Batteriekapazität (kWh)."
    ),
    "battery_cycles": (
        "Äquivalente Vollzyklen der Batterie. "
        "Berechnung: entladene Energie (kWh) / Batteriekapazität (kWh)."
    ),
}
_RESULTS_TABLE_SOURCE_COLUMNS = (
    "timestamp",
    "grid_consumption",
    "grid_feed_in",
    "mid_consumption",
    "total_production",
    "pv_asset_production",
    "wind_asset_production",
    "chp_asset_production",
    "battery_power_flow",
    "battery_charge",
    "battery_discharge",
    "battery_soc_pct",
    "day_ahead_price",
)
_RESULTS_TABLE_CALCULATION_COLUMNS = {
    "battery_charging_kwh": "Geladene Energie (kWh)",
    "battery_discharging_kwh": "Entladene Energie (kWh)",
    "battery_throughput_kwh": "Batteriedurchsatz (kWh)",
    "day_ahead_price_available": "Day-Ahead-Preis verfügbar",
    "charging_cost_eur": "Ladekosten (€)",
    "discharging_value_eur": "Entladewert (€)",
    "optimization_savings_eur": "Kostenwirkung der Batterieoptimierung (€)",
    "battery_capacity_kwh": "Batteriekapazität (kWh)",
    "battery_cycles": "Batteriezyklen (Vollzyklen)",
}
_RESULTS_TABLE_RENAMES = {
    "timestamp": "Zeitpunkt",
    "grid_consumption": "Netzbezug (kW)",
    "grid_feed_in": "Netzeinspeisung (kW)",
    "mid_consumption": "Gesamtverbrauch (kW)",
    "total_production": "Gesamterzeugung (kW)",
    "pv_asset_production": "PV-Erzeugung (kW)",
    "wind_asset_production": "Wind-Erzeugung (kW)",
    "chp_asset_production": "KWK-Erzeugung (kW)",
    "battery_power_flow": "Batterieleistungsfluss (kW)",
    "battery_charge": "Batterieladung (kW)",
    "battery_discharge": "Batterieentladung (kW)",
    "battery_soc_pct": "Batterie-SOC (%)",
    "day_ahead_price": "Day-Ahead-Preis (€/MWh)",
    **_RESULTS_TABLE_CALCULATION_COLUMNS,
}


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


def calculate_battery_optimization_summary(
    master_df: pd.DataFrame,
    resolution: timedelta,
) -> tuple[float, pd.DataFrame]:
    """Calculate total and daily battery optimization savings.

    The input power column follows PSC convention: positive battery power charges
    the battery, negative battery power discharges it. Day-ahead prices are
    expected in EUR/MWh, so interval kWh values are divided by 1000 for EUR.

    Args:
        master_df: Canonical reporting dataframe with battery and price columns.
        resolution: Sampling interval used to convert power (kW) to energy (kWh).

    Returns:
        A tuple with the total optimization savings in EUR and a daily summary
            dataframe.

    Raises:
        ValueError: If required columns are missing or resolution is not positive.
    """
    missing_cols = {
        "timestamp",
        _BATTERY_POWER_FLOW_COLUMN,
        _DAY_AHEAD_PRICE_COLUMN,
    }.difference(master_df.columns)
    if missing_cols:
        raise ValueError(
            "Required columns are missing: " + ", ".join(sorted(missing_cols))
        )

    hours_factor = float(pd.to_timedelta(resolution).total_seconds()) / 3600.0
    if hours_factor <= 0:
        raise ValueError("resolution must be positive")

    df = master_df[
        ["timestamp", _BATTERY_POWER_FLOW_COLUMN, _DAY_AHEAD_PRICE_COLUMN]
    ].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df[_BATTERY_POWER_FLOW_COLUMN] = pd.to_numeric(
        df[_BATTERY_POWER_FLOW_COLUMN], errors="coerce"
    ).fillna(0.0)
    df[_DAY_AHEAD_PRICE_COLUMN] = pd.to_numeric(
        df[_DAY_AHEAD_PRICE_COLUMN], errors="coerce"
    )
    df = df.dropna(subset=["timestamp", _DAY_AHEAD_PRICE_COLUMN])

    df["battery_charging_kwh"] = (
        df[_BATTERY_POWER_FLOW_COLUMN].clip(lower=0.0) * hours_factor
    )
    df["battery_discharging_kwh"] = (
        -df[_BATTERY_POWER_FLOW_COLUMN].clip(upper=0.0) * hours_factor
    )
    df["charging_cost_eur"] = (
        df["battery_charging_kwh"] * df[_DAY_AHEAD_PRICE_COLUMN] / 1000.0
    )
    df["discharging_value_eur"] = (
        df["battery_discharging_kwh"] * df[_DAY_AHEAD_PRICE_COLUMN] / 1000.0
    )
    df["optimization_savings_eur"] = (
        df["discharging_value_eur"] - df["charging_cost_eur"]
    )

    if df.empty:
        return 0.0, pd.DataFrame(
            columns=[
                "date",
                *_SUMMARY_VALUE_COLUMNS,
            ]
        )

    df["date"] = df["timestamp"].dt.date
    daily_summary = (
        df.groupby("date", as_index=False)[_SUMMARY_VALUE_COLUMNS]
        .sum()
        .sort_values("date")
    )

    return float(df["optimization_savings_eur"].sum()), daily_summary


def calculate_normalized_battery_optimization_metrics(
    daily_summary: pd.DataFrame,
    battery_capacity_kwh: float | None = None,
) -> dict[str, float | None]:
    """Calculate normalized battery optimization KPIs from summary values."""
    if daily_summary.empty:
        return {
            "value_per_mwh_throughput": None,
            "value_per_mwh_discharged": None,
            "battery_price_spread_eur_per_mwh": None,
            "value_per_kwh_capacity": None,
            "battery_cycles": None,
        }

    summary = daily_summary.copy()
    for column in _SUMMARY_VALUE_COLUMNS:
        if column not in summary.columns:
            summary[column] = 0.0
        summary[column] = pd.to_numeric(summary[column], errors="coerce").fillna(0.0)

    charging_mwh = float(summary["battery_charging_kwh"].sum()) / _KWH_PER_MWH
    discharging_mwh = float(summary["battery_discharging_kwh"].sum()) / _KWH_PER_MWH
    throughput_mwh = charging_mwh + discharging_mwh
    savings_eur = float(summary["optimization_savings_eur"].sum())
    charging_cost_eur = float(summary["charging_cost_eur"].sum())
    discharging_value_eur = float(summary["discharging_value_eur"].sum())

    value_per_mwh_throughput = savings_eur / throughput_mwh if throughput_mwh else None
    value_per_mwh_discharged = (
        savings_eur / discharging_mwh if discharging_mwh else None
    )
    average_charge_price = charging_cost_eur / charging_mwh if charging_mwh else None
    average_discharge_price = (
        discharging_value_eur / discharging_mwh if discharging_mwh else None
    )
    price_spread = (
        average_discharge_price - average_charge_price
        if average_charge_price is not None and average_discharge_price is not None
        else None
    )
    value_per_kwh_capacity = (
        savings_eur / battery_capacity_kwh
        if battery_capacity_kwh is not None and battery_capacity_kwh > 0
        else None
    )
    battery_cycles = (
        float(summary["battery_discharging_kwh"].sum()) / battery_capacity_kwh
        if battery_capacity_kwh is not None and battery_capacity_kwh > 0
        else None
    )

    return {
        "value_per_mwh_throughput": value_per_mwh_throughput,
        "value_per_mwh_discharged": value_per_mwh_discharged,
        "battery_price_spread_eur_per_mwh": price_spread,
        "value_per_kwh_capacity": value_per_kwh_capacity,
        "battery_cycles": battery_cycles,
    }


def build_battery_optimization_results_table(
    master_df: pd.DataFrame,
    resolution: timedelta,
    battery_capacity_kwh: float | None = None,
) -> pd.DataFrame:
    """Build interval-level battery optimization inputs and calculations for export."""
    result = master_df.copy()
    if "battery_throughput_kwh" in result.columns:
        result_columns = [
            *(column for column in _RESULTS_TABLE_SOURCE_COLUMNS if column in result),
            *tuple(_RESULTS_TABLE_CALCULATION_COLUMNS),
        ]
        table = result.reindex(columns=result_columns).rename(
            columns=_RESULTS_TABLE_RENAMES
        )
        return table.sort_values("Zeitpunkt", ascending=False, kind="stable")
    resolution_hours = pd.to_timedelta(resolution).total_seconds() / 3600.0
    battery_power = pd.to_numeric(
        result.get(
            _BATTERY_POWER_FLOW_COLUMN,
            pd.Series(0.0, index=result.index),
        ),
        errors="coerce",
    ).fillna(0.0)
    day_ahead_price = pd.to_numeric(
        result.get(_DAY_AHEAD_PRICE_COLUMN, float("nan")), errors="coerce"
    )
    result["day_ahead_price_available"] = day_ahead_price.notna()

    production_columns = [
        column
        for column in (
            "pv_asset_production",
            "wind_asset_production",
            "chp_asset_production",
        )
        if column in result.columns
    ]
    if production_columns:
        result["total_production"] = (
            result[production_columns]
            .apply(
                pd.to_numeric,
                errors="coerce",
            )
            .fillna(0.0)
            .sum(axis=1)
        )

    result["battery_charging_kwh"] = battery_power.clip(lower=0.0) * resolution_hours
    result["battery_discharging_kwh"] = (
        -battery_power.clip(upper=0.0) * resolution_hours
    )
    result["battery_throughput_kwh"] = (
        result["battery_charging_kwh"] + result["battery_discharging_kwh"]
    )
    result["charging_cost_eur"] = (
        result["battery_charging_kwh"] * day_ahead_price / _KWH_PER_MWH
    )
    result["discharging_value_eur"] = (
        result["battery_discharging_kwh"] * day_ahead_price / _KWH_PER_MWH
    )
    result["optimization_savings_eur"] = (
        result["discharging_value_eur"] - result["charging_cost_eur"]
    )
    result["battery_capacity_kwh"] = battery_capacity_kwh
    result["battery_cycles"] = (
        result["battery_discharging_kwh"] / battery_capacity_kwh
        if battery_capacity_kwh is not None and battery_capacity_kwh > 0
        else None
    )

    result_columns = [
        *(column for column in _RESULTS_TABLE_SOURCE_COLUMNS if column in result),
        *tuple(_RESULTS_TABLE_CALCULATION_COLUMNS),
    ]
    table = result.reindex(columns=result_columns).rename(
        columns=_RESULTS_TABLE_RENAMES
    )
    return table.sort_values("Zeitpunkt", ascending=False, kind="stable")


def aggregate_battery_optimization_summary(
    daily_summary: pd.DataFrame,
    aggregation: str,
) -> pd.DataFrame:
    """Aggregate daily battery optimization savings by day, week, or month."""
    if aggregation not in _AGGREGATION_OPTIONS:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    if daily_summary.empty:
        return pd.DataFrame(columns=["period", "period_label", *_SUMMARY_VALUE_COLUMNS])

    summary = daily_summary.copy()
    for column in _SUMMARY_VALUE_COLUMNS:
        if column not in summary.columns:
            summary[column] = 0.0

    summary["date"] = pd.to_datetime(summary["date"], errors="coerce")
    summary = summary.dropna(subset=["date"])

    if aggregation == "daily":
        summary["period"] = summary["date"].dt.date
        summary["period_label"] = summary["date"].dt.strftime("%d.%m.%Y")
    elif aggregation == "weekly":
        week_start = summary["date"] - pd.to_timedelta(
            summary["date"].dt.weekday, unit="D"
        )
        summary["period"] = week_start.dt.date
        summary["period_label"] = summary["date"].dt.strftime("KW %V %G")
    else:
        month_start = summary["date"].dt.to_period("M").dt.to_timestamp()
        summary["period"] = month_start.dt.date
        summary["period_label"] = month_start.map(
            lambda value: (
                f"{_GERMAN_MONTH_ABBREVIATIONS[value.month - 1]} {value.year}"
            )
        )

    return (
        summary.groupby(["period", "period_label"], as_index=False)[
            _SUMMARY_VALUE_COLUMNS
        ]
        .sum()
        .sort_values("period")
    )


def build_daily_battery_optimization_figure(
    daily_summary: pd.DataFrame,
    aggregation: str = "daily",
) -> go.Figure:
    """Build a battery optimization savings bar chart."""
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

    positive_values = period_summary["optimization_savings_eur"].where(
        period_summary["optimization_savings_eur"] >= 0
    )
    negative_values = period_summary["optimization_savings_eur"].where(
        period_summary["optimization_savings_eur"] < 0
    )
    positive_labels = positive_values.map(
        lambda value: _format_full_eur(float(value)) if pd.notna(value) else ""
    )
    negative_labels = negative_values.map(
        lambda value: _format_full_eur(float(value)) if pd.notna(value) else ""
    )
    fig.add_trace(
        go.Bar(
            x=period_summary["period_label"],
            y=positive_values,
            marker={
                "color": "#10b981",
                "line": {"color": "#047857", "width": 1},
            },
            text=positive_labels,
            textposition="outside",
            hovertemplate=(
                "<b>%{x}</b><br>" "Einsparung: €%{y:,.0f}" "<extra></extra>"
            ),
            name="Einsparung",
        )
    )
    fig.add_trace(
        go.Bar(
            x=period_summary["period_label"],
            y=negative_values,
            marker={
                "color": "#ef4444",
                "line": {"color": "#b91c1c", "width": 1},
            },
            text=negative_labels,
            textposition="outside",
            hovertemplate=("<b>%{x}</b><br>" "Kosten: €%{y:,.0f}" "<extra></extra>"),
            name="Kosten",
        )
    )
    fig.update_layout(
        barmode="relative",
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
        xaxis_title=_AGGREGATION_OPTIONS[aggregation],
        yaxis_title="Einsparung/Kosten (€)",
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
                pd.DataFrame([period[_SUMMARY_VALUE_COLUMNS].to_dict()]),
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
        xaxis_title=_AGGREGATION_OPTIONS[aggregation],
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
        interval_data = calculate_battery_optimization_intervals(
            master_df, resolution, battery_capacity_data
        )
    except ValueError as exc:
        st.info(str(exc))
        return

    daily_summary = aggregate_battery_optimization_intervals(interval_data, "daily")
    normalized_metrics = calculate_selection_metrics(interval_data)
    total_savings = normalized_metrics["total_savings"] or 0.0
    render_box_grid(
        [
            (
                "Kostenwirkung der Batterieoptimierung (€)",
                round(total_savings),
                None,
                _KPI_TOOLTIPS["total_savings"],
            ),
            (
                "Wert pro MWh Batteriedurchsatz (€/MWh)",
                normalized_metrics["value_per_mwh_throughput"],
                None,
                _KPI_TOOLTIPS["value_per_mwh_throughput"],
            ),
            (
                "Preis-Spread Batterie (€/MWh)",
                normalized_metrics["battery_price_spread_eur_per_mwh"],
                None,
                _KPI_TOOLTIPS["battery_price_spread_eur_per_mwh"],
            ),
            (
                "Wert pro MWh entladene Energie (€/MWh)",
                normalized_metrics["value_per_mwh_discharged"],
                None,
                _KPI_TOOLTIPS["value_per_mwh_discharged"],
            ),
            (
                "Wert pro kWh Batteriekapazität (€/kWh)",
                normalized_metrics["value_per_kwh_capacity"],
                None,
                _KPI_TOOLTIPS["value_per_kwh_capacity"],
            ),
            (
                "Batteriezyklen (Vollzyklen)",
                normalized_metrics["battery_cycles"],
                None,
                _KPI_TOOLTIPS["battery_cycles"],
            ),
        ],
        per_row=3,
        accent="#14b8a6",
    )
    st.divider()
    plot_tabs = st.tabs(
        [
            "Kostenwirkung",
            "Durchsatz",
            "Entladung",
            "Preis-Spread",
            "Kapazität",
            "Zyklen",
        ]
    )
    plot_configs = [
        ("battery_optimization", "Kostenwirkung der Batterieoptimierung", None),
        *[
            (f"battery_optimization_{metric_key}", label, metric_key)
            for metric_key, label, _ in _NORMALIZED_PLOT_METRICS
        ],
    ]
    for tab, (plot_key, title, metric_key) in zip(plot_tabs, plot_configs):
        with tab:
            aggregation_key = f"{plot_key}_aggregation"
            aggregation = str(st.session_state.get(aggregation_key, "daily"))

            def aggregation_selector(key: str = aggregation_key) -> None:
                st.selectbox(
                    "Aggregation",
                    options=tuple(_AGGREGATION_OPTIONS),
                    format_func=lambda value: _AGGREGATION_OPTIONS[str(value)],
                    key=key,
                    label_visibility="collapsed",
                )

            if metric_key is None:
                fig = build_daily_battery_optimization_figure(
                    interval_data,
                    aggregation,
                )
            else:
                fig = build_normalized_battery_optimization_figure(
                    interval_data,
                    metric_key,
                    aggregation,
                    battery_capacity_kwh=battery_capacity_kwh,
                )
            render_plot_card(
                title,
                fig,
                header_control=aggregation_selector,
                key=plot_key,
            )

    st.divider()
    st.subheader("Intervall-Berechnungsdaten")
    render_table_section(
        build_battery_optimization_results_table(
            interval_data,
            resolution,
            battery_capacity_kwh=battery_capacity_kwh,
        ),
        key_prefix="battery_optimization_results",
        caption=(
            "Ausgangsdaten und Berechnungen je Messintervall; die Kennzahlen und "
            "Diagramme werden daraus täglich, wöchentlich oder monatlich aggregiert."
        ),
        empty_info="Keine Berechnungsdaten verfügbar.",
    )
