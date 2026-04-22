# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Utilities for loading packaged HTML templates and CSS styles."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

import streamlit as st

_BASE_PACKAGE = "frequenz.cs_reporting"


@lru_cache(maxsize=None)
def load_template(template_name: str) -> str:
    """Load an HTML template from the package templates folder."""
    template_path = resources.files(_BASE_PACKAGE).joinpath("templates", template_name)
    return template_path.read_text(encoding="utf-8")


def render_template(template_name: str, **values: str) -> str:
    """Render an HTML template with string placeholder replacements."""
    return load_template(template_name).format(**values)


@lru_cache(maxsize=None)
def load_style(style_name: str) -> str:
    """Load a CSS stylesheet from the package styles folder."""
    style_path = resources.files(_BASE_PACKAGE).joinpath("styles", style_name)
    return style_path.read_text(encoding="utf-8")


def inject_style(style_name: str, **tokens: str) -> None:
    """Inject a packaged CSS stylesheet into the current Streamlit page.

    Tokens are replaced using ``__TOKEN_NAME__`` placeholders in the stylesheet.
    """
    style_text = load_style(style_name)
    for key, value in tokens.items():
        style_text = style_text.replace(f"__{key.upper()}__", value)

    st.markdown(f"<style>\n{style_text}\n</style>", unsafe_allow_html=True)
