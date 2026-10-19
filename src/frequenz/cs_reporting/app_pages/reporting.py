# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Dashboard page to explore microgrid data and visualizations."""

from __future__ import annotations

import re
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st
from frequenz.lib.notebooks.reporting.utils.column_mapper import ColumnMapper
from frequenz.lib.notebooks.reporting.utils.helpers import (
    normalize_date_for_reporting,
    set_date_to_midnight,
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
    get_dataset_sync_metadata,
    get_microgrid_data,
    get_microgrid_soc_data,
    start_background_microgrid_data_sync,
)
from frequenz.cs_reporting.services.reporting_session import (
    ReportingDataKey,
    ReportingDataSnapshot,
    store_reporting_data_snapshot,
    take_reporting_data_snapshot,
)
from frequenz.cs_reporting.utils.timing import log_duration
from frequenz.cs_reporting.views.dashboard import (
    build_master_df,
    render_dashboard,
    split_periods,
)


def _scroll_to_section_if_requested() -> None:
    """Scroll to a dashboard section when requested via query params."""
    if st.query_params.get("section") != "data-export":
        return

    st.html(
        """
        <script>
        const target = document.getElementById("data-export-section");
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        </script>
        """,
        unsafe_allow_javascript=True,
    )


@st.fragment(run_every=2.0)
def _poll_active_power_sync(
    future: Future[pd.DataFrame],
) -> None:
    """Rerun the page when its already-started active-power refresh finishes."""
    if not future.done():
        st.info("Microgrid-Daten werden aktualisiert …")
        return

    try:
        future.result()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        st.warning(f"Microgrid-Daten konnten nicht aktualisiert werden: {exc}")
        return
    st.rerun()


def _parse_resolution(resolution_str: str) -> timedelta:
    """Convert a resolution string to a ``timedelta``.

    Args:
        resolution_str: Resolution such as ``"15min"`` or ``"1hour"`` with
            optional spaces before the unit.

    Returns:
        Duration represented by the resolution string.

    Raises:
        ValueError: If the resolution format is unsupported.
    """
    match = re.fullmatch(r"(\d+)\s*(min|hour|h)", resolution_str.strip().lower())
    if not match:
        raise ValueError(f"Nicht unterstütztes Auflösungsformat: {resolution_str}")

    value, unit = match.groups()
    minutes = int(value) * (60 if unit in ("hour", "h") else 1)
    return timedelta(minutes=minutes)


def _prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize dataframe indexes for downstream processing.

    Args:
        df: Raw dataframe that may carry a ``DatetimeIndex``.

    Returns:
        Dataframe with a regular index and ``timestamp`` column if
            a ``DatetimeIndex`` was present; otherwise returns the original
            dataframe.
    """
    if isinstance(df.index, pd.DatetimeIndex):
        return df.reset_index().rename(columns={"index": "timestamp"})
    return df


def _format_data_loading_error(exc: Exception, microgrid_id: int) -> str:
    """Return a user-facing error message for a data loading failure."""
    detail = str(exc).strip()
    detail_suffix = f"\n\nDetails: {detail}" if detail else ""

    if isinstance(exc, TimeoutError):
        return (
            "Zeitüberschreitung beim Laden der Microgrid-Daten. "
            "Bitte wählen Sie einen anderen Zeitraum oder versuchen Sie es erneut."
            f"{detail_suffix}"
        )

    if isinstance(exc, KeyError):
        return (
            f"Microgrid {microgrid_id} wurde in den geladenen Konfigurationen "
            f"nicht gefunden.{detail_suffix}"
        )

    if isinstance(exc, ValueError):
        return (
            "Die ausgewählten Filterparameter sind ungültig. "
            "Bitte prüfen Sie Zeitraum, Zeitzone und Auflösung."
            f"{detail_suffix}"
        )

    if isinstance(exc, RuntimeError):
        if "environment variable" in detail:
            return (
                "Eine benötigte Umgebungsvariable fehlt. "
                "Bitte prüfen Sie die API- und Service-Konfiguration."
                f"{detail_suffix}"
            )
        if "config directory" in detail or "config files" in detail:
            return (
                "Microgrid-Konfigurationen konnten nicht geladen werden. "
                "Bitte prüfen Sie das konfigurierte TOML-Verzeichnis."
                f"{detail_suffix}"
            )
        if "active event loop" in detail:
            return (
                "Interner Laufzeitfehler beim Laden der Daten. "
                "Der Datenabruf wurde aus einem ungültigen Kontext gestartet."
                f"{detail_suffix}"
            )
        return (
            "Microgrid-Daten konnten wegen eines Laufzeitfehlers nicht geladen werden."
            f"{detail_suffix}"
        )

    if isinstance(exc, OSError):
        return (
            "Die Reporting-API konnte nicht erreicht werden. "
            "Bitte prüfen Sie Netzwerkverbindung, API-URL und Zugangsdaten."
            f"{detail_suffix}"
        )

    return (
        "Beim Laden der Microgrid-Daten ist ein unerwarteter Fehler aufgetreten."
        f"{detail_suffix}"
    )


# pylint: disable=too-many-branches, too-many-locals, too-many-statements
def render() -> None:
    """Render the Frequenz Reporting Dashboard page.

    Collects sidebar inputs, fetches microgrid data, prepares it for analysis,
    and renders the dashboard views.

    Returns:
        Streamlit components are rendered directly.
    """
    today = datetime.now(tz=UTC).date()
    with log_duration("reporting.sidebar_inputs"):
        selections = collect_sidebar_inputs(
            default_start=today,
            default_end=today,
            resolution_options=("15min", "30min", "1hour"),
            default_resolution="15min",
            key_prefix="reporting_",
        )

    timezone = selections["timezone"]
    microgrid_id = selections["microgrid_id"]

    # set_date_to_midnight returns TZ-aware datetimes aligned with the user's timezone
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

    selected_period = end_time - start_time
    previous_start_time = start_time - selected_period

    try:
        resolution = _parse_resolution(selections["resolution"])
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    data_key = ReportingDataKey(
        microgrid_id=microgrid_id,
        start_iso=selections["start_date"].isoformat(),
        end_iso=selections["end_date"].isoformat(),
        timezone=timezone,
        resolution_seconds=int(resolution.total_seconds()),
    )

    # We extend the fetch end date by 1 day to ensure the API returns data
    # for the full duration of the selected end_time.

    active_power_sync: Future[pd.DataFrame] | None = None
    try:
        with st.spinner("Microgrid-Daten werden geladen..."):
            with log_duration("reporting.load_component_types"):
                component_types = list(get_component_types(microgrid_id))
            with log_duration("reporting.load_microgrid_config"):
                mcfg = get_microgrid_config(microgrid_id)
            with log_duration("reporting.load_microgrid_names"):
                microgrid_name = get_microgrid_names().get(microgrid_id) or mcfg.name
            heading = f"MID{microgrid_id}"
            if microgrid_name:
                heading = f"{heading} - {microgrid_name}"
            st.title(heading)
            snapshot = take_reporting_data_snapshot(data_key)
            if snapshot is not None:
                df = snapshot.active_power.copy()
                sync_metadata = snapshot.sync_metadata
                battery_soc_df = (
                    None
                    if snapshot.battery_soc is None
                    else snapshot.battery_soc.copy()
                )
            else:
                with log_duration("reporting.load_active_power"):
                    df, sync_metadata = get_cached_microgrid_data(
                        microgrid_id=microgrid_id,
                        start_date=previous_start_time,
                        end_date=end_time,
                        resolution=resolution,
                    )
                    if df.empty:
                        with log_duration("reporting.initial_active_power_sync"):
                            df = get_microgrid_data(
                                microgrid_id=microgrid_id,
                                start_date=previous_start_time,
                                end_date=end_time,
                                resolution=resolution,
                            )
                        sync_metadata = get_dataset_sync_metadata(
                            "active_power", microgrid_id, resolution
                        )
                    else:
                        active_power_sync = start_background_microgrid_data_sync(
                            microgrid_id=microgrid_id,
                            start_date=previous_start_time,
                            end_date=end_time,
                            resolution=resolution,
                        )
                battery_soc_df = None
            if sync_metadata.status == "error":
                last_sync = sync_metadata.last_successful_sync or "unbekannt"
                st.warning(
                    "Die Aktualisierung ist fehlgeschlagen; angezeigt werden die "
                    f"zuletzt erfolgreich gespeicherten Daten ({last_sync})."
                )
            battery_formula = (
                mcfg.ctype["battery"].formula if "battery" in component_types else None
            )
            has_battery_soc_formula = (
                battery_formula is not None and "BATTERY_SOC_PCT" in battery_formula
            )
            if snapshot is None and has_battery_soc_formula:
                try:
                    with log_duration("reporting.load_battery_soc"):
                        fetched_soc_df = get_microgrid_soc_data(
                            microgrid_id=microgrid_id,
                            start_date=previous_start_time,
                            end_date=end_time,
                            resolution=resolution,
                        )
                except Exception as exc:  # pylint: disable=broad-except
                    st.warning(
                        f"Batterie-SOC-Daten konnten nicht geladen werden: {exc}"
                    )
                else:
                    battery_soc_df = None if fetched_soc_df.empty else fetched_soc_df
            if snapshot is None:
                store_reporting_data_snapshot(
                    ReportingDataSnapshot(
                        key=data_key,
                        active_power=df.copy(),
                        battery_soc=(
                            None if battery_soc_df is None else battery_soc_df.copy()
                        ),
                        sync_metadata=sync_metadata,
                    )
                )
    except Exception as exc:  # pylint: disable=broad-except
        st.error(_format_data_loading_error(exc, microgrid_id))
        st.stop()

    if df.empty:
        st.warning("Keine Daten für die ausgewählten Filter vorhanden.")
        st.stop()

    with log_duration("reporting.prepare_dataframe"):
        df_prepared = _prepare_dataframe(df)

    with log_duration("reporting.create_column_mapper"):
        mapper = ColumnMapper.from_default()
    with log_duration("reporting.build_master_dataframe"):
        master_df = build_master_df(
            df_prepared,
            component_types,
            mcfg,
            mapper,
            timezone=timezone,
            battery_soc_df=battery_soc_df,
        )
    with log_duration("reporting.split_periods"):
        current_master_df, previous_master_df = split_periods(
            master_df,
            start_time,
            end_time,
            resolution,
        )
    if current_master_df.empty:
        if active_power_sync is not None and not active_power_sync.done():
            _poll_active_power_sync(active_power_sync)
            st.stop()
        st.warning("Keine Daten für die ausgewählten Filter vorhanden.")
        st.stop()

    with log_duration("reporting.render_dashboard"):
        render_dashboard(
            current_master_df,
            resolution=resolution,
            component_types=component_types,
            mapper=mapper,
            microgrid_id=microgrid_id,
            mcfg=mcfg,
            previous_master_df=previous_master_df,
        )
    _scroll_to_section_if_requested()


PAGE = PageSpec(
    key="reporting_dashboard",
    title="Reporting",
    icon="",
    order=1,
    render=render,
)
