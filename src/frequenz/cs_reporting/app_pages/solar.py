# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Solar monitoring page."""

from __future__ import annotations

import asyncio
import datetime
import traceback
from contextlib import contextmanager
from typing import Iterator

import matplotlib.pyplot as plt
import streamlit as st
from frequenz.lib.notebooks.solar.maintenance.solar_maintenance_app import run_workflow
from matplotlib.figure import Figure

from frequenz.cs_reporting.components.sidebar_inputs import collect_solar_sidebar_inputs
from frequenz.cs_reporting.rep_cs_core.page_spec import PageSpec
from frequenz.cs_reporting.services.client_factory import get_microgrid_config
from frequenz.cs_reporting.services.solar_workflow import build_workflow_request
from frequenz.cs_reporting.views.solar_results import render_workflow_results

DEFAULT_START_DATE = datetime.date(datetime.date.today().year, 1, 1)
DEFAULT_RESAMPLE_PERIOD = "3600"
DEFAULT_BASELINE_MODELS: list[str] = []


@contextmanager
def capture_figures() -> Iterator[list[Figure]]:
    """Capture new Matplotlib figures created within the context.

    Yields:
        A list that will be populated with new figures after the context exits.
    """
    closed_figures: list[Figure] = []
    # Close any existing figures to start fresh (optional, depending on desired behavior)
    # plt.close("all") # Careful with this if other pages rely on state

    existing_nums = set(plt.get_fignums())
    try:
        yield closed_figures
    finally:
        current_nums = set(plt.get_fignums())
        new_nums = current_nums - existing_nums
        closed_figures.extend([plt.figure(num) for num in new_nums])


def render() -> None:
    """Render the Solar Maintenance & Monitoring page."""
    st.title("Solar Maintenance & Monitoring")
    st.divider()

    inputs_data, submit_button = collect_solar_sidebar_inputs(
        default_start_date=DEFAULT_START_DATE,
        default_resample_period=DEFAULT_RESAMPLE_PERIOD,
        baseline_model_options=[
            "7-day MA",
            "7-day sampled MA",
            "weather-based-forecast",
        ],
        default_baseline_models=DEFAULT_BASELINE_MODELS,
    )

    if inputs_data is None:
        return

    if not submit_button:
        st.info(
            "Select options in the sidebar and click Start to run the solar workflow."
        )
        return

    try:
        microgrid_config = get_microgrid_config(inputs_data.microgrid_id)
    except (KeyError, RuntimeError) as exc:
        st.error(
            f"Configuration not found for microgrid {inputs_data.microgrid_id}: {exc}"
        )
        return

    try:
        user_request = build_workflow_request(
            microgrid_id=inputs_data.microgrid_id,
            config=microgrid_config,
            start_date=inputs_data.start_date,
            time_zone=inputs_data.time_zone,
            component_category=inputs_data.component_category,
            language=inputs_data.language,
            resample_period=inputs_data.resample_period,
            rolling_view_duration=inputs_data.rolling_view_duration,
            baseline_models=inputs_data.baseline_models,
        )
    except Exception as exc:  # pylint: disable=broad-except
        st.error(f"Failed to prepare request: {exc}")
        # Improve logging (could use proper logger, simplistic print for now as in original)
        print(f"Error building workflow request:\n{traceback.format_exc()}")
        return

    with st.spinner("Running workflow..."):
        with capture_figures() as new_figures:
            plot_data = asyncio.run(run_workflow(user_config_changes=user_request))

    render_workflow_results(plot_data, new_figures)


PAGE = PageSpec(
    key="solar",
    title="Solar Monitoring",
    icon="",
    order=2,
    render=render,
)
