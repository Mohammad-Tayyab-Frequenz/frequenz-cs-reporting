# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for application-level Streamlit rendering."""

import pytest
import streamlit as st

from frequenz.cs_reporting import ui_resources


class _PageSlot:
    """Record when the replaceable main-page container is entered."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def container(self) -> "_PageSlot":
        """Return this object as a context manager."""
        return self

    def __enter__(self) -> "_PageSlot":
        self._events.append("container-entered")
        return self

    def __exit__(self, *_args: object) -> None:
        self._events.append("container-exited")


def test_render_page_clears_previous_page_before_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The old page is replaced before potentially slow rendering begins."""
    events: list[str] = []

    def fake_empty() -> _PageSlot:
        events.append("placeholder-created")
        return _PageSlot(events)

    def render() -> None:
        events.append("page-rendered")

    monkeypatch.setattr(st, "empty", fake_empty)

    ui_resources.render_page(render)

    assert events == [
        "placeholder-created",
        "container-entered",
        "page-rendered",
        "container-exited",
    ]
