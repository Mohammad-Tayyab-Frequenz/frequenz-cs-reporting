# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Main application module for the Frequenz CS Reporting Suite."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
import importlib.resources as resources
import importlib.util
import streamlit as st
import pkgutil
import os


# --- Check if running in deepnote to pick up environment variables ---
def running_in_deepnote() -> bool:
    # Common Deepnote env vars (if one changes, the others may still work)
    return any(
        k in os.environ
        for k in (
            "DEEPNOTE_PROJECT_ID",
            "DEEPNOTE_WORKSPACE_ID",
            "DEEPNOTE",
        )
    )


IN_DEEPNOTE = running_in_deepnote()

if IN_DEEPNOTE:
    import deepnote_toolkit

    deepnote_toolkit.set_integration_env()

# --- Project paths & sys.path wiring ----------------------------------------
PACKAGE_DIR = Path(__file__).resolve().parent
LIB_PAGES_ROOT = "frequenz.cs_reporting.app_pages"
LOGO_NAME = "neustrom_logo.png"


def _resolve_package_root() -> Path:
    """Return the installed frequenz package path, with a local fallback for dev."""
    spec = importlib.util.find_spec("frequenz.cs_reporting")
    if spec and spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations))).resolve()
    if spec and spec.origin:
        return Path(spec.origin).resolve().parent
    return (PACKAGE_DIR / "src" / "frequenz" / "cs_reporting").resolve()


PACKAGE_ROOT = _resolve_package_root()
APP_PAGES_DIR = PACKAGE_ROOT / "app_pages"
ASSETS_DIR = PACKAGE_ROOT / "assets"

package_parent = str(PACKAGE_ROOT.parent)
if package_parent not in sys.path:
    sys.path.insert(0, package_parent)

# Import PageSpec from your custom library
from frequenz.cs_reporting.rep_cs_core.page_spec import PageSpec


# --- Local page loader (from ./app_pages) -----------------------------------
def _load_local_pages() -> list[PageSpec]:
    """Load PAGE specs from local app_pages/*.py files."""
    if not APP_PAGES_DIR.exists():
        return []

    pages: list[PageSpec] = []

    for module_path in sorted(APP_PAGES_DIR.glob("*.py")):
        if module_path.name.startswith("_") or module_path.name == "__init__.py":
            continue
        spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        page = getattr(module, "PAGE", None)

        if page and all(
            hasattr(page, attr) for attr in ("key", "title", "icon", "order", "render")
        ):
            pages.append(page)

    return pages


# --- Library page discovery (from frequenz.app_pages) -----------------------
def discover_library_pages(pkg_root: str = LIB_PAGES_ROOT) -> list[PageSpec]:
    """Discover PAGE specs from the installed frequenz app_pages package.

    Falls back to local ./app_pages if the library package is missing.
    """
    try:
        pkg = importlib.import_module(pkg_root)
    except ModuleNotFoundError:
        # Library not installed; fall back to local pages
        return _load_local_pages()

    pages: list[PageSpec] = []

    for _, modname, _ in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
        short = modname.rsplit(".", 1)[-1]
        if short.startswith("_"):
            continue

        module = importlib.import_module(modname)
        page = getattr(module, "PAGE", None)

        if page and all(
            hasattr(page, attr) for attr in ("key", "title", "icon", "order", "render")
        ):
            pages.append(page)

    # Sort by (order, title) for stable navigation
    return sorted(pages, key=lambda p: (p.order, p.title.lower()))


def _load_logo_bytes() -> bytes | None:
    """Fetch the sidebar logo from the installed package resources."""
    try:
        return (
            resources.files("frequenz.cs_reporting.assets")
            .joinpath(LOGO_NAME)
            .read_bytes()
        )
    except (FileNotFoundError, ModuleNotFoundError):
        pass

    local_logo = ASSETS_DIR / LOGO_NAME
    if local_logo.exists():
        return local_logo.read_bytes()
    return None


# Sidebar navigation
def sidebar(pages: list[PageSpec]) -> PageSpec:
    if logo_bytes := _load_logo_bytes():
        st.sidebar.image(logo_bytes, width="stretch")

    st.sidebar.divider()

    state_key = "selected_page"
    valid_keys = {p.key for p in pages}
    default_key = st.query_params.get("page", [pages[0].key])[0]

    if default_key not in valid_keys:
        default_key = pages[0].key

    # Initialize session state with the URL query parameter
    st.session_state.setdefault(state_key, default_key)

    # Ensure the state matches the URL param on the initial load/rerun
    if st.session_state[state_key] != default_key:
        st.session_state[state_key] = default_key

    # Map display labels to internal keys
    options = {f"{p.icon} {p.title}": p.key for p in pages}
    display_options = list(options.keys())

    current_key = st.session_state[state_key]
    initial_index = next(
        (idx for idx, page in enumerate(pages) if page.key == current_key), 0
    )

    # Function to resolve the selected key from the display label
    def get_key_from_label(label: str) -> str:
        return options.get(label, pages[0].key)

    # Add page navigation header
    st.sidebar.header("📑 Seiten")

    # Use st.sidebar.radio to manage selection
    selected_label = st.sidebar.radio(
        "Navigation",
        options=display_options,
        index=initial_index,
        key="navigation_radio",
        label_visibility="collapsed",
    )

    # Add divider after navigation
    st.sidebar.divider()

    # Update session state and query params based on radio selection
    selected_key = get_key_from_label(selected_label)
    if st.session_state[state_key] != selected_key:
        st.session_state[state_key] = selected_key
        st.query_params.page = selected_key

    selected = next(p for p in pages if p.key == st.session_state[state_key])
    return selected


# --- Main entrypoint --------------------------------------------------------
def main() -> None:
    st.set_page_config(
        page_title="Enterprise Reporting App",
        page_icon="🏢",
        layout="wide",
    )

    pages = discover_library_pages()
    if not pages:
        st.info(f"No pages found under `{LIB_PAGES_ROOT}` (or local app_pages).")
        return

    selected = sidebar(pages)

    # Render selected page
    selected.render()


if __name__ == "__main__":
    main()
