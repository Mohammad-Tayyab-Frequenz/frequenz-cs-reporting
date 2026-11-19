# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Battery optimization savings page."""

from __future__ import annotations

from concurrent.futures import Future, wait
from datetime import UTC, date, datetime, timedelta
from typing import Any

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
    get_microgrid_names,
)
from frequenz.cs_reporting.services.data_service import (
    get_cached_microgrid_data,
    get_cached_microgrid_soc_data,
    start_background_battery_capacity_data_sync,
    start_background_day_ahead_price_sync,
    start_background_microgrid_data_sync,
    start_background_microgrid_soc_data_sync,
)
from frequenz.cs_reporting.utils.errors import report_error
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


@st.fragment(run_every=0.5)
def _poll_background_syncs(futures: tuple[Future[Any], ...]) -> None:
    """Rerun after all background data synchronizations have finished."""
    if not all(future.done() for future in futures):
        st.info(
            "Daten werden im Hintergrund aktualisiert. Angezeigte Werte sind "
            "bis dahin vorläufig …"
        )
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
    sync_status = st.empty()

    try:
        with log_duration("battery.load_component_types"):
            component_types = list(get_component_types(microgrid_id))
    except Exception as exc:  # pylint: disable=broad-except
        st.error(_format_data_loading_error(exc, microgrid_id))
        st.stop()
    if "battery" not in component_types:
        st.info("Dieses Microgrid enthält keine Batterie.")
        st.stop()

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

    pending_syncs: list[Future[Any]] = []
    price_sync_end = _completed_price_range_end(end_time, timezone, today)
    if start_time < price_sync_end:
        with log_duration("battery.start_price_sync"):
            price_sync = start_background_day_ahead_price_sync(
                "DE_LU", start_time, price_sync_end
            )
        pending_syncs.append(price_sync)

    # Start every API synchronization in the background and render with what the
    # cache already holds; the polling fragment reruns once they have finished.
    sync_args = (microgrid_id, start_time, end_time, resolution)
    power_sync = start_background_microgrid_data_sync(*sync_args)
    soc_sync = start_background_microgrid_soc_data_sync(*sync_args)
    capacity_sync = start_background_battery_capacity_data_sync(*sync_args)
    pending_syncs.extend([power_sync, soc_sync, capacity_sync])
    # Fully cached ranges finish within milliseconds; avoid a needless rerun.
    wait(pending_syncs, timeout=1.0)

    if price_sync_end > start_time and price_sync.done():
        try:
            price_sync.result()
        except Exception as exc:  # pylint: disable=broad-except
            if type(exc).__name__ == "NoMatchingDataError":
                st.warning(
                    "Für einen Teil des Zeitraums sind keine neuen "
                    "Day-Ahead-Preise verfügbar. Vorhandene Cache-Daten "
                    "werden verwendet."
                )
            else:
                st.error(
                    "Day-Ahead-Preise konnten nicht geladen werden. "
                    f"{report_error(exc, 'Day-ahead price load failed')}"
                )
                st.stop()

    still_pending = tuple(future for future in pending_syncs if not future.done())

    try:
        with log_duration("battery.load_microgrid_config"):
            mcfg = get_microgrid_config(microgrid_id)
        df, _ = get_cached_microgrid_data(*sync_args)
        power_error = power_sync.exception() if power_sync.done() else None
        if power_error is not None:
            if df.empty:
                raise power_error
            st.warning(
                "Leistungsdaten konnten nicht aktualisiert werden: "
                f"{report_error(power_error, 'Active power sync failed')}"
            )
        battery_soc_df = None
        try:
            fetched_soc_df = get_cached_microgrid_soc_data(*sync_args)
            if soc_sync.done() and soc_sync.exception() is not None:
                raise soc_sync.exception()  # type: ignore[misc]
        except Exception as exc:  # pylint: disable=broad-except
            st.warning(
                "Batterie-SOC-Daten konnten nicht geladen werden: "
                f"{report_error(exc, 'Battery SOC load failed')}"
            )
        else:
            battery_soc_df = None if fetched_soc_df.empty else fetched_soc_df
        battery_capacity_data = None
        if capacity_sync.done():
            try:
                battery_capacity_data = capacity_sync.result()
            except Exception as exc:  # pylint: disable=broad-except
                st.warning(
                    "Batteriekapazität konnte nicht geladen werden: "
                    f"{report_error(exc, 'Battery capacity load failed')}"
                )
    except Exception as exc:  # pylint: disable=broad-except
        st.error(_format_data_loading_error(exc, microgrid_id))
        st.stop()

    if still_pending:
        with sync_status.container():
            _poll_background_syncs(still_pending)

    if df.empty:
        if not still_pending:
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
