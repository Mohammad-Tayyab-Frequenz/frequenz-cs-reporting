# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Metric rendering functions for the reporting views."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from html import escape
from math import isfinite
from typing import Any, Iterable

import streamlit as st

from frequenz.cs_reporting.constants import KPI_SECTION_ACCENTS
from frequenz.cs_reporting.ui_resources import inject_style, load_tooltips


def _fmt_de(val: float, decimals: int) -> str:
    """Format a number in German locale (period thousands, comma decimal)."""
    formatted = f"{val:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_metric_value(val: object) -> str:
    """Format a KPI value for display."""
    if val is None:
        return "—"
    if isinstance(val, (int, float)):
        numeric_value = float(val)
        if not isfinite(numeric_value):
            return "—"
        if numeric_value == int(numeric_value):
            return _fmt_de(numeric_value, 0)
        return _fmt_de(numeric_value, 2)
    return str(val)


def _unit_from_label(label: str) -> str:
    """Extract a display unit from a KPI label like ``Netzbezug (kWh)``."""
    match = re.search(r"\(([^)]+)\)", label)
    return match.group(1) if match else ""


def _format_previous_value(label: str, value: object) -> str:
    """Format the previous-period text for a KPI card."""
    unit = _unit_from_label(label)
    unit_suffix = f" {unit}" if unit else ""
    return f"Vorperiode: {_fmt_metric_value(value)}{unit_suffix}"


def _format_current_value(label: str, value: object) -> str:
    """Format the current KPI value together with its display unit."""
    unit = _unit_from_label(label)
    unit_suffix = f" {unit}" if unit else ""
    return f"{_fmt_metric_value(value)}{unit_suffix}"


_PRIOR_PERIOD_TOOLTIP = load_tooltips("common")["prior_period"]

_DELTA_COMPARISONS = {
    "Netzbezug (kWh)": "neutral",
    "Netzbetreiber Netzbezug (kWh)": "neutral",
    "Netzbetreiber Netzeinspeisung (kWh)": "neutral",
    "Netzeinspeisung (kWh)": "neutral",
    "Gesamtverbrauch Strom (kWh)": "neutral",
    "Gesamterzeugung (kWh)": "more_is_good",
    "PV-Erzeugung (kWh)": "more_is_good",
    "KWK-Erzeugung (kWh)": "more_is_good",
    "Wind-Erzeugung (kWh)": "more_is_good",
    "Eigenverbrauch (kWh)": "more_is_good",
    "Autarkiegrad (%)": "more_is_good",
    "Eigenverbrauchsquote (%)": "more_is_good",
    "Erzeugung zu Batterie (kWh)": "neutral",
    "Netz zu Batterie (kWh)": "neutral",
    "Batterie zu Netz (kWh)": "neutral",
    "Batterie zu Verbrauch (kWh)": "neutral",
}


def _delta_html(
    current: object,
    previous: object,
    comparison: str = "less_is_good",
) -> str:
    """Build a percentage-delta badge for numeric KPI values."""
    if not isinstance(current, (int, float)) or not isinstance(previous, (int, float)):
        return ""
    current_value = float(current)
    previous_value = float(previous)
    if (
        not isfinite(current_value)
        or not isfinite(previous_value)
        or previous_value == 0
    ):
        return ""

    delta = ((current_value - previous_value) / abs(previous_value)) * 100
    if delta == 0 or comparison == "neutral":
        delta_class = "kpi-card__delta--neutral"
    elif (delta > 0) == (comparison == "more_is_good"):
        delta_class = "kpi-card__delta--positive"
    else:
        delta_class = "kpi-card__delta--negative"
    sign = "+" if delta > 0 else ""
    return (
        f'<span class="kpi-card__delta {delta_class}">'
        f"{sign}{_fmt_de(delta, 1)}%</span>"
    )


def _kpi_label_html(label: str) -> str:
    """Render a KPI label without duplicating the unit shown in its value."""
    display_label = re.sub(r"\s*\([^)]*\)", "", label)
    return f'<span class="kpi-card__label-text">{escape(display_label)}</span>'


def _kpi_tooltip_content_html(tooltip: object) -> str:
    """Format optional heading/body tooltip sections as safe HTML."""
    text = str(tooltip)
    blocks = text.split("\n\n")
    if len(blocks) == 1:
        return escape(" ".join(text.split()))

    sections: list[str] = []
    for block in blocks:
        heading, separator, body = block.partition("\n")
        safe_heading = escape(" ".join(heading.split()))
        if not separator:
            sections.append(
                f'<span class="kpi-card__tooltip-body">{safe_heading}</span>'
            )
            continue
        safe_body = escape(" ".join(body.split()))
        sections.append(
            f'<span class="kpi-card__tooltip-heading">{safe_heading}</span>'
            f'<span class="kpi-card__tooltip-body">{safe_body}</span>'
        )
    return "".join(sections)


def _kpi_tooltip_aria_label(tooltip: object) -> str:
    """Return single-line escaped tooltip text safe for an HTML attribute."""
    return escape(" ".join(str(tooltip).split()), quote=True)


def _prior_period_help_html() -> str:
    """Render the help tooltip displayed beside the prior-period value."""
    tooltip = escape(_PRIOR_PERIOD_TOOLTIP, quote=True)
    return (
        f'<span class="kpi-card__help" role="img" tabindex="0" '
        f'aria-label="{tooltip}">i'
        f'<span class="kpi-card__help-tooltip">{tooltip}</span></span>'
    )


_SECTION_ICONS: dict[str, str] = {
    "Netzkennzahlen": "⚡",
    "(Eigen-)Erzeugungskennzahlen": "☀",
    "Verbrauchskennzahlen": "📊",
    "Batteriekennzahlen": "🔋",
    "Bilanzkennzahlen": "⚖",
}


def _ensure_kpi_css() -> None:
    """Inject KPI styles for the current Streamlit run."""
    inject_style("kpi.css")


def _peak_label(metrics: dict[str, object]) -> str:
    """Compose the label for the peak metric box."""
    return f"Lastspitze (kW) — {metrics.get('peak_date')}"


_INVOICING_WARNING = load_tooltips("reporting")["invoicing_warning"]
_OPTIONAL_METRIC_KEYS = {
    "dso_import_energy_sum",
    "dso_export_energy_sum",
    "dso_import_cost_sum",
    "dso_export_revenue_sum",
    "average_da_price_dso_import",
    "average_da_price_dso_export",
}


SECTION_SPECS: list[dict[str, Any]] = [
    {
        "title": "Netzkennzahlen - Reporting Daten",
        "warning": _INVOICING_WARNING,
        "boxes": [
            {
                "label": "Netzbezug (kWh)",
                "key": "grid_consumption_sum",
                "group": "grid-import",
            },
            {
                "label": "Prognostizierte Netzbezugskosten (€)",
                "key": "grid_import_cost_sum",
                "group": "grid-import",
            },
            {
                "label": "Prognostizierter Preis (ct/kWh)",
                "key": "average_da_price_grid_import",
                "group": "grid-import",
            },
            {
                "label": "Netzeinspeisung (kWh)",
                "key": "grid_feed_in_sum",
                "group": "grid-feed-in",
            },
            {
                "label": "Prognostizierte Einspeiseerlöse (€)",
                "key": "grid_feed_in_revenue_sum",
                "group": "grid-feed-in",
            },
            {
                "label": "Prognostizierter Preis (ct/kWh)",
                "key": "average_da_price_grid_feed_in",
                "group": "grid-feed-in",
            },
        ],
    },
    {
        "title": "Netzkennzahlen - Netzbetreiber",
        "required_any_metric_keys": {
            "dso_import_energy_sum",
            "dso_export_energy_sum",
        },
        "boxes": [
            {
                "label": "Netzbezug (kWh)",
                "key": "dso_import_energy_sum",
                "group": "dso-import",
            },
            {
                "label": "Netzbezugskosten (€)",
                "key": "dso_import_cost_sum",
                "group": "dso-import",
            },
            {
                "label": "Preis (ct/kWh)",
                "key": "average_da_price_dso_import",
                "group": "dso-import",
            },
            {
                "label": "Netzeinspeisung (kWh)",
                "key": "dso_export_energy_sum",
                "group": "dso-export",
            },
            {
                "label": "Einspeiseerlöse (€)",
                "key": "dso_export_revenue_sum",
                "group": "dso-export",
            },
            {
                "label": "Preis (ct/kWh)",
                "key": "average_da_price_dso_export",
                "group": "dso-export",
            },
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
            {"label": "Eigenverbrauch (kWh)", "key": "prod_self_consumption_sum"},
        ],
    },
    {
        "title": "Verbrauchskennzahlen",
        "boxes": [
            {"label": "Gesamtverbrauch Strom (kWh)", "key": "mid_consumption_sum"},
        ],
    },
    # Battery KPI cards are temporarily hidden.
    # {
    #     "title": "Batteriekennzahlen",
    #     "required_component_type": "battery",
    #     "boxes": [...],
    # },
    {
        "title": "Bilanzkennzahlen",
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
    previous_metrics: dict[str, Any] | None = None,
) -> list[tuple[str, object, object]]:
    """Resolve box specifications to label/value tuples."""
    boxes: list[tuple[str, object, object]] = []
    for spec in box_specs:
        label = spec.get("label", "")
        if "label_fn" in spec:
            label = spec["label_fn"](metrics)

        value = metrics.get(spec["key"]) if spec.get("key") else None
        previous_value = (
            previous_metrics.get(spec["key"])
            if previous_metrics is not None and spec.get("key")
            else None
        )
        transform = spec.get("transform")
        if transform is not None and value is not None:
            value = transform(value)
        if transform is not None and previous_value is not None:
            previous_value = transform(previous_value)

        boxes.append((label, value, previous_value))
    return boxes


def _filter_section_box_specs(
    section: dict[str, Any],
    component_type_set: set[str],
    component_types_provided: bool,
    microgrid_id: int | None,
) -> list[dict[str, Any]]:
    """Return KPI box specs that apply to the selected microgrid."""
    del microgrid_id
    required_component_type = section.get("required_component_type")
    if (
        component_types_provided
        and required_component_type is not None
        and required_component_type not in component_type_set
    ):
        return []

    box_specs: list[dict[str, Any]] = section["boxes"]
    if component_types_provided:
        box_specs = [
            spec
            for spec in box_specs
            if spec.get("component_type") is None
            or spec.get("component_type") in component_type_set
        ]

    if section["title"] == "(Eigen-)Erzeugungskennzahlen":
        production_types = component_type_set.intersection({"pv", "chp", "wind"})
        if component_types_provided and len(production_types) <= 1:
            box_specs = [
                spec for spec in box_specs if spec.get("key") != "total_production_sum"
            ]

    return box_specs


def _filter_available_optional_metric_specs(
    box_specs: list[dict[str, Any]], metrics: dict[str, Any]
) -> list[dict[str, Any]]:
    """Hide optional KPI cards only when their source metric is unavailable."""
    return [
        spec
        for spec in box_specs
        if spec.get("key") not in _OPTIONAL_METRIC_KEYS or spec.get("key") in metrics
    ]


# pylint: disable=too-many-locals,too-many-arguments,too-many-positional-arguments
def _card_html(
    label: str,
    val: object,
    _previous_val: object,
    tooltip: object,
    accent: str,
    _delta_comparisons: dict[str, str] | None,
    value_colors: Mapping[str, str] | None,
) -> str:
    """Build the HTML of a single KPI card."""
    if val is None:
        value_html = '<div class="kpi-card__value kpi-card__value--null">—</div>'
    else:
        # Temporarily hide percentage comparisons in KPI cards.
        # comparison = (delta_comparisons or {}).get(label, "less_is_good")
        value_html = (
            '<div class="kpi-card__value-row">'
            f'<div class="kpi-card__value">{_format_current_value(label, val)}</div>'
            # f"{_delta_html(val, previous_val, comparison)}"
            "</div>"
        )
    # Temporarily hide previous-period values in KPI cards.
    # previous_html = (
    #     f'<div class="kpi-card__previous">'
    #     f"<span>{_format_previous_value(label, previous_val)}</span>"
    #     f"{_prior_period_help_html()}</div>"
    #     if previous_val is not None
    #     else ""
    # )
    previous_html = ""
    tooltip_html = (
        '<span class="kpi-card__tooltip" role="button" tabindex="0" '
        f'aria-label="{_kpi_tooltip_aria_label(tooltip)}">'
        '<span class="kpi-card__tooltip-icon">i</span>'
        '<span class="kpi-card__tooltip-text">'
        f"{_kpi_tooltip_content_html(tooltip)}</span>"
        "</span>"
        if tooltip
        else ""
    )
    value_color = (value_colors or {}).get(label, "#1a2740")
    return (
        f'<div class="kpi-card" style="--kpi-accent:{accent};'
        f'--kpi-value-color:{escape(value_color, quote=True)};">'
        '<div class="kpi-card__label-row">'
        f'<div class="kpi-card__label">{_kpi_label_html(label)}</div>'
        f"{tooltip_html}</div>"
        f"{value_html}{previous_html}</div>"
    )


def _box_grid_html(
    boxes: Sequence[
        tuple[str, object]
        | tuple[str, object, object]
        | tuple[str, object, object, str | None]
    ],
    accent: str,
    delta_comparisons: dict[str, str] | None,
    value_colors: Mapping[str, str] | None = None,
    groups: Sequence[str | None] | None = None,
    grid_class: str = "",
) -> str:
    """Build a responsive CSS grid of KPI cards."""
    cards = [
        _card_html(
            item[0],
            item[1],
            item[2] if len(item) >= 3 else None,
            item[3] if len(item) == 4 else None,
            accent,
            delta_comparisons,
            value_colors,
        )
        for item in boxes
    ]
    if groups is None:
        return f'<div class="kpi-grid {grid_class}">{"".join(cards)}</div>'
    if len(groups) != len(cards):
        raise ValueError("KPI card groups must match the number of cards")

    grouped_cards: dict[str, tuple[list[str], bool]] = {}
    for index, (card, group) in enumerate(zip(cards, groups)):
        # Ungrouped cards remain individual grid items.
        key = group or f"card-{index}"
        grouped_cards.setdefault(key, ([], group is None))[0].append(card)
    stacks = "".join(
        f'<div class="kpi-card-stack'
        f'{" kpi-card-stack--standalone" if standalone else " kpi-card-stack--group"}">'
        f'{"".join(stack)}</div>'
        for stack, standalone in grouped_cards.values()
    )
    return f'<div class="kpi-grid kpi-grid--grouped {grid_class}">{stacks}</div>'


# pylint: disable=too-many-arguments,too-many-positional-arguments
def render_box_grid(
    boxes: Sequence[
        tuple[str, object]
        | tuple[str, object, object]
        | tuple[str, object, object, str | None]
    ],
    per_row: int = 3,
    row_gap: int = 12,
    accent: str = "#3b82f6",
    delta_comparisons: dict[str, str] | None = None,
    value_colors: Mapping[str, str] | None = None,
) -> None:
    """Render KPI boxes in a responsive card grid.

    Args:
        boxes: Prepared list of label/value tuples.
        per_row: Retained for compatibility; the responsive grid chooses columns.
        row_gap: Retained for compatibility; CSS controls the grid gap.
        accent: Left-border accent colour for the cards.
        delta_comparisons: Mapping of metric labels to comparison semantics. Values
            are ``"more_is_good"``, ``"less_is_good"``, or ``"neutral"``.
        value_colors: Optional mapping of metric labels to KPI value text colours.

    Returns:
        Streamlit markup is written directly to the page.
    """
    del per_row, row_gap
    _ensure_kpi_css()
    st.markdown(
        _box_grid_html(boxes, accent, delta_comparisons, value_colors),
        unsafe_allow_html=True,
    )


# pylint: disable=too-many-arguments,too-many-positional-arguments
def render_box_section(
    title: str,
    boxes: Sequence[
        tuple[str, object]
        | tuple[str, object, object]
        | tuple[str, object, object, str | None]
    ],
    accent: str = "#3b82f6",
    icon: str = "●",
    delta_comparisons: dict[str, str] | None = None,
    value_colors: Mapping[str, str] | None = None,
    grid_class: str = "",
) -> None:
    """Render KPI cards inside a standard Reporting-style section panel."""
    _ensure_kpi_css()
    icon_bg = accent + "22"
    box_grid_html = _box_grid_html(
        boxes,
        accent,
        delta_comparisons,
        value_colors,
        grid_class=grid_class,
    )
    st.markdown(
        '<div class="kpi-sections">'
        '<section class="kpi-section">'
        '<div class="kpi-section-header">'
        f'<div class="kpi-section-icon" style="background:{icon_bg};">'
        f"{escape(icon)}</div>"
        f'<p class="kpi-section-title">{escape(title)}</p></div>'
        f"{box_grid_html}"
        "</section></div>",
        unsafe_allow_html=True,
    )


def _summary_sections_html(section_blocks: list[tuple[str, str]]) -> str:
    """Arrange network KPI sections beside each other and all others below.

    The reporting-data section anchors the primary column.  The grid-operator
    section occupies the adjacent column, while every other KPI section follows
    below the reporting-data section in the primary column.
    """
    reporting_title = "Netzkennzahlen - Reporting Daten"
    operator_title = "Netzkennzahlen - Netzbetreiber"
    section_by_title = dict(section_blocks)
    reporting_section = section_by_title.pop(reporting_title, None)
    operator_section = section_by_title.pop(operator_title, None)

    if reporting_section is None or operator_section is None:
        return f'<div class="kpi-sections">{"".join(block for _, block in section_blocks)}</div>'

    primary_sections = "".join((reporting_section, *section_by_title.values()))
    return (
        '<div class="kpi-sections kpi-summary-layout">'
        f'<div class="kpi-summary-layout__primary">{primary_sections}</div>'
        f'<div class="kpi-summary-layout__operator">{operator_section}</div>'
        "</div>"
    )


def _section_data_warning_html(warning: str) -> str:
    """Render a catalogue warning with a prominent heading and preserved lines."""
    heading, separator, body = warning.strip().partition("\n\n")
    safe_heading = escape(" ".join(heading.split()))
    body_blocks: list[str] = []
    if separator:
        for block in body.split("\n\n"):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if lines and lines[0] == "Mögliche Gründe:":
                reasons: list[str] = []
                for line in lines[1:]:
                    if line.startswith(("–", "-")):
                        reasons.append(line[1:].strip())
                    elif reasons:
                        reasons[-1] += f" {line}"
                reason_items = "".join(
                    f"<li>{escape(reason)}</li>" for reason in reasons
                )
                body_blocks.append(
                    '<div class="kpi-section-data-warning__body">'
                    f"{escape(lines[0])}</div>"
                    f'<ul class="kpi-section-data-warning__reasons">{reason_items}</ul>'
                )
            elif lines:
                body_blocks.append(
                    '<div class="kpi-section-data-warning__body">'
                    f'{escape(" ".join(lines))}</div>'
                )
    body_html = "".join(body_blocks)
    return (
        '<div class="kpi-section-data-warning" role="status">'
        '<span class="kpi-section-data-warning__icon" aria-hidden="true">⚠</span>'
        '<div class="kpi-section-data-warning__content">'
        f'<strong class="kpi-section-data-warning__title">{safe_heading}</strong>'
        f"{body_html}</div></div>"
    )


# pylint: disable=too-many-locals
def render_summary_boxes(
    metrics: dict[str, Any],
    component_types: Iterable[str] | None = None,
    microgrid_id: int | None = None,
    previous_metrics: dict[str, Any] | None = None,
    skipped_dso_market_location_ids: tuple[str, ...] = (),
    dso_data_warning: str | None = None,
) -> None:
    """Render overview metrics grouped into styled subsections.

    Args:
        metrics: Metrics dictionary containing aggregated KPI values.
        component_types: Optional iterable of component type identifiers present
            in the microgrid (e.g., ``{"pv", "chp"}``).
        microgrid_id: Optional microgrid identifier used for microgrid-specific
            KPI cards.
        previous_metrics: Optional metrics for the immediately preceding period,
            used to render previous values and percentage deltas.
        skipped_dso_market_location_ids: MaLo IDs omitted because the Market
            Metering API does not recognize them.
        dso_data_warning: Warning shown instead of grid-operator KPI cards when
            DSO data does not cover the complete selected period.

    Returns:
        Streamlit components are rendered directly.
    """
    if not metrics and not dso_data_warning:
        st.info("Keine Übersichtskennzahlen verfügbar.")
        return

    _ensure_kpi_css()
    component_types_provided = component_types is not None
    component_type_set = set(component_types or [])

    # st.markdown(
    #     """
    #     <div class="metrics-heading">
    #         <h2>Leistungskennzahlen</h2>
    #         <div class="metrics-heading__line"></div>
    #     </div>
    #     """,
    #     unsafe_allow_html=True,
    # )

    section_blocks: list[tuple[str, str]] = []
    for section in SECTION_SPECS:
        title = section["title"]
        is_dso_warning_section = (
            title == "Netzkennzahlen - Netzbetreiber" and dso_data_warning is not None
        )
        required_any_metric_keys = section.get("required_any_metric_keys")
        if (
            not is_dso_warning_section
            and required_any_metric_keys
            and not required_any_metric_keys.intersection(metrics)
        ):
            continue
        accent = KPI_SECTION_ACCENTS.get(title, "#3b82f6")
        icon = _SECTION_ICONS.get(title, "●")
        icon_bg = accent + "22"  # ~13% opacity hex approximation
        if is_dso_warning_section:
            assert dso_data_warning is not None
            section_blocks.append(
                (
                    title,
                    '<section class="kpi-section">'
                    '<div class="kpi-section-header">'
                    f'<div class="kpi-section-icon" style="background:{icon_bg};">'
                    f"{icon}</div>"
                    f'<p class="kpi-section-title">{title}</p></div>'
                    f"{_section_data_warning_html(dso_data_warning)}"
                    "</section>",
                )
            )
            continue
        box_specs = _filter_section_box_specs(
            section,
            component_type_set,
            component_types_provided,
            microgrid_id,
        )
        box_specs = _filter_available_optional_metric_specs(box_specs, metrics)
        if not box_specs:
            continue

        warning = section.get("warning")
        warning_icon = "⚠"
        if (
            title == "Netzkennzahlen - Netzbetreiber"
            and skipped_dso_market_location_ids
        ):
            warning = (
                "Netzbetreiber-Daten wurden für folgende MaLo-IDs nicht geladen: "
                f"{', '.join(skipped_dso_market_location_ids)}"
            )
            warning_icon = "⚠"
        warning_html = (
            f'<span class="kpi-section-warning" role="button" tabindex="0" '
            f'aria-label="{warning}">'
            f'<span class="kpi-section-warning__icon">{warning_icon}</span>'
            f'<span class="kpi-section-warning__tooltip">{warning}</span>'
            "</span>"
            if warning
            else ""
        )
        boxes = _materialize_boxes(box_specs, metrics, previous_metrics)
        groups = [spec.get("group") for spec in box_specs]
        grid_class = (
            "kpi-grid--operator" if title == "Netzkennzahlen - Netzbetreiber" else ""
        )
        box_grid_html = _box_grid_html(
            boxes,
            accent,
            _DELTA_COMPARISONS,
            groups=groups,
            grid_class=grid_class,
        )
        section_blocks.append(
            (
                title,
                '<section class="kpi-section">'
                '<div class="kpi-section-header">'
                f'<div class="kpi-section-icon" style="background:{icon_bg};">{icon}</div>'
                f'<p class="kpi-section-title">{title}</p>'
                f"{warning_html}</div>"
                f"{box_grid_html}"
                "</section>",
            )
        )

    st.markdown(
        _summary_sections_html(section_blocks),
        unsafe_allow_html=True,
    )
