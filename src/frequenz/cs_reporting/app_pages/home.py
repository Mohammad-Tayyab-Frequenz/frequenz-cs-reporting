# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Home page introducing the Frequenz reporting suite."""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

from frequenz.cs_reporting.rep_cs_core.page_spec import PageSpec

PACKAGE_DIR = Path(__file__).resolve().parents[1]
ASSETS_DIR = PACKAGE_DIR / "assets"
BACKGROUND_PATH = ASSETS_DIR / "neustrom_background.png"
LOGO_PATH = ASSETS_DIR / "neustrom_logo.png"


def _navigate_to(page_key: str) -> None:
    """Navigate to a target page using the app's query-param routing."""
    st.session_state["selected_page"] = page_key
    st.session_state["_nav_target"] = page_key
    st.query_params.page = page_key
    st.rerun()


def _b64_image(image_path: Path) -> str | None:
    """Return base64-encoded image string or None if file missing."""
    if not image_path.exists():
        return None
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


def _inject_styles(bg_b64: str | None) -> None:
    """Inject global page styles including optional background image."""
    bg_css = (
        f"""
        background-image:
            linear-gradient(180deg, rgba(241,246,253,0.80), rgba(243,246,251,0.85)),
            url("data:image/png;base64,{bg_b64}");
        background-size: cover;
        background-position: center top;
        background-attachment: fixed;
        background-color: #f3f6fb;
        """
        if bg_b64
        else "background-color: #f3f6fb;"
    )

    st.markdown(
        f"""
        <style>
        /* ── Page background ── */
        [data-testid="stAppViewContainer"] {{
            {bg_css}
            min-height: 100vh;
        }}
        [data-testid="stHeader"] {{ background: transparent !important; }}

        /* ── Design tokens ── */
        :root {{
            --clr-bg-card:    #ffffff;
            --clr-border:     #d9e1ec;
            --clr-accent:     #1e4f87;
            --clr-accent-lt:  #2563eb;
            --clr-text-h:     #0f2233;
            --clr-text-body:  #46566e;
            --clr-text-muted: #7a8fa8;
            --radius-lg:      14px;
            --radius-md:      10px;
            --shadow-card:    0 4px 18px rgba(17,43,79,0.08);
        }}

        /* ── Top badge ── */
        .home-badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            border-radius: 999px;
            padding: 4px 14px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #1d4ed8;
            margin-bottom: 20px;
        }}

        /* ── Hero block ── */
        .home-hero {{
            padding: 36px 0 28px;
        }}
        .home-hero h1 {{
            margin: 0 0 16px;
            font-size: clamp(1.9rem, 3vw, 2.7rem);
            font-weight: 700;
            line-height: 1.18;
            color: var(--clr-text-h);
            letter-spacing: -0.02em;
        }}
        .home-hero h1 span {{
            color: #1d4ed8;
        }}
        .home-hero p {{
            margin: 0;
            font-size: 1.02rem;
            line-height: 1.7;
            color: var(--clr-text-body);
            max-width: 680px;
        }}

        /* ── Divider ── */
        .home-divider {{
            border: 0;
            border-top: 1px solid var(--clr-border);
            margin: 32px 0;
        }}

        /* ── Stats row ── */
        .home-stats {{
            display: flex;
            gap: 32px;
            flex-wrap: wrap;
            margin-bottom: 36px;
        }}
        .home-stat {{
            display: flex;
            flex-direction: column;
        }}
        .home-stat__value {{
            font-size: 1.55rem;
            font-weight: 700;
            color: var(--clr-accent);
            line-height: 1;
        }}
        .home-stat__label {{
            font-size: 0.75rem;
            color: var(--clr-text-muted);
            margin-top: 4px;
            letter-spacing: 0.04em;
            text-transform: uppercase;
        }}

        /* ── Feature cards grid ── */
        .home-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
            margin-bottom: 36px;
        }}
        .home-card {{
            position: relative;
            background: var(--clr-bg-card);
            border: 1px solid var(--clr-border);
            border-radius: var(--radius-lg);
            padding: 24px 24px 20px;
            box-shadow: var(--shadow-card);
            transition: box-shadow 0.2s, border-color 0.2s;
            overflow: hidden;
        }}
        .home-card:hover {{
            box-shadow: 0 8px 28px rgba(17,43,79,0.13);
            border-color: #b8cbe8;
        }}
        .home-card::before {{
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 3px;
            border-radius: var(--radius-lg) var(--radius-lg) 0 0;
        }}
        .home-card--blue::before  {{ background: linear-gradient(90deg, #1d4ed8, #3b82f6); }}
        .home-card--green::before {{ background: linear-gradient(90deg, #059669, #10b981); }}
        .home-card--purple::before{{ background: linear-gradient(90deg, #7c3aed, #8b5cf6); }}

        .home-card__icon {{
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            margin-bottom: 14px;
        }}
        .home-card--blue   .home-card__icon {{ background: #eff6ff; }}
        .home-card--green  .home-card__icon {{ background: #ecfdf5; }}
        .home-card--purple .home-card__icon {{ background: #f5f3ff; }}

        .home-card h3 {{
            margin: 0 0 8px;
            font-size: 0.95rem;
            font-weight: 700;
            color: var(--clr-text-h);
            letter-spacing: 0.01em;
        }}
        .home-card p {{
            margin: 0 0 16px;
            font-size: 0.875rem;
            color: var(--clr-text-body);
            line-height: 1.6;
        }}
        .home-card__features {{
            list-style: none;
            margin: 0;
            padding: 0;
            border-top: 1px solid #eef1f7;
            padding-top: 14px;
        }}
        .home-card__features li {{
            font-size: 0.8rem;
            color: var(--clr-text-muted);
            padding: 3px 0;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .home-card__features li::before {{
            content: "✓";
            color: #2563eb;
            font-weight: 700;
            font-size: 0.75rem;
        }}

        /* ── CTA buttons — keep Streamlit default style, just round them ── */
        div[data-testid="stHorizontalBlock"] .stButton > button {{
            border-radius: 8px !important;
            font-weight: 600 !important;
            font-size: 0.875rem !important;
            padding: 10px 20px !important;
            transition: all 0.2s !important;
        }}

        /* ── Footer ── */
        .home-footer {{
            margin-top: 44px;
            padding-top: 20px;
            border-top: 1px solid var(--clr-border);
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .home-footer p {{
            margin: 0;
            font-size: 0.78rem;
            color: var(--clr-text-muted);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render() -> None:
    """Render the landing page with a professional hero and feature cards."""
    bg_b64 = _b64_image(BACKGROUND_PATH)
    logo_b64 = _b64_image(LOGO_PATH)
    _inject_styles(bg_b64)

    # ── Logo ──────────────────────────────────────────────────────────────
    if logo_b64:
        st.markdown(
            f'<img src="data:image/png;base64,{logo_b64}" '
            'style="height:38px;margin-bottom:32px;display:block;" alt="Frequenz logo">',
            unsafe_allow_html=True,
        )

    # ── Hero ──────────────────────────────────────────────────────────────
    st.markdown(
        """
        <div class="home-hero">
            <div class="home-badge">&#9679; Live Reporting Platform</div>
            <h1>Frequenz<br><span>Reporting Suite</span></h1>
            <p>
                Consolidated operational intelligence for distributed energy systems.
                Monitor portfolio performance, analyse solar generation, and export
                standardised reports — all in one unified platform.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Stats row ─────────────────────────────────────────────────────────
    st.markdown(
        """
        <div class="home-stats">
            <div class="home-stat">
                <span class="home-stat__value">Real-time</span>
                <span class="home-stat__label">Data Refresh</span>
            </div>
            <div class="home-stat">
                <span class="home-stat__value">5+</span>
                <span class="home-stat__label">Component Types</span>
            </div>
            <div class="home-stat">
                <span class="home-stat__value">Multi-site</span>
                <span class="home-stat__label">Portfolio View</span>
            </div>
            <div class="home-stat">
                <span class="home-stat__value">CSV</span>
                <span class="home-stat__label">Export Ready</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Feature cards ─────────────────────────────────────────────────────
    st.markdown(
        """<div class="home-grid">
<div class="home-card home-card--blue">
    <div class="home-card__icon">&#9889;</div>
    <h3>Reporting Dashboard</h3>
    <p>Portfolio-level power flows, consumption balances,
       and detailed KPI analytics across all microgrid components.</p>
    <ul class="home-card__features">
        <li>Grid import / export KPIs</li>
        <li>PV, Battery, CHP & Wind analytics</li>
        <li>Self-sufficiency &amp; self-consumption ratios</li>
        <li>Interactive time-series plots</li>
    </ul>
</div>
<div class="home-card home-card--green">
    <div class="home-card__icon">&#9728;</div>
    <h3>Solar Operations</h3>
    <p>Maintenance-oriented solar workflow checks with baseline
       model comparison and rolling performance views.</p>
    <ul class="home-card__features">
        <li>Inverter &amp; meter diagnostics</li>
        <li>Baseline model benchmarking</li>
        <li>Rolling performance window (5–60 days)</li>
        <li>German &amp; English report output</li>
    </ul>
</div>
<div class="home-card home-card--purple">
    <div class="home-card__icon">&#8595;</div>
    <h3>Data Export</h3>
    <p>Download standardised tables from each reporting section
       for use in internal pipelines and client deliverables.</p>
    <ul class="home-card__features">
        <li>Per-component time series</li>
        <li>Aggregated energy summaries</li>
        <li>Configurable resolution &amp; timezone</li>
        <li>CSV-compatible format</li>
    </ul>
</div>
</div>
        """,
        unsafe_allow_html=True,
    )

    # ── CTA buttons ───────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        if st.button("Open Reporting Dashboard", use_container_width=True):
            _navigate_to("reporting_dashboard")
    with col2:
        if st.button("Open Solar Operations", use_container_width=True):
            _navigate_to("solar")
    with col3:
        if st.button("Download Data Export", use_container_width=True):
            _navigate_to("reporting_dashboard")

    # ── Footer ────────────────────────────────────────────────────────────
    st.markdown(
        """
        <div class="home-footer">
            <p>© 2026 Frequenz Energy-as-a-Service GmbH &nbsp;·&nbsp; MIT License</p>
            <p>Built for daily monitoring &amp; decision support</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


PAGE = PageSpec(
    key="home",
    title="Overview",
    icon="",
    order=0,
    render=render,
)
