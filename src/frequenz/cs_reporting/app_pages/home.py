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


def _navigate_to(page_key: str) -> None:
    """Navigate to a target page using the app's query-param routing."""
    st.session_state["selected_page"] = page_key
    st.query_params.page = page_key
    st.rerun()


def _set_page_bg(image_path: Path) -> None:
    """Set a base64-encoded background image for the page.

    Args:
        image_path: Path to the background image file.

    Returns:
        Streamlit styles are injected directly.
    """
    if not image_path.exists():
        st.warning(f"Background image not found: {image_path}")
        return

    b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
    st.markdown(
        f"""
        <style>
        [data-testid="stAppViewContainer"] {{
            background-image:
                linear-gradient(180deg, rgba(241,246,253,0.94), rgba(243,246,251,0.98)),
                url("data:image/png;base64,{b64}");
            background-size: cover;
            background-repeat: no-repeat;
            background-position: center top;
            background-attachment: fixed;
            background-color: #f3f6fb;
            min-height: 100vh;
        }}
        [data-testid="stHeader"] {{ background: transparent; }}

        .home-hero {{
            background: rgba(255, 255, 255, 0.93);
            border: 1px solid #d9e1ec;
            border-radius: 14px;
            box-shadow: 0 14px 30px rgba(17, 43, 79, 0.08);
            padding: 26px 30px;
            margin-bottom: 18px;
        }}

        .home-hero h1 {{
            margin: 0;
            font-size: clamp(1.6rem, 2vw, 2.2rem);
            color: #142033;
        }}

        .home-hero p {{
            margin: 10px 0 0;
            line-height: 1.6;
            color: #46566e;
            max-width: 960px;
        }}

        .home-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
            gap: 14px;
            margin-top: 14px;
        }}

        .home-panel {{
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid #d9e1ec;
            border-radius: 12px;
            padding: 16px 18px;
        }}

        .home-panel h3 {{
            margin: 0 0 8px;
            font-size: 1rem;
            color: #1e4f87;
        }}

        .home-panel p {{
            margin: 0;
            color: #4f5f76;
            font-size: 0.95rem;
            line-height: 1.5;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render() -> None:
    """Render the landing page with a welcome message and background.

    Returns:
        Streamlit components are rendered directly.
    """
    _set_page_bg(BACKGROUND_PATH)

    st.markdown(
        """
        <div class="home-hero">
            <h1>Frequenz Reporting Suite</h1>
            <p>
                Consolidated operational insights for energy systems, built for daily
                monitoring and decision support. Use the navigation on the left to access
                reporting and solar performance workflows.
            </p>
        </div>

        <div class="home-grid">
            <div class="home-panel">
                <h3>Reporting Dashboard</h3>
                <p>Review portfolio-level power flows, consumption balances, and detailed component analytics.</p>
            </div>
            <div class="home-panel">
                <h3>Solar Monitoring</h3>
                <p>Run maintenance-oriented solar workflow checks and compare baseline models.</p>
            </div>
            <div class="home-panel">
                <h3>Data Export</h3>
                <p>Download standardized tables directly from each section for internal reporting pipelines.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Open Reporting Dashboard", use_container_width=True):
            _navigate_to("reporting_dashboard")
    with col2:
        if st.button("Open Solar Operations", use_container_width=True):
            _navigate_to("solar")
    with col3:
        if st.button("Open Reporting Exports", use_container_width=True):
            _navigate_to("reporting_dashboard")


PAGE = PageSpec(
    key="home",
    title="Overview",
    icon="",
    order=0,
    render=render,
)
