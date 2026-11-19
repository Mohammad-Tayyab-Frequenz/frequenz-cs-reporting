# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Interval calculations for battery optimization reporting."""

from __future__ import annotations

from datetime import timedelta
from math import isfinite
from numbers import Real

import pandas as pd

BATTERY_POWER_FLOW_COLUMN = "battery_power_flow"
DAY_AHEAD_PRICE_COLUMN = "day_ahead_price"
KWH_PER_MWH = 1000.0
_BATTERY_POWER_FLOW_COLUMN = "battery_power_flow"
_DAY_AHEAD_PRICE_COLUMN = "day_ahead_price"
SUMMARY_VALUE_COLUMNS = [
    "battery_charging_kwh",
    "battery_discharging_kwh",
    "charging_cost_eur",
    "discharging_value_eur",
    "optimization_savings_eur",
]
_PLOT_VALUE_COLUMN_ALIASES = {
    "charging_value_eur": "discharging_value_eur",
    "discharging_cost_eur": "charging_cost_eur",
}
AGGREGATION_OPTIONS = {
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
CALCULATION_COLUMNS = (
    "battery_charging_kwh",
    "battery_discharging_kwh",
    "battery_throughput_kwh",
    "priced_battery_charging_kwh",
    "priced_battery_discharging_kwh",
    "priced_battery_throughput_kwh",
    "charging_cost_eur",
    "discharging_value_eur",
    "optimization_savings_eur",
    "battery_cycles",
    "value_per_kwh_capacity_interval",
)

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
    "discharging_value_eur": "Entladewert (€)",
    "optimization_savings_eur": "Netto-Einsparung (€)",
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


def build_battery_optimization_results_table(
    master_df: pd.DataFrame,
    resolution: timedelta,
    battery_capacity_kwh: float | None = None,
) -> pd.DataFrame:
    """Build the interval-level data table used by Battery Reporting exports."""
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
        result.get(BATTERY_POWER_FLOW_COLUMN, pd.Series(0.0, index=result.index)),
        errors="coerce",
    ).fillna(0.0)
    day_ahead_price_source = (
        result[DAY_AHEAD_PRICE_COLUMN]
        if DAY_AHEAD_PRICE_COLUMN in result.columns
        else pd.Series(float("nan"), index=result.index, dtype="float64")
    )
    day_ahead_price = pd.to_numeric(day_ahead_price_source, errors="coerce")
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
            .apply(pd.to_numeric, errors="coerce")
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
        result["battery_charging_kwh"] * day_ahead_price / KWH_PER_MWH
    )
    result["discharging_value_eur"] = (
        result["battery_discharging_kwh"] * day_ahead_price / KWH_PER_MWH
    )
    result["optimization_savings_eur"] = (
        result["discharging_value_eur"] - result["charging_cost_eur"]
    )
    result["battery_capacity_kwh"] = battery_capacity_kwh
    result["battery_cycles"] = (
        result["battery_throughput_kwh"] / (2 * battery_capacity_kwh)
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


def calculate_battery_optimization_intervals(
    master_df: pd.DataFrame,
    resolution: timedelta,
    battery_capacity_data: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Calculate physical and price-dependent values for every data interval."""
    required = {"timestamp", BATTERY_POWER_FLOW_COLUMN, DAY_AHEAD_PRICE_COLUMN}
    missing = required.difference(master_df.columns)
    if missing:
        raise ValueError("Required columns are missing: " + ", ".join(sorted(missing)))

    hours = pd.to_timedelta(resolution).total_seconds() / 3600.0
    if hours <= 0:
        raise ValueError("resolution must be positive")

    result = master_df.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], errors="coerce", utc=True)
    result = result.dropna(subset=["timestamp"]).sort_values("timestamp")
    power = pd.to_numeric(result[BATTERY_POWER_FLOW_COLUMN], errors="coerce").fillna(
        0.0
    )
    price = pd.to_numeric(result[DAY_AHEAD_PRICE_COLUMN], errors="coerce")

    result["battery_charging_kwh"] = power.clip(lower=0.0) * hours
    result["battery_discharging_kwh"] = -power.clip(upper=0.0) * hours
    result["battery_throughput_kwh"] = (
        result["battery_charging_kwh"] + result["battery_discharging_kwh"]
    )
    result["day_ahead_price_available"] = price.notna()
    for column in (
        "battery_charging_kwh",
        "battery_discharging_kwh",
        "battery_throughput_kwh",
    ):
        result[f"priced_{column}"] = result[column].where(price.notna())
    result["charging_cost_eur"] = (
        result["priced_battery_charging_kwh"] * price / KWH_PER_MWH
    )
    result["discharging_value_eur"] = (
        result["priced_battery_discharging_kwh"] * price / KWH_PER_MWH
    )
    result["optimization_savings_eur"] = (
        result["discharging_value_eur"] - result["charging_cost_eur"]
    )

    result["battery_capacity_kwh"] = _capacity_for_intervals(
        result[["timestamp"]], battery_capacity_data
    )
    result["battery_cycles"] = result["battery_throughput_kwh"] / (
        2 * result["battery_capacity_kwh"]
    )
    result["value_per_kwh_capacity_interval"] = (
        result["optimization_savings_eur"] / result["battery_capacity_kwh"]
    )
    return result


def _capacity_for_intervals(
    intervals: pd.DataFrame, capacity_data: pd.DataFrame | None
) -> pd.Series:
    """Align the latest known reporting capacity to each data interval."""
    if capacity_data is None or capacity_data.empty:
        return pd.Series(index=intervals.index, dtype="float64")
    capacity = capacity_data[["timestamp", "battery_capacity_kwh"]].copy()
    capacity["timestamp"] = pd.to_datetime(
        capacity["timestamp"], errors="coerce", utc=True
    )
    capacity["battery_capacity_kwh"] = pd.to_numeric(
        capacity["battery_capacity_kwh"], errors="coerce"
    ).where(lambda value: value > 0)
    capacity = capacity.dropna().sort_values("timestamp")
    if capacity.empty:
        return pd.Series(index=intervals.index, dtype="float64")
    sorted_intervals = intervals.sort_values("timestamp")
    aligned = pd.merge_asof(
        sorted_intervals, capacity, on="timestamp", direction="backward"
    )
    # A selected date range can start before its first capacity sample.  Use the
    # nearest sample only for those leading gaps; afterwards retain latest-known
    # capacity so a later capacity change applies from its recorded timestamp.
    if aligned["battery_capacity_kwh"].isna().any():
        nearest = pd.merge_asof(
            sorted_intervals, capacity, on="timestamp", direction="nearest"
        )
        aligned["battery_capacity_kwh"] = aligned["battery_capacity_kwh"].fillna(
            nearest["battery_capacity_kwh"]
        )
    return pd.Series(
        aligned["battery_capacity_kwh"].to_numpy(), index=sorted_intervals.index
    ).reindex(intervals.index)


def aggregate_battery_optimization_intervals(
    intervals: pd.DataFrame, aggregation: str
) -> pd.DataFrame:
    """Aggregate interval calculations into daily, weekly, or monthly periods."""
    if aggregation not in {"daily", "weekly", "monthly"}:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    if intervals.empty:
        return pd.DataFrame()

    summary = intervals.copy()
    summary["timestamp"] = pd.to_datetime(summary["timestamp"], utc=True)
    timestamps = summary["timestamp"]
    if aggregation == "daily":
        summary["period"] = timestamps.dt.date
        summary["period_label"] = timestamps.dt.strftime("%d.%m.%Y")
    elif aggregation == "weekly":
        starts = timestamps - pd.to_timedelta(timestamps.dt.weekday, unit="D")
        summary["period"] = starts.dt.date
        summary["period_label"] = timestamps.dt.strftime("KW %V %G")
    else:
        month_start = timestamps.dt.to_period("M").dt.to_timestamp()
        names = (
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
        summary["period"] = month_start.dt.date
        summary["period_label"] = month_start.map(
            lambda value: f"{names[value.month - 1]} {value.year}"
        )

    totals = summary.groupby(["period", "period_label"], as_index=False)[
        list(CALCULATION_COLUMNS)
    ].sum(min_count=1)
    return _add_normalized_metrics(totals)


def _add_normalized_metrics(summary: pd.DataFrame) -> pd.DataFrame:
    """Add weighted financial metrics and physical-cycle coverage to period totals."""
    result = summary.copy()
    result["value_per_mwh_throughput"] = result["optimization_savings_eur"] / (
        result["priced_battery_throughput_kwh"] / KWH_PER_MWH
    )
    result["value_per_mwh_discharged"] = result["optimization_savings_eur"] / (
        result["priced_battery_discharging_kwh"] / KWH_PER_MWH
    )
    result["battery_price_spread_eur_per_mwh"] = result["discharging_value_eur"] / (
        result["priced_battery_discharging_kwh"] / KWH_PER_MWH
    ) - result["charging_cost_eur"] / (
        result["priced_battery_charging_kwh"] / KWH_PER_MWH
    )
    result["value_per_kwh_capacity"] = result["value_per_kwh_capacity_interval"]
    result["price_coverage_pct"] = (
        result["priced_battery_throughput_kwh"] / result["battery_throughput_kwh"] * 100
    )
    return result.replace([float("inf"), float("-inf")], float("nan"))


def calculate_selection_metrics(intervals: pd.DataFrame) -> dict[str, float | None]:
    """Return KPI metrics for the whole selected range from interval calculations."""
    if intervals.empty:
        return {
            key: None
            for key in (
                "total_savings",
                "charging_cost_eur",
                "discharging_value_eur",
                "battery_charging_kwh",
                "battery_discharging_kwh",
                "battery_efficiency_pct",
                "value_per_mwh_throughput",
                "value_per_mwh_discharged",
                "battery_price_spread_eur_per_mwh",
                "value_per_kwh_capacity",
                "battery_cycles",
                "price_coverage_pct",
            )
        }
    totals = intervals[list(CALCULATION_COLUMNS)].sum(min_count=1).to_frame().T
    metrics = _add_normalized_metrics(totals).iloc[0]
    charging_kwh = _finite(metrics["battery_charging_kwh"])
    discharging_kwh = _finite(metrics["battery_discharging_kwh"])
    # This is only a meaningful round-trip estimate when the energy charged in
    # the selected period covers the energy discharged in that period.  A
    # selected period can start with an already charged battery; counting that
    # pre-period energy in the numerator used to produce impossible values
    # above 100 percent.
    efficiency_pct = (
        discharging_kwh / charging_kwh * 100
        if (
            charging_kwh is not None
            and charging_kwh > 0
            and discharging_kwh is not None
            and discharging_kwh <= charging_kwh
        )
        else None
    )
    return {
        "total_savings": _finite(metrics["optimization_savings_eur"]),
        "charging_cost_eur": _finite(metrics["charging_cost_eur"]),
        "discharging_value_eur": _finite(metrics["discharging_value_eur"]),
        "battery_charging_kwh": charging_kwh,
        "battery_discharging_kwh": discharging_kwh,
        "battery_efficiency_pct": efficiency_pct,
        "value_per_mwh_throughput": _finite(metrics["value_per_mwh_throughput"]),
        "value_per_mwh_discharged": _finite(metrics["value_per_mwh_discharged"]),
        "battery_price_spread_eur_per_mwh": _finite(
            metrics["battery_price_spread_eur_per_mwh"]
        ),
        "value_per_kwh_capacity": _finite(metrics["value_per_kwh_capacity"]),
        "battery_cycles": _finite(metrics["battery_cycles"]),
        "price_coverage_pct": _finite(metrics["price_coverage_pct"]),
    }


def _finite(value: object) -> float | None:
    """Convert finite numeric values to floats."""
    if not isinstance(value, Real):
        return None
    numeric_value = float(value)
    return numeric_value if isfinite(numeric_value) else None


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
                *SUMMARY_VALUE_COLUMNS,
            ]
        )

    df["date"] = df["timestamp"].dt.date
    daily_summary = (
        df.groupby("date", as_index=False)[SUMMARY_VALUE_COLUMNS]
        .sum()
        .sort_values("date")
    )

    return float(df["optimization_savings_eur"].sum()), daily_summary


# pylint: disable=too-many-locals
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
    for column in SUMMARY_VALUE_COLUMNS:
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
        (
            float(summary["battery_charging_kwh"].sum())
            + float(summary["battery_discharging_kwh"].sum())
        )
        / (2 * battery_capacity_kwh)
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


def aggregate_battery_optimization_summary(
    daily_summary: pd.DataFrame,
    aggregation: str,
) -> pd.DataFrame:
    """Aggregate daily battery optimization savings by day, week, or month."""
    if aggregation not in AGGREGATION_OPTIONS:
        raise ValueError(f"Unsupported aggregation: {aggregation}")
    if daily_summary.empty:
        return pd.DataFrame(columns=["period", "period_label", *SUMMARY_VALUE_COLUMNS])

    summary = daily_summary.copy()
    for column in SUMMARY_VALUE_COLUMNS:
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
            SUMMARY_VALUE_COLUMNS
        ]
        .sum()
        .sort_values("period")
    )


def with_plot_value_column_aliases(summary: pd.DataFrame) -> pd.DataFrame:
    """Add plot-value aliases, preferring the latest pipeline column names."""
    result = summary.copy()
    for current_column, legacy_column in _PLOT_VALUE_COLUMN_ALIASES.items():
        if current_column in result.columns:
            result[legacy_column] = result[current_column]
        elif legacy_column in result.columns:
            result[current_column] = result[legacy_column]
    return result
