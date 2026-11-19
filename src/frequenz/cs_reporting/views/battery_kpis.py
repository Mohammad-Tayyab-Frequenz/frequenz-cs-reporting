# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""KPI cards for the battery optimization page."""

from __future__ import annotations

from frequenz.cs_reporting.ui_resources import load_tooltips

_KPI_TOOLTIPS = load_tooltips("battery_optimization")


def build_battery_optimization_kpi_boxes(
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
