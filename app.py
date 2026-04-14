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


def _inject_global_theme() -> None:
    """Inject a professional global theme for the Streamlit app."""
    if st.session_state.get("_global_theme_injected"):
        return

    st.markdown(
        """
        <style>
        :root {
            --app-bg: #f3f6fb;
            --surface: #ffffff;
            --surface-soft: #f7f9fc;
            --text-main: #142033;
            --text-muted: #56637a;
            --border: #d9e1ec;
            --accent: #1e4f87;
            --accent-hover: #173f6c;
            --radius-md: 10px;
            --radius-sm: 8px;
            --shadow: 0 8px 24px rgba(16, 40, 74, 0.06);
        }

        [data-testid="stAppViewContainer"] {
            background: radial-gradient(circle at top right, #edf3fb 0%, var(--app-bg) 35%, #f3f6fb 100%);
            color: var(--text-main);
        }

        .main .block-container {
            max-width: 1300px;
            padding-top: 1.25rem;
            padding-bottom: 2rem;
        }

        [data-testid="stSidebar"] {
            background: #eaf0f8;
            border-right: 1px solid var(--border);
        }

        [data-testid="stSidebar"] [data-testid="stImage"] img {
            border-radius: 12px;
            border: 1px solid var(--border);
            background: #fff;
            padding: 8px;
        }

        h1, h2, h3 {
            letter-spacing: 0.01em;
            color: var(--text-main);
        }

        [data-testid="stMetric"] {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            box-shadow: var(--shadow);
        }

        [data-testid="stTabs"] [data-baseweb="tab-list"] {
            gap: 0.35rem;
            border-bottom: 1px solid var(--border);
        }

        [data-testid="stTabs"] [data-baseweb="tab"] {
            border: 1px solid transparent;
            border-radius: var(--radius-sm) var(--radius-sm) 0 0;
            padding: 0.45rem 0.85rem;
            color: var(--text-muted);
            background: transparent;
        }

        [data-testid="stTabs"] [aria-selected="true"] {
            border-color: var(--border);
            border-bottom-color: #ffffff;
            background: #ffffff;
            color: var(--text-main);
            font-weight: 600;
        }

        .stButton > button,
        [data-testid="stDownloadButton"] > button,
        div[data-testid="stFormSubmitButton"] > button {
            border-radius: var(--radius-sm);
            border: 1px solid var(--accent);
            background: var(--accent);
            color: #ffffff;
            font-weight: 600;
        }

        .stButton > button:hover,
        [data-testid="stDownloadButton"] > button:hover,
        div[data-testid="stFormSubmitButton"] > button:hover {
            background: var(--accent-hover);
            border-color: var(--accent-hover);
            color: #ffffff;
        }

        .stSelectbox div[data-baseweb="select"] > div,
        .stTextInput input,
        .stDateInput input {
            border-radius: var(--radius-sm);
            border: 1px solid var(--border);
            background: #ffffff;
        }

        .stAlert {
            border-radius: var(--radius-sm);
            border: 1px solid var(--border);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.session_state["_global_theme_injected"] = True


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
    options = {p.title: p.key for p in pages}
    display_options = list(options.keys())

    current_key = st.session_state[state_key]
    initial_index = next(
        (idx for idx, page in enumerate(pages) if page.key == current_key), 0
    )

    # Function to resolve the selected key from the display label
    def get_key_from_label(label: str) -> str:
        return options.get(label, pages[0].key)

    # Add page navigation header
    st.sidebar.header("Seiten")

    # Use st.sidebar.radio to manage selection
    selected_label = st.sidebar.radio(
        "Seiten",
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
        page_icon="📊",
        layout="wide",
    )
    _inject_global_theme()

    pages = discover_library_pages()
    if not pages:
        st.info(f"No pages found under `{LIB_PAGES_ROOT}` (or local app_pages).")
        return

    selected = sidebar(pages)

    # Render selected page
    selected.render()


if __name__ == "__main__":
    main()
