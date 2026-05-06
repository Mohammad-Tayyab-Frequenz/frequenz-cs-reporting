# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Dashboard page to explore microgrid data and visualizations."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
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
)
from frequenz.cs_reporting.services.data_service import get_microgrid_data
from frequenz.cs_reporting.views.dashboard import build_master_df, render_dashboard


def _scroll_to_section_if_requested() -> None:
    """Scroll to a dashboard section when requested via query params."""
    if st.query_params.get("section") != "data-export":
        return

    # Execute in parent document because Streamlit components render in an iframe.
    components.html(
        """
        <script>
        const target = window.parent.document.getElementById("data-export-section");
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
        </script>
        """,
        height=0,
    )


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


# pylint: disable=too-many-locals
def render() -> None:
    """Render the Frequenz Reporting Dashboard page.

    Collects sidebar inputs, fetches microgrid data, prepares it for analysis,
    and renders the dashboard views.

    Returns:
        Streamlit components are rendered directly.
    """
    # Page header
    st.title("Reporting-Dashboard")

    # Collect user inputs from sidebar
    today = datetime.now(tz=UTC).date()
    selections = collect_sidebar_inputs(
        default_start=today,
        default_end=today,
        resolution_options=("15min", "30min", "1hour"),
        default_resolution="15min",
    )

    timezone = selections["timezone"]
    # Extract and convert inputs
    microgrid_id = selections["microgrid_id"]

    # set_date_to_midnight returns TZ-aware datetimes aligned with the user's timezone
    start_time = set_date_to_midnight(selections["start_date"], timezone)
    end_time = normalize_date_for_reporting(selections["end_date"], timezone)
    end_time = end_time.replace(microsecond=0)
    if end_time.date() != datetime.now(tz=UTC).date():
        end_time += timedelta(days=1)

    # Validate date range
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

    # Fetch microgrid configuration
    component_types = list(get_component_types(microgrid_id))
    mcfg = get_microgrid_config(microgrid_id)

    # We extend the fetch end date by 1 day to ensure the API returns data
    # for the full duration of the selected end_time.

    # Fetch data with error handling
    try:
        with st.spinner("Microgrid-Daten werden geladen..."):
            df = get_microgrid_data(
                microgrid_id=microgrid_id,
                start_date=start_time,
                # Use the extended date here to ensure we get the full last day
                end_date=end_time,
                resolution=resolution,
            )
    except (RuntimeError, ValueError, OSError) as e:
        st.error(f"Daten konnten nicht geladen werden: {e}")
        st.stop()

    # Check for empty results
    if df.empty:
        st.warning("Keine Daten für die ausgewählten Filter vorhanden.")
        st.stop()

    # Normalize the dataframe (Handle Index)
    df_prepared = _prepare_dataframe(df)

    # Build and render dashboard
    mapper = ColumnMapper.from_default()
    master_df = build_master_df(df_prepared, component_types, mcfg, mapper)
    render_dashboard(
        master_df,
        resolution=resolution,
        component_types=component_types,
        mapper=mapper,
    )
    _scroll_to_section_if_requested()


PAGE = PageSpec(
    key="reporting_dashboard",
    title="Reporting",
    icon="",
    order=1,
    render=render,
)
