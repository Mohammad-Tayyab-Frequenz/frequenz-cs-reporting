# Code structure

This document explains how the codebase is organized so new code lands in
the right place. It complements [CONTRIBUTING.md](CONTRIBUTING.md), which
covers workflow (branches, releases, CI); this file covers layout and
layering.

## Layering

The app is a layered Streamlit application. Each layer only depends on the
layers below it:

```
app.py                  Streamlit entrypoint: page discovery + navigation
   │
   ▼
app_pages/               One module per Streamlit page (registers a PAGE)
   │
   ▼
views/                    Business/data-aware section rendering
   │
   ▼
components/               Dumb, reusable UI widgets
   │
   ▼
services/                 Data access & business logic (no Streamlit calls)
```

`utils/`, `styles/`, `templates/`, `assets/`, and a few small root-level
modules (`constants.py`, `page_spec.py`, `ui_resources.py`) are cross-cutting
and can be used from any layer.

| Directory / file | Purpose | Example |
| --- | --- | --- |
| `app.py` | Top-level Streamlit entrypoint. Discovers pages, renders the sidebar/navigation, sets global page config and theme. | `main()`, `sidebar()` |
| `app_pages/` | One module per navigable page. Each module builds and exports a `PAGE: PageSpec` describing how to render itself. Pages call into `views`/`services`, they don't render report sections directly. | `app_pages/reporting.py`, `app_pages/solar.py` |
| `views/` | Business/data-aware rendering: combines `components` widgets with reporting data (tables, metrics, microgrid config) to render a section of a page (a KPI grid, a plot tab, a data table). Anything that needs to know about report-specific data shapes belongs here. | `views/dashboard.py`, `views/table_renderers.py`, `views/plot_renderers.py`, `views/metric_renderers.py`, `views/solar_renderers.py` |
| `components/` | Dumb, reusable building blocks: render a widget (a table, a chart, an input, a styled card) with no awareness of reporting business logic or app-specific data shapes. | `components/tables.py` (`aggrid_table`), `components/plot_charts.py`, `components/inputs.py`, `components/ui.py` |
| `services/` | Data access and business logic: fetching microgrid data, building client connections, preparing workflow requests. No Streamlit UI calls. | `services/client_factory.py`, `services/data_service.py`, `services/solar_workflow.py` |
| `utils/` | Small, generic, Streamlit-agnostic helpers not specific to reporting (env vars, time/timezone helpers). | `utils/env.py`, `utils/time.py` |
| `constants.py` | Shared constants and shared `TypedDict`s used across layers (e.g. `COLOR_DICT`, `TablesResult`). | — |
| `page_spec.py` | The `PageSpec` dataclass used by `app.py` and every `app_pages/*.py` module for navigation. | — |
| `ui_resources.py` | Loads packaged HTML templates and CSS stylesheets, and injects CSS into the current Streamlit run (`inject_style`, `inject_style_once`). | — |
| `styles/`, `templates/`, `assets/` | Packaged, non-Python resources: CSS files, HTML templates, images (logo, icons). | `styles/kpi.css`, `templates/dashboard_section_divider.html` |
| `tests/` | Test suite (pytest). | `tests/test_frequenz_cs_reporting.py` |

## Where does new code go?

- **New Streamlit page** → `app_pages/`. Export a `PAGE: PageSpec`.
- **New data fetch or business logic** (talking to microgrid clients,
  building requests) → `services/`.
- **New reusable, data-agnostic widget** (works the same regardless of what
  report it's used in) → `components/`.
- **New page-specific section** that combines one or more `components` with
  report data → `views/`.
- **New generic helper** with no Streamlit or reporting dependency → `utils/`.
- **New CSS** → add a `.css` file under `styles/` and load it with
  `inject_style_once()` from `ui_resources.py` — never inline CSS strings in
  Python. `inject_style_once` guards against re-injecting the same
  stylesheet multiple times within one Streamlit session; use `inject_style`
  directly only if you deliberately need per-call token substitution.

## Standards

This library follows the standard Frequenz OSS lint/type/format setup,
configured in `pyproject.toml` and runnable via `nox` (see
[CONTRIBUTING.md](CONTRIBUTING.md) for the full dev setup):

- `black` / `isort` — formatting and import order.
- `mypy --strict` — full type coverage.
- `flake8` (with `pydoclint`/`pydocstyle`, Google-style docstrings) — style
  and docstring checks.
- `pylint` — additional static analysis.

Run them all at once with `nox`, or individually, e.g.:

```bash
mypy
flake8 src/frequenz/cs_reporting app.py
pylint src/frequenz/cs_reporting app.py
black --check src app.py
isort --check src app.py
```
