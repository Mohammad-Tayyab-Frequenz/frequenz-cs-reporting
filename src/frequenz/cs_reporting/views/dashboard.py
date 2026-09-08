# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Dashboard view rendering and master dataframe construction."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Iterable

import pandas as pd
import streamlit as st
from frequenz.lib.notebooks.reporting.asset_optimization.data import (
    merge_day_ahead_prices,
)
from frequenz.lib.notebooks.reporting.data_processing import create_energy_report_df
from frequenz.lib.notebooks.reporting.utils.column_mapper import ColumnMapper
from frequenz.lib.notebooks.reporting.utils.reporting_nb_functions import (
    aggregate_metrics,
    build_component_analysis,
    build_overview_df,
    compute_energy_summary,
)

from frequenz.cs_reporting.constants import COMPONENT_CONFIGS, TablesResult
from frequenz.cs_reporting.services.client_factory import get_meter_display_names
from frequenz.cs_reporting.ui_resources import inject_style, render_template
from frequenz.cs_reporting.views import sections

_DAY_AHEAD_PRICE_COLUMN = "day_ahead_price"
_DAY_AHEAD_PRICE_METRIC_KEYS = {
    "grid_import_cost_sum",
    "grid_feed_in_revenue_sum",
    "average_da_price_grid_import",
    "average_da_price_grid_feed_in",
}
_ENTSOE_FETCH_WARNING = (
    "We were not able to fetch the data from ENTSOE, please try again later."
)


def _inject_dashboard_css() -> None:
    """Inject dashboard section styles for the current Streamlit run."""
    inject_style("dashboard.css")


def _section_divider(label: str = "", badge: str = "") -> None:
    """Render a styled section divider with optional label."""
    _inject_dashboard_css()
    badge_html = (
        f'<span class="dash-section-label__count">{badge}</span>' if badge else ""
    )
    if label:
        st.markdown(
            render_template(
                "dashboard_section_divider.html",
                label=label,
                badge_html=badge_html,
            ),
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<hr class="dash-section-divider">',
            unsafe_allow_html=True,
        )


def _numeric_metric(metrics: dict[str, float | str | None], key: str) -> float | None:
    """Return a metric value as a float when it is numeric."""
    value = metrics.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _average_price_ct_per_kwh(
    metrics: dict[str, float | str | None], value_key: str, energy_key: str
) -> float | None:
    """Calculate an average price in ct/kWh from euro and kWh metric values."""
    value = _numeric_metric(metrics, value_key)
    energy = _numeric_metric(metrics, energy_key)
    if value is None or energy is None or energy == 0.0:
        return None
    return (value * 100) / energy


def _has_day_ahead_prices(master_df: pd.DataFrame) -> bool:
    """Return whether the dataframe contains usable day-ahead price data."""
    return (
        _DAY_AHEAD_PRICE_COLUMN in master_df.columns
        and not master_df[_DAY_AHEAD_PRICE_COLUMN].isna().all()
    )


def _aggregate_metrics(
    master_df: pd.DataFrame, resolution: timedelta
) -> dict[str, float | str | None]:
    """Aggregate dashboard metrics, omitting price metrics when prices are missing."""
    has_day_ahead_prices = _has_day_ahead_prices(master_df)
    metrics = aggregate_metrics(
        master_df,
        resolution,
        price_column=_DAY_AHEAD_PRICE_COLUMN if has_day_ahead_prices else None,
    )
    if not has_day_ahead_prices:
        for key in _DAY_AHEAD_PRICE_METRIC_KEYS:
            metrics.pop(key, None)
        return metrics

    metrics["average_da_price_grid_import"] = _average_price_ct_per_kwh(
        metrics, "grid_import_cost_sum", "grid_consumption_sum"
    )
    metrics["average_da_price_grid_feed_in"] = _average_price_ct_per_kwh(
        metrics, "grid_feed_in_revenue_sum", "grid_feed_in_sum"
    )
    return metrics


def _filter_component_types_for_master_df(
    component_types: Iterable[str], master_df: pd.DataFrame
) -> tuple[str, ...]:
    """Keep only component types represented by the master dataframe columns."""
    required_columns = {
        "battery": {"battery_power_flow"},
        "chp": {"chp_asset_production"},
        "pv": {"pv_asset_production"},
        "wind": {"wind_asset_production"},
    }
    columns = set(master_df.columns)

    return tuple(
        component_type
        for component_type in component_types
        if required_columns.get(component_type, set()).issubset(columns)
    )


@st.cache_data(show_spinner="Preparing analysis tables…")
def _build_tables(
    master_df: pd.DataFrame,
    resolution: timedelta,
    component_types: Iterable[str],
) -> TablesResult:
    """Build all analysis tables from master dataframe.

    Creates power summary, aggregated metrics, and component-specific time series
    analyses for all configured components (PV, Battery, CHP, Wind, EV). Uses a
    configuration-driven approach from COMPONENT_CONFIGS for maintainability.

    Args:
        master_df: Master dataframe with timestamp index and component data columns.
            Expected to contain energy/power values for all microgrid components.
        resolution: Time resolution for energy aggregation (e.g., timedelta(minutes=15)).
        component_types: List of component type strings present in the microgrid
            (e.g., ['pv', 'battery', 'chp']).

    Returns:
        Dictionary containing:
            - power_table: Energy summary table by source
            - metrics: Aggregated KPIs and summary metrics
            - pv_analysis: PV component time series analysis
            - batt_analysis: Battery component time series analysis
            - chp_analysis: CHP component time series analysis
            - wind_analysis: Wind component time series analysis
            - ev_analysis: EV component time series analysis
            - overview_df: Overview dataframe for main dashboard display

    Note:
        This function is cached with @st.cache_data for performance. The cache
        is automatically invalidated when any input parameters change.
    """
    component_types = _filter_component_types_for_master_df(component_types, master_df)
    power_table = compute_energy_summary(master_df, resolution)
    metrics = _aggregate_metrics(master_df, resolution)

    # Build component analyses using configuration
    analyses = {
        f"{key}_analysis": build_component_analysis(
            master_df,
            selection_filter=["All"],
            component_label=config["label"],
            value_col_name=config["value_col"],
        )
        for key, config in COMPONENT_CONFIGS.items()
    }

    overview_df = build_overview_df(master_df, component_types)

    return {
        "power_table": power_table,
        "metrics": metrics,
        "pv_analysis": analyses["pv_analysis"],
        "batt_analysis": analyses["batt_analysis"],
        "chp_analysis": analyses["chp_analysis"],
        "wind_analysis": analyses["wind_analysis"],
        "ev_analysis": analyses["ev_analysis"],
        "overview_df": overview_df,
    }


# pylint: disable=too-many-arguments, too-many-positional-arguments
def build_master_df(
    raw_df: pd.DataFrame,
    component_types: Iterable[str],
    mcfg: Any,
    mapper: ColumnMapper,
    timezone: str = "Europe/Berlin",
    battery_soc_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Transform raw microgrid data into master analysis dataframe.

    Processes raw time-series data from the microgrid to create a comprehensive
    master dataframe suitable for analysis and visualization. Applies data cleaning,
    component aggregation, and column mapping.

    Args:
        raw_df: Raw dataframe with microgrid time-series data. Expected columns
            include timestamp, component IDs, and power/energy measurements.
        component_types: List of component type strings to include in analysis
            (e.g., ['pv', 'battery', 'grid']).
        mcfg: Microgrid configuration object containing component metadata and
            site-specific settings.
        mapper: Column name mapper for converting internal names to display names.
        timezone: Timezone name to use for the report timestamps.
        battery_soc_df: Optional battery SOC dataframe to merge into the report.

    Returns:
        Master dataframe with processed and aggregated component data, ready for
        analysis and visualization. Includes derived metrics and standardized
        column names.
    """
    component_types = [col for col in component_types if col in raw_df.columns]

    # Now drop components whose meters sum to zero
    component_types = [
        c
        for c in component_types
        if pd.to_numeric(raw_df[c], errors="coerce").fillna(0).sum() != 0
    ]
    component_display_names = get_meter_display_names(mcfg.meta.microgrid_id)
    master_df = create_energy_report_df(
        raw_df,
        component_types,
        mcfg,
        mapper=mapper,
        tz_name=timezone,
        assume_tz="UTC",
        component_display_names=component_display_names,
        battery_soc_df=battery_soc_df,
    )
    try:
        master_df = merge_day_ahead_prices(
            master_df.set_index("timestamp"),
            dayahead_country_code="DE_LU",
        ).reset_index()
    except Exception:  # pylint: disable=broad-exception-caught
        st.warning(_ENTSOE_FETCH_WARNING)
    else:
        if not _has_day_ahead_prices(master_df):
            st.warning(_ENTSOE_FETCH_WARNING)
    return master_df


def render_dashboard(
    master_df: pd.DataFrame,
    resolution: timedelta,
    component_types: Iterable[str],
    mapper: ColumnMapper,
    microgrid_id: int,
) -> None:
    """Render the complete microgrid reporting dashboard.

    Displays a comprehensive three-section dashboard:
    1. Overview section with summary metric boxes
    2. Interactive plots section with time series and pie charts
    3. Data tables section with detailed component breakdowns

    Args:
        master_df: Master dataframe containing processed microgrid data with all
            component measurements and derived metrics.
        resolution: Time resolution for data aggregation (e.g., timedelta(minutes=15)).
        component_types: List of component types present in the microgrid for
            dynamic tab generation.
        mapper: Column name mapper for display name standardization.
        microgrid_id: Identifier of the selected microgrid.

    Returns:
        Renders Streamlit components directly to the app interface.

    Note:
        This function orchestrates the dashboard layout and delegates rendering
        to specialized section modules (summary_boxes, plots_tabs, data_tabs).
    """
    component_types = _filter_component_types_for_master_df(component_types, master_df)
    tables = _build_tables(master_df, resolution, component_types)

    # --- Overview section---
    _section_divider("Übersicht", "KPIs")
    sections.render_summary_boxes(tables["metrics"], component_types, microgrid_id)

    # --- Plots section---
    _section_divider("Diagramme & Zeitreihen")
    sections.render_plots_tabs(tables, mapper, component_types)

    # --- Tables section---
    st.markdown('<div id="data-export-section"></div>', unsafe_allow_html=True)
    _section_divider("Datentabellen")
    sections.render_data_tabs(master_df, tables, mapper)
