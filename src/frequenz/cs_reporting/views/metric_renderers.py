# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Metric rendering functions for the reporting views."""

from __future__ import annotations

from typing import Any, Iterable

import streamlit as st

from frequenz.cs_reporting.components.plot_charts import plot_percentage_bar
from frequenz.cs_reporting.ui_resources import inject_style

# ── Section accent colours ─────────────────────────────────────────────────────
# Each reporting section gets a distinct left-border colour so the dashboard
# reads as a structured, visually hierarchical document.
_SECTION_ACCENTS: dict[str, str] = {
    "Netzkennzahlen": "#3b82f6",              # blue  – grid
    "(Eigen-)Erzeugungskennzahlen": "#10b981", # green – generation
    "Verbrauchskennzahlen": "#f59e0b",         # amber – consumption
    "Bilanzkennzahlen": "#8b5cf6",             # purple – balance ratios
}

_SECTION_ICONS: dict[str, str] = {
    "Netzkennzahlen": "⚡",
    "(Eigen-)Erzeugungskennzahlen": "☀",
    "Verbrauchskennzahlen": "📊",
    "Bilanzkennzahlen": "⚖",
}

def _ensure_kpi_css() -> None:
    """Inject KPI styles for the current Streamlit run."""
    inject_style("kpi.css")


def _peak_label(metrics: dict[str, object]) -> str:
    """Compose the label for the peak metric box."""
    return f"Lastspitze (kW) — {metrics.get('peak_date')}"


SECTION_SPECS: list[dict[str, Any]] = [
    {
        "title": "Netzkennzahlen",
        "boxes": [
            {"label": "Netzbezug (kWh)", "key": "grid_consumption_sum"},
            {"label": "Netzeinspeisung (kWh)", "key": "grid_feed_in_sum"},
            {"label_fn": _peak_label, "key": "peak"},
        ],
    },
    {
        "title": "(Eigen-)Erzeugungskennzahlen",
        "boxes": [
            {"label": "Gesamterzeugung (kWh)", "key": "total_production_sum"},
            {
                "label": "PV-Erzeugung (kWh)",
                "key": "pv_production_sum",
                "component_type": "pv",
            },
            {
                "label": "KWK-Erzeugung (kWh)",
                "key": "chp_production_sum",
                "component_type": "chp",
            },
            {
                "label": "Wind-Erzeugung (kWh)",
                "key": "wind_production_sum",
                "component_type": "wind",
            },
        ],
    },
    {
        "title": "Verbrauchskennzahlen",
        "per_row": 3,
        "boxes": [
            {"label": "Gesamtverbrauch Strom (kWh)", "key": "mid_consumption_sum"},
            {"label": "Eigenverbrauch (kWh)", "key": "prod_self_consumption_sum"},
        ],
    },
    {
        "title": "Bilanzkennzahlen",
        "per_row": 3,
        "boxes": [
            {
                "label": "Autarkiegrad (%)",
                "key": "prod_self_consumption_share",
                "transform": lambda v: v * 100,
            },
            {
                "label": "Eigenverbrauchsquote (%)",
                "key": "prod_self_production_share",
                "transform": lambda v: v * 100,
            },
        ],
    },
]


def _materialize_boxes(
    box_specs: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> list[tuple[str, object]]:
    """Resolve box specifications to label/value tuples."""
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
    boxes: list[tuple[str, object]],
    per_row: int = 3,
    row_gap: int = 12,
    accent: str = "#3b82f6",
) -> None:
    """Render KPI boxes in a professional card grid.

    Args:
        boxes: Prepared list of label/value tuples.
        per_row: Maximum number of boxes to render per row.
        row_gap: Vertical gap between rows in pixels.
        accent: Left-border accent colour for the cards.

    Returns:
        Streamlit markup is written directly to the page.
    """
    _ensure_kpi_css()

    for i in range(0, len(boxes), per_row):
        row = boxes[i : i + per_row]
        while len(row) < per_row:
            row.append(("", None))

        cols = st.columns(per_row, gap="small")
        for col, (label, val) in zip(cols, row):
            if label == "" and val is None:
                col.markdown(
                    '<div class="kpi-card kpi-card--empty">&nbsp;</div>',
                    unsafe_allow_html=True,
                )
            else:
                if val is None:
                    value_html = '<div class="kpi-card__value kpi-card__value--null">—</div>'
                elif isinstance(val, float) and val == int(val):
                    value_html = f'<div class="kpi-card__value">{val:,.0f}</div>'
                elif isinstance(val, (int, float)):
                    value_html = f'<div class="kpi-card__value">{val:,.2f}</div>'
                else:
                    value_html = f'<div class="kpi-card__value">{val}</div>'

                col.markdown(
                    f"""
                    <div class="kpi-card" style="--kpi-accent:{accent};">
                        <div class="kpi-card__label">{label}</div>
                        {value_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        if i + per_row < len(boxes):
            st.markdown(
                f"<div style='margin-top:{row_gap}px;'></div>",
                unsafe_allow_html=True,
            )


def _build_consumption_breakdown(metrics: dict[str, Any]) -> dict[str, float | None]:
    """Prepare data for the percentage bar plot."""
    values = {
        "Stromverbrauch (kWh)": metrics.get("mid_consumption_sum"),
        "Netzbezug (kWh)": metrics.get("grid_consumption_sum"),
        "Netz Einspeisung (kWh)": -(metrics.get("grid_feed_in_sum") or 0),
        "PV Gesamterzeugung (kWh)": metrics.get("pv_production_sum"),
        "KWK Gesamterzeugung (kWh)": metrics.get("chp_production_sum"),
        "Wind Gesamterzeugung (kWh)": metrics.get("wind_production_sum"),
    }
    return {k: (float(v) if v is not None else 0.0) for k, v in values.items()}


def render_summary_boxes(
    metrics: dict[str, Any],
    component_types: Iterable[str] | None = None,
) -> None:
    """Render overview metrics grouped into styled subsections.

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

    _ensure_kpi_css()
    component_type_set = set(component_types or [])

    # Section heading
    st.markdown(
        """
        <div class="metrics-heading">
            <h2>Key Performance Indicators</h2>
            <div class="metrics-heading__line"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    for section in SECTION_SPECS:
        title = section["title"]
        accent = _SECTION_ACCENTS.get(title, "#3b82f6")
        icon = _SECTION_ICONS.get(title, "●")
        icon_bg = accent + "22"  # ~13% opacity hex approximation

        st.markdown(
            f"""
            <div class="kpi-section-header">
                <div class="kpi-section-icon" style="background:{icon_bg};">{icon}</div>
                <p class="kpi-section-title">{title}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        box_specs = section["boxes"]
        if component_type_set:
            box_specs = [
                spec
                for spec in box_specs
                if spec.get("component_type") is None
                or spec.get("component_type") in component_type_set
            ]
        boxes = _materialize_boxes(box_specs, metrics)
        per_row = section.get("per_row", 3)
        render_box_grid(boxes, per_row=per_row, accent=accent)

    # Consumption breakdown bar
    st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
    consumption_dict = _build_consumption_breakdown(metrics)
    consumption_bar_plot = plot_percentage_bar(
        consumption_dict, total_key="Stromverbrauch (kWh)"
    )
    st.plotly_chart(consumption_bar_plot, width="stretch")
