# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""UI helpers for rendering plots and styled cards."""

import plotly.graph_objects as go
import streamlit as st
from matplotlib.figure import Figure


def _ensure_plot_card_css() -> None:
    """Inject card styling CSS once per session.

    Returns:
        Streamlit styles are injected directly.
    """
    if st.session_state.get("_plot_card_css_injected"):
        return
    st.markdown(
        """
        <style>
        .plot-card {
            background: #ffffff;
            border: 1px solid #d9e1ec;
            border-radius: 12px;
            padding: 14px 16px 10px;
            box-shadow: 0 10px 20px rgba(15, 41, 74, 0.05);
            margin-bottom: 16px;
        }
        .plot-card__title {
            font-size: 15px;
            font-weight: 700;
            color: #1a2940;
            margin-bottom: 10px;
            letter-spacing: 0.01em;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_plot_card_css_injected"] = True


def render_plot_card(title: str, fig: object) -> None:
    """Render a plot inside a styled card.

    Args:
        title: Title displayed above the plot.
        fig: Plotly or Matplotlib figure to render.

    Returns:
        Streamlit components are rendered directly.
    """
    _ensure_plot_card_css()

    with st.container():
        st.markdown('<div class="plot-card">', unsafe_allow_html=True)
        st.markdown(
            f'<div class="plot-card__title">{title}</div>', unsafe_allow_html=True
        )

        # Check the figure type to use the correct Streamlit component
        if isinstance(fig, go.Figure):
            st.plotly_chart(fig, width="stretch")
        elif isinstance(fig, Figure):
            st.pyplot(fig)
        else:
            st.warning("Unsupported figure type.")
        st.markdown("</div>", unsafe_allow_html=True)
