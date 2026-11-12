# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests that every page is declared lazily in the page manifest."""

import importlib
import pkgutil
import sys

from frequenz.cs_reporting import app_pages


def test_every_page_module_has_a_matching_lazy_manifest_entry() -> None:
    """A page missing from the manifest is imported eagerly at app start."""
    for info in pkgutil.iter_modules(app_pages.__path__):
        if info.name.startswith("_"):
            continue
        assert info.name in app_pages.PAGE_MANIFEST, (
            f"{info.name} is not in PAGE_MANIFEST, so discovery would import it "
            "eagerly on every start"
        )
        module = importlib.import_module(f"{app_pages.__name__}.{info.name}")
        declared = app_pages.PAGE_MANIFEST[info.name]
        actual = module.PAGE
        assert (declared.key, declared.title, declared.icon, declared.order) == (
            actual.key,
            actual.title,
            actual.icon,
            actual.order,
        )


def test_preload_imports_every_lazy_page_module_in_background() -> None:
    """Preloading imports each manifest module off the calling thread."""
    for name in app_pages.PAGE_MANIFEST:
        sys.modules.pop(f"{app_pages.__name__}.{name}", None)

    thread = app_pages.preload_page_modules()
    thread.join(timeout=60)

    assert not thread.is_alive()
    for name in app_pages.PAGE_MANIFEST:
        assert f"{app_pages.__name__}.{name}" in sys.modules
