# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Shared constants for the reporting library."""

from typing import TypedDict

import pandas as pd

# Color mapping for energy components
COLOR_DICT = {
    "PV": "rgba(224,176,38,1)",
    "PV-Erzeugung": "rgba(224,176,38,1)",
    "PV-Erzeugung [kWh]": "rgba(224,176,38,1)",
    "PV-Erzeugung [kWh] Sum": "rgba(224,176,38,1)",
    "Wind": "rgba(62,125,179,1)",
    "Wind-Erzeugung": "rgba(62,125,179,1)",
    "Wind-Erzeugung [kWh] Sum": "rgba(62,125,179,1)",
    "KWK": "rgba(198,113,52,1)",
    "KWK-Erzeugung": "rgba(198,113,52,1)",
    "KWK-Erzeugung [kWh] Sum": "rgba(198,113,52,1)",
    "Netto Gesamtverbrauch": "rgba(71,82,99,1)",
    "MID Gesamtverbrauch": "rgba(71,82,99,1)",
    "Batterie Leistungsfluss": "rgba(41,140,120,1)",
    "Netzbezug": "rgba(32,42,55,1)",
}

# Column name constants (German display names)
COLUMN_NAMES = {
    "TIMESTAMP": "Zeitpunkt",
    "TOTAL_CONSUMPTION": "MID Gesamtverbrauch",
    "GRID_CONSUMPTION": "Netzbezug",
    "GRID_FEED_IN": "Netzeinspeisung",
    "PV_PRODUCTION": "PV-Erzeugung",
    "PV_PRODUCTION_KWH": "PV-Erzeugung [kWh]",
    "BATTERY_ENERGY": "Batterie Energie [kWh]",
    "BATTERY_THROUGHPUT": "Batterie Durchsatz",
    "BATTERY": "Batterie",
    "CHP_PRODUCTION": "KWK-Erzeugung",
    "CHP_PRODUCTION_KWH": "KWK-Erzeugung [kWh]",
    "WIND_PRODUCTION": "Wind-Erzeugung",
    "WIND_PRODUCTION_KWH": "Wind-Erzeugung [kWh]",
    "EV_PRODUCTION_KWH": "EV-Erzeugung [kWh]",
    "ENERGY_SOURCE": "Energiebezug",
    "ENERGY_KWH": "Energie [kWh]",
}

# Component analysis configurations
COMPONENT_CONFIGS = {
    "pv": {
        "label": "PV",
        "value_col": COLUMN_NAMES["PV_PRODUCTION_KWH"],
        "title": "PV Leistung",
    },
    "batt": {
        "label": "Battery",
        "value_col": COLUMN_NAMES["BATTERY_ENERGY"],
        "title": "Batterie Energie [kWh]",
    },
    "chp": {
        "label": "CHP",
        "value_col": COLUMN_NAMES["CHP_PRODUCTION_KWH"],
        "title": "KWK Erzeugung",
    },
    "ev": {
        "label": "EV",
        "value_col": COLUMN_NAMES["EV_PRODUCTION_KWH"],
        "title": "EV Erzeugung",
    },
    "wind": {
        "label": "Wind",
        "value_col": COLUMN_NAMES["WIND_PRODUCTION_KWH"],
        "title": "Wind Erzeugung",
    },
}

# Column rename mapping for compatibility with lib notebooks
COLUMN_RENAME_MAP = {
    "Total Consumption": COLUMN_NAMES["TOTAL_CONSUMPTION"],
    "grid_consumption": COLUMN_NAMES["GRID_CONSUMPTION"],
    "grid_feed_in": COLUMN_NAMES["GRID_FEED_IN"],
    "pv_asset_production": COLUMN_NAMES["PV_PRODUCTION"],
    "chp_asset_production": COLUMN_NAMES["CHP_PRODUCTION"],
    "wind_asset_production": COLUMN_NAMES["WIND_PRODUCTION"],
    "Batterie Durchsatz": COLUMN_NAMES["BATTERY"],
}


class TablesResult(TypedDict):
    """Container for all tabular results produced by the energy system analysis.

    This TypedDict groups together summary tables, technology-specific analyses,
    and key performance metrics returned by the model.
    """

    power_table: pd.DataFrame
    metrics: dict[str, float | str | None]
    pv_analysis: pd.DataFrame
    batt_analysis: pd.DataFrame
    chp_analysis: pd.DataFrame
    wind_analysis: pd.DataFrame
    ev_analysis: pd.DataFrame
    overview_df: pd.DataFrame
