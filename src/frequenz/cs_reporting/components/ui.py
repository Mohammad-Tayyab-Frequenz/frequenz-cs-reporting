# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""UI helpers for rendering plots and styled cards."""

import plotly.graph_objects as go
import streamlit as st
from matplotlib.figure import Figure

_PLOT_CARD_CSS = """
<style>
/* ── Plot card container ── */
.plot-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 2px 12px rgba(15, 41, 74, 0.06);
    margin-bottom: 20px;
    transition: box-shadow 0.2s;
}
.plot-card:hover {
    box-shadow: 0 6px 24px rgba(15, 41, 74, 0.10);
}

/* ── Card header strip ── */
.plot-card__header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 13px 18px;
    background: linear-gradient(90deg, #f8fafc 0%, #f1f5fb 100%);
    border-bottom: 1px solid #e2e8f0;
}
.plot-card__header-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #3b82f6;
    flex-shrink: 0;
}
.plot-card__title {
    font-size: 0.82rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: #374151;
    margin: 0;
    flex: 1;
}

/* ── Card body ── */
.plot-card__body {
    padding: 6px 4px 2px;
}
</style>
"""


def _ensure_plot_card_css() -> None:
    """Inject card styling CSS once per session."""
    if st.session_state.get("_plot_card_css_injected"):
        return
    st.markdown(_PLOT_CARD_CSS, unsafe_allow_html=True)
    st.session_state["_plot_card_css_injected"] = True


def render_plot_card(title: str, fig: object) -> None:
    """Render a plot inside a professional styled card.

    Args:
        title: Title displayed in the card header.
        fig: Plotly or Matplotlib figure to render.

    Returns:
        Streamlit components are rendered directly.
    """
    _ensure_plot_card_css()

    with st.container():
        st.markdown(
            f"""
            <div class="plot-card">
                <div class="plot-card__header">
                    <div class="plot-card__header-dot"></div>
                    <p class="plot-card__title">{title}</p>
                </div>
                <div class="plot-card__body">
            """,
            unsafe_allow_html=True,
        )

        if isinstance(fig, go.Figure):
            st.plotly_chart(fig, width="stretch")
        elif isinstance(fig, Figure):
            st.pyplot(fig)
        else:
            st.warning("Unsupported figure type.")

        st.markdown("</div></div>", unsafe_allow_html=True)
