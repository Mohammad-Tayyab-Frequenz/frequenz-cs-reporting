# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Battery optimization savings page."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta

import streamlit as st
from frequenz.lib.notebooks.reporting.utils.column_mapper import ColumnMapper
from frequenz.lib.notebooks.reporting.utils.helpers import (
    normalize_date_for_reporting,
    set_date_to_midnight,
)

from frequenz.cs_reporting.app_pages.reporting import (
    _format_data_loading_error,
    _parse_resolution,
    _prepare_dataframe,
)
from frequenz.cs_reporting.components.sidebar_inputs import collect_sidebar_inputs
from frequenz.cs_reporting.rep_cs_core.page_spec import PageSpec
from frequenz.cs_reporting.services.client_factory import (
    get_component_types,
    get_microgrid_config,
)
from frequenz.cs_reporting.services.data_service import (
    get_battery_capacity_kwh,
    get_microgrid_data,
    get_microgrid_soc_data,
)
from frequenz.cs_reporting.views.battery_optimization import (
    render_battery_optimization,
)
from frequenz.cs_reporting.views.dashboard import build_master_df, split_periods

_SIDEBAR_KEY_PREFIX = "battery_optimization_"


def _previous_month_date(value: date) -> date:
    """Return the same calendar day in the previous month when possible."""
    previous_month = value.month - 1
    year = value.year
    if previous_month == 0:
        previous_month = 12
        year -= 1

    previous_month_days = calendar.monthrange(year, previous_month)[1]
    return date(year, previous_month, min(value.day, previous_month_days))


# pylint: disable=too-many-locals
def render() -> None:
    """Render the battery optimization savings page."""
    st.title("Kostenwirkung der Batterieoptimierung")

    today = datetime.now(tz=UTC).date()
    selections = collect_sidebar_inputs(
        default_start=_previous_month_date(today),
        default_end=today,
        resolution_options=("15min", "30min", "1hour"),
        default_resolution="15min",
        key_prefix=_SIDEBAR_KEY_PREFIX,
    )

    timezone = selections["timezone"]
    microgrid_id = selections["microgrid_id"]
    start_time = set_date_to_midnight(selections["start_date"], timezone)
    end_time = normalize_date_for_reporting(selections["end_date"], timezone)
    end_time = end_time.replace(microsecond=0)
    if end_time.date() != datetime.now(tz=UTC).date():
        end_time += timedelta(days=1)

    if start_time > end_time:
        st.warning(
            "Das Enddatum muss am oder nach dem Startdatum liegen. "
            "Bitte passen Sie Ihre Auswahl an."
        )
        st.stop()

    try:
        resolution = _parse_resolution(selections["resolution"])
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    try:
        with st.spinner("Microgrid-Daten werden geladen..."):
            component_types = list(get_component_types(microgrid_id))
            if "battery" not in component_types:
                st.info("Dieses Microgrid enthält keine Batterie.")
                st.stop()

            battery_capacity_kwh = None
            try:
                battery_capacity_kwh = get_battery_capacity_kwh(
                    microgrid_id,
                    start_time,
                    end_time,
                    resolution,
                )
            except Exception as exc:  # pylint: disable=broad-except
                st.warning(f"Batteriekapazität konnte nicht geladen werden: {exc}")

            mcfg = get_microgrid_config(microgrid_id)
            df = get_microgrid_data(
                microgrid_id=microgrid_id,
                start_date=start_time,
                end_date=end_time,
                resolution=resolution,
            )
            battery_soc_df = None
            battery_formula = mcfg.ctype["battery"].formula
            has_battery_soc_formula = (
                battery_formula is not None and "BATTERY_SOC_PCT" in battery_formula
            )
            if has_battery_soc_formula:
                try:
                    fetched_soc_df = get_microgrid_soc_data(
                        microgrid_id=microgrid_id,
                        start_date=start_time,
                        end_date=end_time,
                        resolution=resolution,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    st.warning(
                        f"Batterie-SOC-Daten konnten nicht geladen werden: {exc}"
                    )
                else:
                    battery_soc_df = None if fetched_soc_df.empty else fetched_soc_df
    except Exception as exc:  # pylint: disable=broad-except
        st.error(_format_data_loading_error(exc, microgrid_id))
        st.stop()

    if df.empty:
        st.warning("Keine Daten für die ausgewählten Filter vorhanden.")
        st.stop()

    mapper = ColumnMapper.from_default()
    master_df = build_master_df(
        _prepare_dataframe(df),
        component_types,
        mcfg,
        mapper,
        timezone=timezone,
        battery_soc_df=battery_soc_df,
    )
    current_master_df, _ = split_periods(master_df, start_time, end_time, resolution)
    if current_master_df.empty:
        st.warning("Keine Daten für die ausgewählten Filter vorhanden.")
        st.stop()

    render_battery_optimization(
        current_master_df,
        resolution,
        battery_capacity_kwh=battery_capacity_kwh,
    )


PAGE = PageSpec(
    key="battery_optimization",
    title="Kostenwirkung der Batterieoptimierung",
    icon="",
    order=3,
    render=render,
)
