# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Metric rendering functions for the reporting views."""

from __future__ import annotations

from typing import Any, Iterable

import streamlit as st

from frequenz.cs_reporting.components.plot_charts import plot_percentage_bar


def _peak_label(metrics: dict[str, object]) -> str:
    """Compose the label for the peak metric box.

    Args:
        metrics: Metrics dictionary expected to contain ``peak_date``.

    Returns:
        Localized peak label including the peak date.
    """
    return f"Lastspitze (kW) - {metrics.get('peak_date')}"


SECTION_SPECS: list[dict[str, Any]] = [
    {
        "title": "Verbrauch",
        "boxes": [
            {"label": "Stromverbrauch (kWh)", "key": "mid_consumption_sum"},
            {"label": "", "key": None},
            {"label": "", "key": None},
        ],
    },
    {
        "title": "Netzbezug",
        "boxes": [
            {"label": "Netzbezug (kWh)", "key": "grid_consumption_sum"},
            {"label": "Einspeisung (kWh)", "key": "grid_feed_in_sum"},
            {"label_fn": _peak_label, "key": "peak"},
        ],
    },
    {
        "title": "Gesamterzeugung",
        "boxes": [
            {"label": "Gesamterzeugung (kWh)", "key": "total_production_sum"},
            {
                "label": "PV Gesamterzeugung (kWh)",
                "key": "pv_production_sum",
                "component_type": "pv",
            },
            {
                "label": "BHKW Gesamterzeugung (kWh)",
                "key": "chp_production_sum",
                "component_type": "chp",
            },
            {
                "label": "Wind Gesamterzeugung (kWh)",
                "key": "wind_production_sum",
                "component_type": "wind",
            },
        ],
    },
    {
        "title": "Eigenverbrauch",
        "boxes": [
            {"label": "Eigenverbrauch (kWh)", "key": "prod_self_consumption_sum"},
            {
                "label": "Eigenverbrauchsanteil (%)",
                "key": "prod_self_consumption_share",
                "transform": lambda v: v * 100,
            },
        ],
    },
]


def _materialize_boxes(
    box_specs: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> list[tuple[str, object]]:
    """Resolve box specifications to label/value tuples.

    Args:
        box_specs: List of box configuration dictionaries with ``label``,
            ``label_fn``, ``key``, and optional ``transform`` entries.
        metrics: Metrics dictionary supplying values for the configured keys.

    Returns:
        Prepared label and value pairs for rendering.
    """
    boxes: list[tuple[str, object]] = []
    for spec in box_specs:
        label = spec.get("label", "")
        if "label_fn" in spec:
            label = spec["label_fn"](metrics)

        value = metrics.get(spec["key"]) if spec.get("key") else None
        transform = spec.get("transform")
        if transform is not None and value is not None:
            value = transform(value)

        boxes.append((label, value))
    return boxes


def render_box_grid(
    boxes: list[tuple[str, object]], per_row: int = 3, row_gap: int = 20
) -> None:
    """Render boxes in a grid layout.

    Args:
        boxes: Prepared list of label/value tuples.
        per_row: Maximum number of boxes to render per row.
        row_gap: Vertical gap between rows in pixels.

    Returns:
        Streamlit markup is written directly to the page.
    """
    for i in range(0, len(boxes), per_row):
        row = boxes[i : i + per_row]

        # pad row with empty boxes so it always has `per_row` items
        while len(row) < per_row:
            row.append(("", None))

        cols = st.columns(per_row, gap="medium")
        for col, (label, val) in zip(cols, row):
            if label == "" and val is None:
                # render transparent placeholder
                col.markdown(
                    """
                    <div style="
                        background:transparent;
                        border:1px solid transparent;
                        border-radius:8px;
                        padding:14px;
                        text-align:center;
                    ">&nbsp;</div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                txt = (
                    "-"
                    if val is None
                    else (f"{val:,.2f}" if isinstance(val, (int, float)) else str(val))
                )
                col.markdown(
                    f"""
                    <div style="
                        background:#f9f9f9;
                        border:1px solid #ddd;
                        border-radius:8px;
                        padding:14px;
                        text-align:center;
                        box-shadow:1px 1px 3px rgba(0,0,0,0.06);
                    ">
                        <div style="font-size:13px;color:#555;">{label}</div>
                        <div style="font-size:20px;font-weight:700;color:#1565c0;">{txt}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        # add vertical gap between rows (except last)
        if i + per_row < len(boxes):
            st.markdown(
                f"<div style='margin-top:{row_gap}px;'></div>", unsafe_allow_html=True
            )


def _build_consumption_breakdown(metrics: dict[str, Any]) -> dict[str, float | None]:
    """Prepare data for the percentage bar plot.

    Args:
        metrics: Metrics dictionary with consumption and production values.

    Returns:
        Mapping of label to value with missing entries
            normalized to ``0.0``.
    """
    values = {
        "Stromverbrauch (kWh)": metrics.get("mid_consumption_sum"),
        "Netzbezug (kWh)": metrics.get("grid_consumption_sum"),
        "PV Gesamterzeugung (kWh)": metrics.get("pv_production_sum"),
        "BHKW Gesamterzeugung (kWh)": metrics.get("chp_production_sum"),
        "Wind Gesamterzeugung (kWh)": metrics.get("wind_production_sum"),
    }
    return {k: (float(v) if v is not None else 0.0) for k, v in values.items()}


def render_summary_boxes(
    metrics: dict[str, Any],
    component_types: Iterable[str] | None = None,
) -> None:
    """Render overview metrics grouped into subsections.

    Args:
        metrics: Metrics dictionary containing aggregated KPI values.
        component_types: Optional iterable of component type identifiers present
            in the microgrid (e.g., ``{"pv", "chp"}``).

    Returns:
        Streamlit components are rendered directly.
    """
    if not metrics:
        st.info("No overview metrics available.")
        return

    component_type_set = set(component_types or [])

    st.subheader("Übersicht")

    for section in SECTION_SPECS:
        st.markdown(f"##### {section['title']}")
        box_specs = section["boxes"]
        if component_type_set:
            box_specs = [
                spec
                for spec in box_specs
                if spec.get("component_type") is None
                or spec.get("component_type") in component_type_set
            ]
        boxes = _materialize_boxes(box_specs, metrics)
        render_box_grid(boxes)

    consumption_dict = _build_consumption_breakdown(metrics)
    consumption_bar_plot = plot_percentage_bar(
        consumption_dict, total_key="Stromverbrauch (kWh)"
    )
    st.plotly_chart(consumption_bar_plot, width="stretch")
