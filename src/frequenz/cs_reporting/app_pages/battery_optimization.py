# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Battery optimization savings page."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta

import pandas as pd
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
    _submit_with_script_context,
)
from frequenz.cs_reporting.components.sidebar_inputs import collect_sidebar_inputs
from frequenz.cs_reporting.rep_cs_core.page_spec import PageSpec
from frequenz.cs_reporting.services.client_factory import (
    get_component_types,
    get_microgrid_config,
    get_microgrid_names,
)
from frequenz.cs_reporting.services.data_service import (
    get_battery_capacity_data_kwh,
    get_microgrid_data,
    get_microgrid_soc_data,
    start_background_day_ahead_price_sync,
)
from frequenz.cs_reporting.utils.timing import log_duration
from frequenz.cs_reporting.views.battery_optimization import render_battery_optimization
from frequenz.cs_reporting.views.dashboard import build_master_df, split_periods


def _mid_caption(microgrid_id: int, microgrid_name: str | None) -> str:
    """Return the MID identification displayed as the page title."""
    name = microgrid_name or "Nicht verfügbar"
    return f"MID{microgrid_id} - {name}"


def _completed_price_range_end(
    selected_end: datetime, timezone: str, today: date
) -> datetime:
    """Return a price-sync end that excludes the current incomplete local day."""
    return min(selected_end, set_date_to_midnight(today, timezone))


_CAPACITY_CACHE_TTL_SECONDS = 60 * 60


@st.cache_data(ttl=_CAPACITY_CACHE_TTL_SECONDS, show_spinner=False)
def _cached_battery_capacity(
    microgrid_id: int,
    start_time: datetime,
    end_time: datetime,
    resolution: timedelta,
) -> pd.DataFrame:
    """Load battery capacity once per range; it rarely changes within an hour."""
    return get_battery_capacity_data_kwh(microgrid_id, start_time, end_time, resolution)


def _load_battery_capacity(
    microgrid_id: int, start_time: datetime, end_time: datetime, resolution: timedelta
) -> pd.DataFrame:
    """Load capacity through a short-lived cache, timing the whole load."""
    # For a range ending "now" the raw end changes on every rerun and would
    # never hit the cache.  Capacity is aligned backward onto the intervals, so
    # an end floored to the hour loses nothing.
    cache_end = end_time.replace(minute=0, second=0, microsecond=0)
    if cache_end <= start_time:
        cache_end = end_time
    with log_duration("battery.load_capacity"):
        return _cached_battery_capacity(microgrid_id, start_time, cache_end, resolution)


def _load_battery_soc(
    microgrid_id: int, start_time: datetime, end_time: datetime, resolution: timedelta
) -> pd.DataFrame:
    """Load battery SOC data, timing the whole load."""
    with log_duration("battery.load_soc"):
        return get_microgrid_soc_data(
            microgrid_id=microgrid_id,
            start_date=start_time,
            end_date=end_time,
            resolution=resolution,
        )


@st.fragment(run_every=2.0)
def _poll_day_ahead_price_sync(future: Future[pd.Series]) -> None:
    """Rerun after the selected day-ahead price range finishes loading."""
    if not future.done():
        st.info("Day-Ahead-Preise werden für den gewählten Zeitraum geladen …")
        return
    st.rerun()


# pylint: disable=too-many-branches,too-many-locals,too-many-statements
def render() -> None:
    """Render the battery optimization savings page."""
    today = datetime.now(tz=UTC).date()
    with log_duration("battery.sidebar_inputs"):
        selections = collect_sidebar_inputs(
            resolution_options=("15min", "30min", "1hour"),
            default_resolution="15min",
        )

    timezone = selections["timezone"]
    microgrid_id = selections["microgrid_id"]
    with log_duration("battery.load_microgrid_names"):
        microgrid_names = get_microgrid_names()
    st.title(_mid_caption(microgrid_id, microgrid_names.get(microgrid_id)))

    # Clear the previous filter result before any asynchronous synchronization or
    # data loading can stop this run.  Otherwise Streamlit can keep the old report
    # body visible while the newly selected range is still loading, which makes
    # the KPI cards appear to contain current data when they are actually stale.
    report_content = st.empty()
    report_content.empty()

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

    # Start the price synchronization first but do not wait for it here: the
    # data below loads while it runs, and it is only awaited before the
    # calculation that needs the prices.
    price_sync_end = _completed_price_range_end(end_time, timezone, today)
    price_sync: Future[pd.Series] | None = None
    if start_time < price_sync_end:
        with log_duration("battery.start_price_sync"):
            price_sync = start_background_day_ahead_price_sync(
                "DE_LU", start_time, price_sync_end
            )

    try:
        with st.spinner("Microgrid-Daten werden geladen..."):
            with log_duration("battery.load_component_types"):
                component_types = list(get_component_types(microgrid_id))
            if "battery" not in component_types:
                st.info("Dieses Microgrid enthält keine Batterie.")
                st.stop()

            # Capacity and SOC are independent of active power, so load them
            # concurrently while the (usually slowest) active-power load runs.
            executor = ThreadPoolExecutor(max_workers=2)
            capacity_future = _submit_with_script_context(
                executor,
                _load_battery_capacity,
                microgrid_id,
                start_time,
                end_time,
                resolution,
            )
            soc_future = _submit_with_script_context(
                executor,
                _load_battery_soc,
                microgrid_id,
                start_time,
                end_time,
                resolution,
            )
            executor.shutdown(wait=False)

            with log_duration("battery.load_microgrid_config"):
                mcfg = get_microgrid_config(microgrid_id)
            with log_duration("battery.load_active_power"):
                df = get_microgrid_data(
                    microgrid_id=microgrid_id,
                    start_date=start_time,
                    end_date=end_time,
                    resolution=resolution,
                )

            with log_duration("battery.wait_capacity"):
                battery_capacity_data = None
                try:
                    battery_capacity_data = capacity_future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    st.warning(f"Batteriekapazität konnte nicht geladen werden: {exc}")
            with log_duration("battery.wait_soc"):
                battery_soc_df = None
                try:
                    fetched_soc_df = soc_future.result()
                except Exception as exc:  # pylint: disable=broad-except
                    st.warning(
                        f"Batterie-SOC-Daten konnten nicht geladen werden: {exc}"
                    )
                else:
                    battery_soc_df = None if fetched_soc_df.empty else fetched_soc_df
    except Exception as exc:  # pylint: disable=broad-except
        st.error(_format_data_loading_error(exc, microgrid_id))
        st.stop()

    if price_sync is not None:
        if not price_sync.done():
            _poll_day_ahead_price_sync(price_sync)
            st.stop()
        try:
            price_sync.result()
        except Exception as exc:  # pylint: disable=broad-except
            if type(exc).__name__ == "NoMatchingDataError":
                st.warning(
                    "Für einen Teil des Zeitraums sind keine neuen "
                    "Day-Ahead-Preise verfügbar. Vorhandene Cache-Daten werden "
                    "verwendet."
                )
            else:
                st.error(
                    "Day-Ahead-Preise konnten nicht geladen werden. "
                    f"Details: {type(exc).__name__}: {exc}"
                )
                st.stop()

    if df.empty:
        st.warning("Keine Daten für die ausgewählten Filter vorhanden.")
        st.stop()

    with log_duration("battery.prepare_dataframe"):
        prepared_df = _prepare_dataframe(df)
    with log_duration("battery.create_column_mapper"):
        mapper = ColumnMapper.from_default()
    with log_duration("battery.build_master_dataframe"):
        master_df = build_master_df(
            prepared_df,
            component_types,
            mcfg,
            mapper,
            timezone=timezone,
            battery_soc_df=battery_soc_df,
        )
    with log_duration("battery.split_periods"):
        current_master_df, _ = split_periods(
            master_df, start_time, end_time, resolution
        )
    if current_master_df.empty:
        st.warning("Keine Daten für die ausgewählten Filter vorhanden.")
        st.stop()

    with log_duration("battery.render_report"), report_content.container():
        render_battery_optimization(
            current_master_df,
            resolution,
            battery_capacity_data=battery_capacity_data,
        )


PAGE = PageSpec(
    key="battery_optimization",
    title="Batterie Reporting",
    icon="",
    order=2,
    render=render,
)
