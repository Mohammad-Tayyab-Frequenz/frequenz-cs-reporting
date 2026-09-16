# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Helpers for selecting component data sources in reporting views."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Literal

import pandas as pd
import streamlit as st
from frequenz.lib.notebooks.reporting.utils.reporting_nb_functions import (
    build_component_analysis,
)

PLOT_SOURCE_OPTIONS = ("meter", "inverter")
PLOT_SOURCE_ANALYSIS_KEYS = frozenset({"pv", "batt", "wind", "chp"})


def component_type_from_analysis_key(analysis_key: str) -> str:
    """Return the microgrid component type for an analysis table key."""
    if analysis_key == "batt":
        return "battery"
    return analysis_key


def component_ids_for_plot_source(
    mcfg: Any,
    component_types: Iterable[str],
    component_plot_source: str,
) -> dict[str, tuple[str, ...]]:
    """Return component ID filters for the selected HTH plot source."""
    component_type_set = set(component_types)
    analysis_ids: dict[str, tuple[str, ...]] = {}

    for analysis_key in PLOT_SOURCE_ANALYSIS_KEYS:
        component_type = component_type_from_analysis_key(analysis_key)
        if component_type not in component_type_set:
            continue

        category_ids = (
            mcfg.component_type_ids(
                component_type,
                component_category=component_plot_source,
            )
            or []
        )
        if component_plot_source == "inverter" and not category_ids:
            category_ids = (
                mcfg.component_type_ids(
                    component_type,
                    component_category="component",
                )
                or []
            )

        analysis_ids[analysis_key] = tuple(str(cid) for cid in sorted(category_ids))

    return analysis_ids


def default_component_plot_source(
    mcfg: Any,
    component_types: Iterable[str],
    analysis_key: str,
    *,
    source_has_data: Callable[[str], bool] | None = None,
) -> str:
    """Return the best default component source for an analysis key."""
    if analysis_key not in PLOT_SOURCE_ANALYSIS_KEYS:
        return PLOT_SOURCE_OPTIONS[0]

    if source_has_data and not source_has_data("meter") and source_has_data("inverter"):
        return "inverter"

    source_ids = {
        source: component_ids_for_plot_source(mcfg, component_types, source).get(
            analysis_key, ()
        )
        for source in PLOT_SOURCE_OPTIONS
    }
    if not source_ids["meter"] and source_ids["inverter"]:
        return "inverter"
    return "meter"


def selected_component_plot_source(
    mcfg: Any,
    component_types: Iterable[str],
    analysis_key: str,
    *,
    state_key: str,
    source_has_data: Callable[[str], bool] | None = None,
) -> str:
    """Return the selected component source, initializing a useful default."""
    selected_source = st.session_state.get(state_key)
    if selected_source in PLOT_SOURCE_OPTIONS:
        return str(selected_source)

    selected_source = default_component_plot_source(
        mcfg,
        component_types,
        analysis_key,
        source_has_data=source_has_data,
    )
    st.session_state[state_key] = selected_source
    return selected_source


# pylint: disable=too-many-arguments, too-many-positional-arguments
def component_analysis_for_source(
    master_df: pd.DataFrame,
    mcfg: Any,
    component_types: Iterable[str],
    analysis_key: str,
    component_label: str,
    value_col_name: str,
    component_plot_source: str,
) -> pd.DataFrame:
    """Build component analysis for a selected component data source."""
    selected_ids = component_ids_for_plot_source(
        mcfg,
        component_types,
        component_plot_source,
    ).get(analysis_key)
    return build_component_analysis(
        master_df,
        selection_filter=["All"],
        component_label=component_label,
        value_col_name=value_col_name,
        allowed_component_ids=(set(selected_ids) if selected_ids is not None else None),
    )


# pylint: disable=too-many-arguments, too-many-positional-arguments
def component_source_has_data(
    master_df: pd.DataFrame,
    mcfg: Any,
    component_types: Iterable[str],
    analysis_key: str,
    component_label: str,
    value_col_name: str,
    component_plot_source: str,
) -> bool:
    """Return whether a source produces component analysis rows."""
    return not component_analysis_for_source(
        master_df,
        mcfg,
        component_types,
        analysis_key,
        component_label,
        value_col_name,
        component_plot_source,
    ).empty


# pylint: disable=too-many-arguments
def render_component_source_selector(
    mcfg: Any,
    component_types: Iterable[str],
    analysis_key: str,
    *,
    state_key: str,
    widget_key: str,
    label_visibility: Literal["visible", "hidden", "collapsed"] = "visible",
) -> None:
    """Render a source selector that stays synced through a canonical state key."""
    selected_source = selected_component_plot_source(
        mcfg,
        component_types,
        analysis_key,
        state_key=state_key,
    )
    if st.session_state.get(widget_key) != selected_source:
        st.session_state[widget_key] = selected_source

    def sync_source() -> None:
        st.session_state[state_key] = st.session_state[widget_key]

    st.selectbox(
        "Komponentenquelle",
        options=PLOT_SOURCE_OPTIONS,
        format_func=lambda value: {
            "meter": "Meter",
            "inverter": "Inverter / Komponenten",
        }[value],
        key=widget_key,
        on_change=sync_source,
        label_visibility=label_visibility,
    )
