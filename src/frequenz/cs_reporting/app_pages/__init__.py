# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Frequenz CS Reporting App Pages."""

from __future__ import annotations

import importlib
import logging
import threading
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
        title="Startseite",
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
    "battery_optimization": PageSpec(
        key="battery_optimization",
        title="Batterie Reporting",
        icon="",
        order=2,
        render=_lazy_render("battery_optimization", "battery_optimization"),
    ),
    "solar": PageSpec(
        key="solar",
        title="Solar-Reporting",
        icon="",
        order=3,
        render=_lazy_render("solar", "solar"),
    ),
    "data_export": PageSpec(
        key="data_export",
        title="Datenexport",
        icon="",
        order=4,
        render=_lazy_render("data_export", "data_export"),
    ),
}


def preload_page_modules() -> threading.Thread:
    """Import every page module in a background thread.

    The first visit to a page otherwise pays its heavy imports (pandas, plotly,
    the reporting library) on the critical path.  Starting this while the home
    page renders hides that cost; Python's import locks make a concurrent
    on-demand import wait for the preload instead of importing twice.
    """

    def run() -> None:
        with log_duration("app.preload_page_modules"):
            for name in PAGE_MANIFEST:
                try:
                    importlib.import_module(f"{__name__}.{name}")
                except Exception:  # pylint: disable=broad-except
                    # The page re-raises it with context when it is opened.
                    logging.getLogger(__name__).exception(
                        "Preloading page module %r failed", name
                    )

    thread = threading.Thread(target=run, name="page-preload", daemon=True)
    thread.start()
    return thread


__all__ = ["PAGE_MANIFEST", "preload_page_modules"]
