# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Frequenz CS Reporting App Pages."""

from __future__ import annotations

import importlib
from collections.abc import Callable

from frequenz.cs_reporting.rep_cs_core.page_spec import PageSpec
from frequenz.cs_reporting.utils.timing import log_duration


def _lazy_render(module_name: str, expected_key: str) -> Callable[[], None]:
    """Create a renderer that imports its page module only when selected."""

    def render() -> None:
        with log_duration(f"page.{expected_key}.import_module"):
            module = importlib.import_module(f"{__name__}.{module_name}")
        page = getattr(module, "PAGE", None)
        if not isinstance(page, PageSpec) or page.key != expected_key:
            raise RuntimeError(
                f"Page module {module.__name__!r} does not expose the expected "
                f"PAGE specification {expected_key!r}"
            )
        page.render()

    return render


PAGE_MANIFEST: dict[str, PageSpec] = {
    "home": PageSpec(
        key="home",
        title="Übersicht",
        icon="",
        order=0,
        render=_lazy_render("home", "home"),
    ),
    "reporting": PageSpec(
        key="reporting_dashboard",
        title="Reporting",
        icon="",
        order=1,
        render=_lazy_render("reporting", "reporting_dashboard"),
    ),
    "solar": PageSpec(
        key="solar",
        title="Solar-Monitoring",
        icon="",
        order=2,
        render=_lazy_render("solar", "solar"),
    ),
}

__all__ = ["PAGE_MANIFEST"]
