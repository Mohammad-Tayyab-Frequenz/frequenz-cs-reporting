# Frequenz CS Reporting Library

[![Build Status](https://github.com/frequenz-floss/frequenz-cs-reporting/actions/workflows/ci.yaml/badge.svg)](https://github.com/frequenz-floss/frequenz-cs-reporting/actions/workflows/ci.yaml)
[![PyPI Package](https://img.shields.io/pypi/v/frequenz-cs-reporting)](https://pypi.org/project/frequenz-cs-reporting/)
[![Docs](https://img.shields.io/badge/docs-latest-informational)](https://frequenz-floss.github.io/frequenz-cs-reporting/)

## Overview

Streamlit library that ships a ready-to-use client reporting UI. It fetches data from the Frequenz reporting API, applies the energy
reporting utilities from `frequenz-lib-notebooks`, and renders dashboards, tables, and plots with reusable Streamlit components.

## Features

- Pre-built Streamlit app with navigation, landing page, and reporting view.
- Connects to the Frequenz reporting API to fetch microgrid measurements.
- Ready-made dashboards (metrics, plots, and tables) powered by
  `frequenz-lib-notebooks`.
- Reusable components (sidebar filters, charts, tables) for your own pages.

## Quick start

1. Install the library (Python 3.12):
   ```bash
   pip install "frequenz-cs-reporting"
   ```
2. Provide environment variables (see below). A `.env` file works with Streamlit:
   ```bash
   REPORTING_API_URL=https://your-reporting-endpoint
   FREQUENZ_API_KEY=your-api-key
   FREQUENZ_API_SECRET=your-signing-secret
   MICROGRID_CONFIG_DIR=toml_directory/
   ```
3. Add .toml files to the toml_directory.
4. Run the bundled UI from the repo root:
   ```bash
   streamlit run app.py
   ```
   Use the sidebar to pick a microgrid, date range, timezone, and resolution.

## Configuration

### Environment

- `REPORTING_API_URL` **(required)**: Base URL for the Frequenz reporting API.
- `FREQUENZ_API_KEY` **(required)**: Credential used by the data client.
- `FREQUENZ_API_SECRET` **(required)**: Signing secret used for Assets API requests.
- `MICROGRID_CONFIG_DIR` *(optional)*: Directory containing TOML microgrid
  configs. Defaults to `toml_directory/`.

### Microgrid configs

Microgrid definitions are loaded from TOML files in `MICROGRID_CONFIG_DIR`.

## Running the Streamlit app

The app entry point is `app.py`. When you run `streamlit run app.py`, it:

- Discovers pages from `frequenz.cs_reporting.app_pages` (the default
  build ships `Home` and `Reporting` pages).
- Loads microgrid configs from `MICROGRID_CONFIG_DIR` and lists available IDs.
- Fetches data via the reporting API.

### Running in Deepnote
- Running in Deepnote is supported; required environment variables can be injected
via the Deepnote integration.
- Add this library as a requirement in requirements.txt
- Add the docker image from dockerhub (currently named: CS-Reporting in deepnote).
- Copy the app.py to the folder structure in Deepnote.
- Click on create_streamlit_application in Deepnote UI to create the app.

## Library usage

Fetch microgrid data programmatically (sync wrapper shown):

```python
from datetime import datetime, timedelta
from frequenz.cs_reporting.services.data_service import get_microgrid_data

df = get_microgrid_data(
    microgrid_id=241,
    start_date=datetime(2024, 1, 1),
    end_date=datetime(2024, 1, 2),
    resolution=timedelta(minutes=15),
)
```

Build your own Streamlit page and add it to the navigation by defining a
`PageSpec` in `frequenz.cs_reporting.app_pages`:

```python
# app_pages/custom.py
from frequenz.cs_reporting.rep_cs_core.page_spec import PageSpec
import streamlit as st

def render() -> None:
    st.title("Custom view")
    st.write("Add your own charts or tables here.")

PAGE = PageSpec(key="custom", title="Custom", icon="🛠️", order=10, render=render)
```

## Development

- Install dev tools: `pip install -e ".[dev]"`.
- Run tests: `nox -l` to see sessions, e.g. `nox -s tests`.
- Build docs with MkDocs (`README.md` is the landing page). After installing the
  mkdocs extra you can use the `docs` nox session (if available) or run
  `mkdocs serve`.

## Supported Platforms

The following platforms are officially supported (tested):

- **Python:** 3.12
- **Operating System:** Ubuntu Linux 20.04
- **Architectures:** amd64, arm64

## Contributing

If you want to know how to build this project and contribute to it, please
check out the [Contributing Guide](CONTRIBUTING.md).
