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
        """Render the selected page."""

    def discover_library_pages(self) -> list[PageSpec]:
        """Discover lightweight navigation page specifications."""


def _load_app() -> _AppModule:
    """Load the root-level Streamlit app regardless of pytest's import mode."""
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    spec = importlib.util.spec_from_file_location("reporting_app", app_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load Streamlit app from {app_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return cast(_AppModule, module)


def test_render_selected_page_invokes_page_renderer() -> None:
    """The selected page renderer is invoked directly."""
    rendered: list[str] = []
    page = PageSpec(
        key="test",
        title="Test",
        icon="",
        order=0,
        render=lambda: rendered.append("rendered"),
    )

    _load_app().render_selected_page(page)

    assert rendered == ["rendered"]


def test_page_discovery_uses_lightweight_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Navigation metadata is available without importing each page module."""
    monkeypatch.setattr(st, "fragment", lambda function: function)

    pages = _load_app().discover_library_pages()

    assert [page.key for page in pages] == [
        "home",
        "reporting_dashboard",
        "solar",
    ]
