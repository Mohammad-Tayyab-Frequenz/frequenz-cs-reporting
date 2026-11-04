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
