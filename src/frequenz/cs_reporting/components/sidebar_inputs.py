# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Sidebar filter rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Sequence

import streamlit as st

from frequenz.cs_reporting.components import inputs
from frequenz.cs_reporting.services.client_factory import (
    get_microgrid_ids,
    get_microgrid_names,
)

TIMEZONE_OPTIONS = (
    "Europe/Berlin",
    "Europe/Vienna",
    "Europe/Zurich",
    "Europe/Amsterdam",
    "Europe/Brussels",
    "Europe/Copenhagen",
    "UTC",
)

_REPORTING_FILTER_KEY_PREFIX = "reporting_"
_REPORTING_FORM_KEY = f"{_REPORTING_FILTER_KEY_PREFIX}filters_form"
_REPORTING_STATE_KEY = f"{_REPORTING_FILTER_KEY_PREFIX}applied_filters"


# pylint: disable=too-many-locals, too-many-arguments
def collect_sidebar_inputs(
    *,
    resolution_options: Sequence[str] = ("15min", "30min", "1hour", "4hour"),
    default_resolution: str = "15min",
    timezone_options: Sequence[str] = TIMEZONE_OPTIONS,
    default_timezone: str = "Europe/Berlin",
) -> dict[str, Any]:
    """Render the sidebar filters.

    Creates an organized sidebar with sections for microgrid selection, date
    range, and resolution.

    Args:
        resolution_options: Allowed resolution values for selection.
        default_resolution: Default resolution shown initially.
        timezone_options: Allowed timezone values for selection.
        default_timezone: Default timezone shown initially.

    Returns:
        Dictionary containing ``microgrid_id``, ``start_date``,
            ``end_date``, ``timezone``, and ``resolution`` selected by the user.
    """
    st.sidebar.header("Filter Einstellungen")
    st.sidebar.caption("Wählen Sie die Parameter für die Analyse.")

    microgrid_names = get_microgrid_names()
    available_microgrids = sorted(microgrid_names)
    _restore_reporting_widget_state()
    _reconcile_microgrid_selection(
        available_microgrids,
        _REPORTING_FILTER_KEY_PREFIX,
        _REPORTING_STATE_KEY,
    )

    with st.sidebar.form(_REPORTING_FORM_KEY):
        st.subheader("Microgrid")
        microgrid_id = inputs.microgrid_selector(
            label="Microgrid auswählen",
            ids=available_microgrids,
            format_func=lambda microgrid_id: _microgrid_option_label(
                microgrid_id, microgrid_names
            ),
            key_prefix=_REPORTING_FILTER_KEY_PREFIX,
            container=st,
        )

        st.divider()

        st.subheader("Zeitraum")

        default_start, default_end = _default_reporting_date_range()
        today = default_end

        start_key = f"{_REPORTING_FILTER_KEY_PREFIX}start_date"
        end_key = f"{_REPORTING_FILTER_KEY_PREFIX}end_date"
        timezone_key = f"{_REPORTING_FILTER_KEY_PREFIX}timezone"

        start_initial = st.session_state.get(start_key, default_start)

        columns = st.columns(2)
        with columns[0]:
            start_date = st.date_input(
                "Von",
                value=start_initial,
                max_value=today,
                key=start_key,
            )

        end_initial = min(
            st.session_state.get(end_key, default_end),
            today,
        )

        with columns[1]:
            end_date = st.date_input(
                "Ende",
                value=end_initial,
                max_value=today,
                key=end_key,
            )

        timezone_options_list = list(timezone_options)
        timezone_index = next(
            (
                idx
                for idx, option in enumerate(timezone_options_list)
                if option == default_timezone
            ),
            0,
        )

        timezone = st.selectbox(
            "Zeitzone",
            options=timezone_options_list,
            index=timezone_index,
            key=timezone_key,
            help="Zeitzone zur Interpretation der ausgewählten Tage",
        )

        st.divider()

        resolution = st.selectbox(
            "Auflösung",
            options=list(resolution_options),
            index=next(
                (
                    idx
                    for idx, option in enumerate(resolution_options)
                    if option == default_resolution
                ),
                0,
            ),
            key=f"{_REPORTING_FILTER_KEY_PREFIX}resolution",
            help="Zeitliche Auflösung der Daten",
        )

        st.divider()

        submitted = st.form_submit_button(
            "Filter anwenden", use_container_width=True, type="primary"
        )

    current_selection = {
        "microgrid_id": microgrid_id,
        "start_date": start_date,
        "end_date": end_date,
        "timezone": timezone,
        "resolution": resolution,
    }

    if submitted or _REPORTING_STATE_KEY not in st.session_state:
        st.session_state[_REPORTING_STATE_KEY] = current_selection

    return dict(st.session_state[_REPORTING_STATE_KEY])


def _default_reporting_date_range(today: date | None = None) -> tuple[date, date]:
    """Return the default reporting range covering the previous week."""
    range_end = today or datetime.now(tz=UTC).date()
    return range_end - timedelta(weeks=1), range_end


def _restore_reporting_widget_state() -> None:
    """Restore missing widget values from the last applied reporting filters.

    Streamlit may discard widget-owned keys while another page is rendered.
    The applied-filter dictionary is regular session state, so it remains the
    durable source for rebuilding the shared reporting sidebar.
    """
    applied_filters = st.session_state.get(_REPORTING_STATE_KEY)
    if not isinstance(applied_filters, dict):
        return

    for field in ("microgrid_id", "start_date", "end_date", "timezone", "resolution"):
        widget_key = f"{_REPORTING_FILTER_KEY_PREFIX}{field}"
        if widget_key not in st.session_state and field in applied_filters:
            st.session_state[widget_key] = applied_filters[field]


def _reconcile_microgrid_selection(
    available_microgrids: Sequence[int],
    key_prefix: str,
    applied_filters_key: str | None = None,
) -> None:
    """Replace session selections that are invalid for the current credentials."""
    if not available_microgrids:
        return

    microgrid_key = f"{key_prefix}microgrid_id"
    selected_microgrid = st.session_state.get(microgrid_key)
    if selected_microgrid not in available_microgrids:
        selected_microgrid = available_microgrids[0]
        st.session_state[microgrid_key] = selected_microgrid

    if applied_filters_key is None:
        return
    applied_filters = st.session_state.get(applied_filters_key)
    if not isinstance(applied_filters, dict):
        return
    if applied_filters.get("microgrid_id") in available_microgrids:
        return

    updated_filters = dict(applied_filters)
    updated_filters["microgrid_id"] = selected_microgrid
    st.session_state[applied_filters_key] = updated_filters


def _microgrid_option_label(
    microgrid_id: int, microgrid_names: dict[int, str | None]
) -> str:
    """Return the sidebar label for a microgrid selection option."""
    name = microgrid_names.get(microgrid_id)
    return f"{microgrid_id} — {name}" if name else str(microgrid_id)


# pylint: disable=too-many-instance-attributes
@dataclass(frozen=True)
class SolarWorkflowInputs:
    """Structured inputs for the solar maintenance workflow."""

    microgrid_id: int
    component_category: str
    language: str
    resample_period: str
    rolling_view_duration: int
    baseline_models: list[str]
    start_date: date
    time_zone: str


def collect_solar_sidebar_inputs(
    *,
    default_start_date: date,
    default_resample_period: str,
    baseline_model_options: Sequence[str],
    default_baseline_models: Sequence[str] | None = None,
    timezone_options: Sequence[str] | None = None,
    default_timezone: str = "UTC",
    key_prefix: str = "",
) -> tuple[SolarWorkflowInputs | None, bool]:
    """Render sidebar inputs for the solar maintenance workflow.

    Args:
        default_start_date: Default start date shown in the date picker.
        default_resample_period: Default resample period in seconds.
        baseline_model_options: Available baseline model options.
        default_baseline_models: Baseline models selected by default.
        timezone_options: Timezone options; defaults to all available timezones.
        default_timezone: Default timezone selection.
        key_prefix: Optional prefix for widget keys to avoid collisions.

    Returns:
        A tuple containing the collected selections (or ``None`` on error) and
        the submit flag.
    """
    st.sidebar.header("Solar Workflow")
    st.sidebar.caption("Konfigurieren Sie den Solar-Wartungsworkflow.")

    try:
        available_microgrids = get_microgrid_ids()
    except RuntimeError as exc:
        st.error(f"Microgrid-Konfigurationen konnten nicht geladen werden: {exc}")
        return None, False

    if not available_microgrids:
        st.error("Keine Microgrid-Konfigurationen gefunden.")
        return None, False

    _reconcile_microgrid_selection(available_microgrids, key_prefix)

    timezone_options_list = list(timezone_options or TIMEZONE_OPTIONS)
    timezone_default_index = next(
        (
            idx
            for idx, option in enumerate(timezone_options_list)
            if option == default_timezone
        ),
        0,
    )

    form_key = f"{key_prefix}solar_inputs" if key_prefix else "solar_inputs"
    default_baseline_models = list(default_baseline_models or [])

    with st.sidebar.form(form_key):
        st.subheader("Microgrid")
        microgrid_id = st.selectbox(
            "Microgrid auswählen",
            options=available_microgrids,
            format_func=str,
            key=f"{key_prefix}microgrid_id",
        )
        component_category = st.selectbox(
            "Komponentenkategorie auswählen",
            options=["inverter", "meter"],
            index=0,
            key=f"{key_prefix}component_category",
        )

        st.divider()
        st.subheader("Workflow")
        language = st.selectbox(
            "Sprache",
            options=["Deutsch", "Englisch"],
            index=0,
            key=f"{key_prefix}language",
        )
        resample_period = st.text_input(
            "Resampling-Intervall (Sekunden)",
            value=default_resample_period,
            key=f"{key_prefix}resample_period",
        )
        rolling_view_duration = st.slider(
            "Rolling-View-Dauer (Tage)",
            min_value=5,
            max_value=60,
            value=30,
            step=1,
            key=f"{key_prefix}rolling_view_duration",
        )
        baseline_models = st.multiselect(
            "Baseline-Modelle",
            options=list(baseline_model_options),
            default=default_baseline_models,
            key=f"{key_prefix}baseline_models",
        )

        st.divider()
        st.subheader("Datum und Zeit")
        start_date = st.date_input(
            "Startdatum",
            value=default_start_date,
            key=f"{key_prefix}start_date",
        )
        time_zone = st.selectbox(
            "Zeitzone",
            options=timezone_options_list,
            index=timezone_default_index,
            key=f"{key_prefix}timezone",
        )

        submit_button = st.form_submit_button("Starten", use_container_width=True)

    inputs_data = SolarWorkflowInputs(
        microgrid_id=int(microgrid_id),
        component_category=component_category,
        language=language,
        resample_period=resample_period,
        rolling_view_duration=rolling_view_duration,
        baseline_models=baseline_models,
        start_date=start_date,
        time_zone=time_zone,
    )

    return inputs_data, submit_button
