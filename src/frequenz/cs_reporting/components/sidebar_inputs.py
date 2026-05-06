# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Sidebar filter rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Sequence

import streamlit as st

from frequenz.cs_reporting.components import inputs
from frequenz.cs_reporting.services.client_factory import get_microgrid_ids

TIMEZONE_OPTIONS = (
    "Europe/Berlin",
    "Europe/Vienna",
    "Europe/Zurich",
    "Europe/Amsterdam",
    "Europe/Brussels",
    "Europe/Copenhagen",
    "UTC",
)


# pylint: disable=too-many-locals, too-many-arguments
def collect_sidebar_inputs(
    *,
    default_start: date,
    default_end: date,
    resolution_options: Sequence[str] = ("15min", "30min", "1hour", "4hour"),
    default_resolution: str = "15min",
    timezone_options: Sequence[str] = TIMEZONE_OPTIONS,
    default_timezone: str = "Europe/Berlin",
    key_prefix: str = "",
) -> dict[str, Any]:
    """Render structured sidebar filters with clear visual hierarchy.

    Creates an organized sidebar with sections for microgrid selection, date
    range, and resolution. Uses icons, dividers, and proper grouping for
    professional appearance and better UX.

    Args:
        default_start: Default start date for the date picker.
        default_end: Default end date for the date picker.
        resolution_options: Allowed resolution values for selection.
        default_resolution: Default resolution shown initially.
        timezone_options: Allowed timezone values for selection.
        default_timezone: Default timezone shown initially.
        key_prefix: Optional prefix for Streamlit widget keys.

    Returns:
        Dictionary containing ``microgrid_id``, ``start_date``,
            ``end_date``, ``timezone``, and ``resolution`` selected by the user.
    """
    # Header with icon and caption
    st.sidebar.header("Filter Einstellungen")
    st.sidebar.caption("Wählen Sie die Parameter für die Analyse.")

    form_key = f"{key_prefix}filters_form" if key_prefix else "filters_form"
    state_key = f"{key_prefix}applied_filters" if key_prefix else "applied_filters"

    with st.sidebar.form(form_key):
        # Microgrid Section
        st.subheader("Microgrid")
        microgrid_id = inputs.microgrid_selector(
            label="Microgrid-ID",
            ids=get_microgrid_ids(),
            key_prefix=key_prefix,
            container=st,
        )

        st.divider()

        # Date & Time Section
        st.subheader("Zeitraum")

        today = datetime.now(tz=UTC).date()
        fallback_start = default_start or (today - timedelta(days=7))

        start_key = f"{key_prefix}start_date"
        end_key = f"{key_prefix}end_date"
        timezone_key = f"{key_prefix}timezone"

        start_initial = st.session_state.get(start_key, fallback_start)

        columns = st.columns(2)
        with columns[0]:
            start_date = st.date_input(
                "Von",
                value=start_initial,
                max_value=today,
                key=start_key,
            )

        end_initial = min(
            st.session_state.get(end_key, default_end or today),
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

        # Resolution selector (full width)
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
            key=f"{key_prefix}resolution",
            help="Zeitliche Auflösung der Daten",
        )

        st.divider()

        # Prominent submit button
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

    if submitted or state_key not in st.session_state:
        st.session_state[state_key] = current_selection

    return dict(st.session_state[state_key])


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
        )
        component_category = st.selectbox(
            "Komponentenkategorie auswählen",
            options=["inverter", "meter"],
            index=0,
        )

        st.divider()
        st.subheader("Workflow")
        language = st.selectbox(
            "Sprache",
            options=["Deutsch", "Englisch"],
            index=0,
        )
        resample_period = st.text_input(
            "Resampling-Intervall (Sekunden)",
            value=default_resample_period,
        )
        rolling_view_duration = st.slider(
            "Rolling-View-Dauer (Tage)",
            min_value=5,
            max_value=60,
            value=30,
            step=1,
        )
        baseline_models = st.multiselect(
            "Baseline-Modelle",
            options=list(baseline_model_options),
            default=default_baseline_models,
        )

        st.divider()
        st.subheader("Datum und Zeit")
        start_date = st.date_input(
            "Startdatum",
            value=default_start_date,
        )
        time_zone = st.selectbox(
            "Zeitzone",
            options=timezone_options_list,
            index=timezone_default_index,
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
