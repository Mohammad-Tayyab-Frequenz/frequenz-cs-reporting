# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Interval calculations for battery optimization reporting."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

BATTERY_POWER_FLOW_COLUMN = "battery_power_flow"
DAY_AHEAD_PRICE_COLUMN = "day_ahead_price"
KWH_PER_MWH = 1000.0
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
    result["battery_cycles"] = (
        result["battery_discharging_kwh"] / result["battery_capacity_kwh"]
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
    timestamps = pd.to_datetime(summary["timestamp"], utc=True)
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
    return {
        "total_savings": _finite(metrics["optimization_savings_eur"]),
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
    value = pd.to_numeric(value, errors="coerce")
    return (
        float(value)
        if pd.notna(value) and float(value) not in (float("inf"), float("-inf"))
        else None
    )
