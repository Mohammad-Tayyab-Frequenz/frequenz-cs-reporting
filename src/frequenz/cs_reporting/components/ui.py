# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""UI helpers for rendering plots and styled cards."""

import plotly.graph_objects as go
import streamlit as st
from matplotlib.figure import Figure

from frequenz.cs_reporting.ui_resources import inject_style


def _ensure_plot_card_css() -> None:
    """Inject card styling CSS for the current Streamlit run."""
    inject_style("plot_card.css")


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
