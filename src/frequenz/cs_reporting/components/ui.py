# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""UI helpers for rendering plots and styled cards."""

from collections.abc import Callable
from typing import Literal, TypeAlias

import plotly.graph_objects as go
import streamlit as st
from matplotlib.figure import Figure

from frequenz.cs_reporting.ui_resources import inject_style

StreamlitHeight: TypeAlias = Literal["stretch", "content"] | int

_PLOT_CARD_CHROME_HEIGHT = 92
_PLOTLY_COMPONENT_VERTICAL_PADDING = 120


def _ensure_plot_card_css() -> None:
    """Inject card styling CSS for the current Streamlit run."""
    inject_style("plot_card.css")


def _plotly_component_height(fig: go.Figure) -> StreamlitHeight:
    """Return a Streamlit component height that avoids clipping Plotly controls."""
    figure_height = fig.layout.height
    if isinstance(figure_height, int | float):
        return int(figure_height) + _PLOTLY_COMPONENT_VERTICAL_PADDING

    return "content"


def _plot_card_height(fig: object) -> StreamlitHeight:
    """Return the outer card height needed for the rendered plot."""
    if isinstance(fig, go.Figure):
        plot_height = _plotly_component_height(fig)
        if isinstance(plot_height, int):
            return plot_height + _PLOT_CARD_CHROME_HEIGHT

    return "content"


def render_plot_card(
    title: str,
    fig: object,
    header_control: Callable[[], None] | None = None,
    key: str | None = None,
) -> None:
    """Render a plot inside a professional styled card.

    Args:
        title: Title displayed in the card header.
        fig: Plotly or Matplotlib figure to render.
        header_control: Optional Streamlit control rendered at the right side of
            the card header.
        key: Optional key used to style cards that include header controls.

    Returns:
        Streamlit components are rendered directly.
    """
    _ensure_plot_card_css()
    card_key = f"{key or title.lower().replace(' ', '_')}_plot_card"
    header_key = f"{key or title.lower().replace(' ', '_')}_plot_header"

    if header_control is not None:
        with st.container(key=card_key, height=_plot_card_height(fig)):
            with st.container(
                key=header_key,
                horizontal=True,
                vertical_alignment="center",
                horizontal_alignment="distribute",
            ):
                st.markdown(
                    f"""
                    <div class="plot-card__native-title-wrap">
                        <div class="plot-card__header-dot"></div>
                        <p class="plot-card__title">{title}</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                header_control()

            if isinstance(fig, go.Figure):
                st.plotly_chart(
                    fig,
                    width="stretch",
                    height=_plotly_component_height(fig),
                )
            elif isinstance(fig, Figure):
                st.pyplot(fig)
            else:
                st.warning("Nicht unterstützter Figurtyp.")
        return

    with st.container(key=card_key, height=_plot_card_height(fig)):
        st.markdown(
            f"""
            <div class="plot-card__header">
                <div class="plot-card__header-dot"></div>
                <p class="plot-card__title">{title}</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if isinstance(fig, go.Figure):
            st.plotly_chart(
                fig,
                width="stretch",
                height=_plotly_component_height(fig),
            )
        elif isinstance(fig, Figure):
            st.pyplot(fig)
        else:
            st.warning("Nicht unterstützter Figurtyp.")
