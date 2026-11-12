# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for warming the Assets API microgrid catalog off the render path."""

from __future__ import annotations

import threading

import pytest

from frequenz.cs_reporting.services import client_factory


def _run_warm_up(monkeypatch: pytest.MonkeyPatch, fake: object) -> None:
    monkeypatch.setattr(client_factory, "get_microgrid_names", fake)
    client_factory.warm_up_microgrid_catalog.clear()
    assert client_factory.warm_up_microgrid_catalog() is True
    for thread in threading.enumerate():
        if thread.name == "microgrid-catalog-warmup":
            thread.join(timeout=10)


def test_catalog_is_fetched_in_a_background_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalog call must not run on the calling (render) thread."""
    seen: list[str] = []

    def fake() -> dict[int, str | None]:
        seen.append(threading.current_thread().name)
        return {}

    _run_warm_up(monkeypatch, fake)

    assert seen == ["microgrid-catalog-warmup"]


def test_catalog_warm_up_failure_does_not_propagate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing credential or API outage must leave the app usable."""

    def fake() -> dict[int, str | None]:
        raise OSError("assets api unreachable")

    _run_warm_up(monkeypatch, fake)
