# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Home page introducing the Frequenz reporting suite."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from frequenz.cs_reporting.rep_cs_core.page_spec import PageSpec
from frequenz.cs_reporting.ui_resources import (
    inject_style,
    load_template,
    render_template,
)

ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
BACKGROUND_PATH = ASSETS_DIR / "neustrom_background.png"
LOGO_PATH = ASSETS_DIR / "neustrom_logo.png"

# ── Static content data ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Stat:
    value: str
    label: str


@dataclass(frozen=True)
class _FeatureCard:
    color_class: str  # e.g. "home-card--blue"
    icon: str  # HTML entity or character
    title: str
    description: str
    features: tuple[str, ...]


_STATS: tuple[_Stat, ...] = (
    _Stat("Echtzeit", "Datenaktualisierung"),
    _Stat("5+", "Komponententypen"),
    _Stat("Multi-Standort", "Portfolioansicht"),
    _Stat("CSV", "Exportbereit"),
)

_FEATURE_CARDS: tuple[_FeatureCard, ...] = (
    _FeatureCard(
        color_class="home-card--blue",
        icon="&#9889;",
        title="Reporting-Dashboard",
        description=(
            "Leistungsflüsse auf Portfolioebene, Verbrauchsbilanzen "
            "und detaillierte KPI-Analysen über alle Microgrid-Komponenten."
        ),
        features=(
            "KPIs für Netzbezug und Einspeisung",
            "Analysen für PV, Batterie, KWK &amp; Wind",
            "Autarkie- und Eigenverbrauchsquoten",
            "Interaktive Zeitreihen-Plots",
        ),
    ),
    _FeatureCard(
        color_class="home-card--green",
        icon="&#9728;",
        title="Solar-Monitoring",
        description=(
            "Wartungsorientierte Solar-Workflow-Prüfungen mit "
            "Baseline-Modellvergleich und rollierenden Performance-Ansichten."
        ),
        features=(
            "Diagnose für Wechselrichter &amp; Zähler",
            "Benchmarking von Baseline-Modellen",
            "Rollierendes Performance-Fenster (5-60 Tage)",
            "Berichtsausgabe auf Deutsch &amp; Englisch",
        ),
    ),
    _FeatureCard(
        color_class="home-card--purple",
        icon="&#8595;",
        title="Datenexport",
        description=(
            "Standardisierte Tabellen aus allen Reporting-Bereichen "
            "für interne Pipelines und Kundenberichte herunterladen."
        ),
        features=(
            "Zeitreihen pro Komponente",
            "Aggregierte Energiezusammenfassungen",
            "Konfigurierbare Auflösung &amp; Zeitzone",
            "CSV-kompatibles Format",
        ),
    ),
)

# ── Navigation ────────────────────────────────────────────────────────────────


def _navigate_to(page_key: str, section: str | None = None) -> None:
    """Navigate to a target page using the app's query-param routing."""
    st.session_state["selected_page"] = page_key
    st.session_state["_nav_target"] = page_key
    st.query_params.page = page_key
    if section:
        st.query_params.section = section
    elif "section" in st.query_params:
        del st.query_params["section"]
    st.rerun()


# ── Asset helpers ─────────────────────────────────────────────────────────────


def _b64_image(image_path: Path) -> str | None:
    """Return base64-encoded image string, or None if the file is missing."""
    if not image_path.exists():
        return None
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


# ── HTML builders ─────────────────────────────────────────────────────────────
# Each function returns a self-contained HTML string for one page section.
# Keeping markup out of render() makes each piece independently readable
# and easy to update without touching unrelated sections.


def _logo_html(logo_b64: str) -> str:
    return render_template("home_logo.html", logo_b64=logo_b64)


def _hero_html() -> str:
    return load_template("home_hero.html")


def _stats_html(stats: tuple[_Stat, ...]) -> str:
    items = "".join(
        render_template("home_stat_item.html", value=s.value, label=s.label)
        for s in stats
    )
    return render_template("home_stats.html", items=items)


def _feature_card_html(card: _FeatureCard) -> str:
    feature_items = "".join(f"<li>{f}</li>" for f in card.features)
    return render_template(
        "home_feature_item.html",
        color_class=card.color_class,
        icon=card.icon,
        title=card.title,
        description=card.description,
        feature_items=feature_items,
    )


def _feature_grid_html(cards: tuple[_FeatureCard, ...]) -> str:
    card_blocks = "".join(_feature_card_html(c) for c in cards)
    return render_template("home_feature_grid.html", cards=card_blocks)


def _footer_html() -> str:
    return load_template("home_footer.html")


# ── Style injection ───────────────────────────────────────────────────────────


def _inject_styles(bg_b64: str | None) -> None:
    """Inject page CSS, substituting the background image when available."""
    if bg_b64:
        bg_css = (
            f"background-image: linear-gradient("
            f"180deg, rgba(241,246,253,0.80), rgba(243,246,251,0.85)"
            f'), url("data:image/png;base64,{bg_b64}");'
            "background-size: cover;"
            "background-position: center top;"
            "background-attachment: fixed;"
            "background-color: #f3f6fb;"
        )
    else:
        bg_css = "background-color: #f3f6fb;"

    inject_style("home.css", bg_css=bg_css)


# ── Page entry point ──────────────────────────────────────────────────────────


def render() -> None:
    """Render the home page."""
    bg_b64 = _b64_image(BACKGROUND_PATH)
    logo_b64 = _b64_image(LOGO_PATH)

    _inject_styles(bg_b64)

    if logo_b64:
        st.markdown(_logo_html(logo_b64), unsafe_allow_html=True)

    st.markdown(_hero_html(), unsafe_allow_html=True)
    st.markdown(_stats_html(_STATS), unsafe_allow_html=True)
    st.markdown(_feature_grid_html(_FEATURE_CARDS), unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Reporting-Dashboard öffnen", use_container_width=True):
            _navigate_to("reporting_dashboard")
    with col2:
        if st.button("Solar-Monitoring öffnen", use_container_width=True):
            _navigate_to("solar")
    with col3:
        if st.button("Datenexport öffnen", use_container_width=True):
            _navigate_to("reporting_dashboard", section="data-export")

    st.markdown(_footer_html(), unsafe_allow_html=True)


PAGE = PageSpec(
    key="home",
    title="Übersicht",
    icon="",
    order=0,
    render=render,
)
