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
- `FREQUENZ_API_KEY` and `FREQUENZ_API_SECRET` **(required)**: Credentials used
  to authenticate and sign Reporting and Assets API requests.
- `MICROGRID_CONFIG_DIR` *(optional)*: Directory containing TOML microgrid
  configs. Defaults to `toml_directory/`.
- `PARQUET_STORAGE_PATH` *(optional)*: Persistent directory for reporting data.
  Defaults to `data/parquet`.
- `SYNC_INTERVAL_MINUTES` *(optional)*: Minimum interval between overlap
  refreshes. Defaults to `15`.
- `SYNC_OVERLAP_MINUTES` *(optional)*: Tail window re-fetched to pick up recent
  corrections. Defaults to `5`.
- `API_REQUEST_TIMEOUT_SECONDS` *(optional)*: Reporting request timeout.
  Defaults to `300`.

### Microgrid configs

Microgrid definitions are loaded from TOML files in `MICROGRID_CONFIG_DIR`.

## Running the Streamlit app

The app entry point is `app.py`. When you run `streamlit run app.py`, it:

- Discovers pages from `frequenz.cs_reporting.app_pages` (the default
  build ships `Home` and `Reporting` pages).
- Loads microgrid configs from `MICROGRID_CONFIG_DIR` and lists available IDs.
- Fetches data via the reporting API.

### Persistent data cache

Active-power, battery-SOC, and ENTSO-E day-ahead price time series are stored as
Parquet. Microgrid measurements are separated by microgrid and resolution. The
first request downloads the requested range;
later requests read covered ranges locally and fetch only missing intervals.
When a dataset is due for refresh, its trailing overlap is fetched again and
merged by timestamp. Writes use a same-directory temporary file followed by an
atomic replacement, while a file lock prevents duplicate writers across
Streamlit sessions and local worker processes. Sync metadata is stored beside
the Parquet directory in `data/metadata` by default.

The reporting client used by this app exposes time-range queries, but not
record modification timestamps, stable record IDs, change tokens, ETags, or a
deletion feed. Consequently this is range-incremental synchronization, not a
complete change-data-capture implementation. Corrections older than the overlap
window require a wider explicit reconciliation request or rebuilding that
dataset. Pagination remains owned by the upstream Frequenz clients. The cache
retries transient connection, timeout, HTTP 429, and server errors with
exponential backoff and honors `Retry-After` when the client exposes it.

For production, run synchronization independently from Streamlit, for example
every 15 minutes with cron or the deployment platform's scheduler:

```bash
python -m frequenz.cs_reporting.services.sync_data \
  --microgrid-id 241 --lookback-days 30 --resolution-minutes 15
```

The page remains a safe pull-through fallback: cache hits do not call the API,
and failed overlap refreshes continue serving the last successful file. Point
`PARQUET_STORAGE_PATH` at persistent storage. All replicas must see the same
filesystem with working POSIX locks; ephemeral container disks and independent
per-replica volumes do not provide a coherent shared cache. For those
deployments, use a shared POSIX volume or replace this backend with
object-storage/database coordination.

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
