# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for application-level Streamlit rendering."""

import importlib.util
from pathlib import Path
from typing import Protocol, cast

import pytest
import streamlit as st

from frequenz.cs_reporting.rep_cs_core.page_spec import PageSpec


class _AppModule(Protocol):
    """Typed interface to the dynamically loaded Streamlit app."""

    def render_selected_page(self, page: PageSpec) -> None:
        """Render the selected page fragment."""


def _load_app() -> _AppModule:
    """Load the root-level Streamlit app regardless of pytest's import mode."""
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("reporting_app", app_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Streamlit app from {app_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(_AppModule, module)


def test_render_selected_page_invokes_page_renderer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The selected page is rendered through the fragment entry point."""
    rendered: list[str] = []
    fragment_functions: list[str] = []

    def fake_fragment(function: object) -> object:
        fragment_functions.append(getattr(function, "__name__", ""))
        return function

    monkeypatch.setattr(st, "fragment", fake_fragment)
    page = PageSpec(
        key="test",
        title="Test",
        icon="",
        order=0,
        render=lambda: rendered.append("rendered"),
    )

    _load_app().render_selected_page(page)

    assert "render_selected_page" in fragment_functions
    assert rendered == ["rendered"]
