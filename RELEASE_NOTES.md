# Frequenz CS Reporting Library Release Notes

## Summary


## Upgrading

The cache defaults to `data/parquet`, with synchronization metadata stored in
`data/metadata`. Deployments should ensure this location is persistent and
writable. Multiple application replicas must share a filesystem that supports
POSIX file locking.

The following optional environment variables are available:

- `PARQUET_STORAGE_PATH` selects the Parquet directory. It defaults to
  `data/parquet`.
- `SYNC_INTERVAL_MINUTES` controls refresh frequency. It defaults to 15
  minutes.
- `SYNC_OVERLAP_MINUTES` controls the recent-data overlap fetched during a
  refresh. It defaults to 5 minutes.
- `API_REQUEST_TIMEOUT_SECONDS` controls Reporting API request timeouts. It
  defaults to 300 seconds.

Deployments can move synchronization out of Streamlit page execution by
running `python -m frequenz.cs_reporting.services.sync_data` from cron or a
platform scheduler.

## New Features

- Active-power, battery-SOC, and ENTSO-E day-ahead price data are persisted as
  Parquet and loaded through a shared range-aware data-access layer.
- Requests fully covered by the local dataset are served without another API
  call. Requests extending the cached period fetch only the missing intervals,
  while a configurable overlap refreshes recent values.
- Expensive master-report transformations are cached, and a scheduler-friendly
  synchronization command can pre-warm datasets independently of Streamlit.
- The reporting sidebar displays each microgrid's ID alongside its current name from the Assets API. The reporting page title now uses the format `MID<id> - <name>`.
- Data tables now provide a compact toolbar in every tab, with controls to select the component data source where applicable, reset active filters, and download the displayed data as CSV.
- Reporting data tables now offer German and English formatting from the CSV
  toolbar. The selection updates both the displayed number format and the CSV
  delimiter and decimal mark; German formatting remains the default.
- KPI cards include a compact help tooltip that explains how the selected period is compared with the preceding period.
- Page, data-access, calculation, and rendering durations are appended to
  `data/metadata/duration_log.txt` for performance diagnostics.
- The dashboard reads 15-minute day-ahead prices exclusively from the local
  cache. Scheduled synchronization can refresh prices after their daily
  publication without blocking interactive page loads.
- A missing day-ahead price range now starts one shared background
  synchronization job. A polling fragment reruns the dashboard once when the
  prices become available, while the initial dashboard remains usable.
- Page navigation metadata is loaded from a lightweight manifest; individual
  page modules and their heavier dependencies are imported only when selected.
- Deepnote uses an automatic hybrid cache: persistent snapshots are restored
  from `/work/data` to fast `/tmp` storage, and scheduled synchronization copies
  successful updates back to persistent storage.
- Deepnote now also saves the local Parquet cache, synchronization metadata,
  and duration log to `/work/data` in a coalescing background worker after page
  loads and completed background synchronizations.
- The full rerun triggered by completed day-ahead price synchronization reuses
  the active-power and battery-SOC data already loaded for the current filters.
- Interactive active-power requests use cached data immediately and launch a
  shared background refresh. A completely empty cache performs one foreground
  synchronization so initial loading remains reliable in embedded deployments.
- Timing entries are written asynchronously in batches. Ephemeral `/tmp`
  metadata skips durability `fsync`, synchronization persists only its final
  metadata state, and cache reads return data with the metadata already read.

## Bug Fixes

- Battery-SOC data is now read from the local cache immediately and refreshed by one shared background job, so a slow or unavailable Reporting API no longer blocks the dashboard from rendering cached data.
- When the current reporting period is not cached yet, the dashboard now waits for the active-power background refresh and reruns automatically instead of showing an empty-data warning that required manually reapplying the filters.
- Selected pages use full Streamlit reruns so forms rendered in the sidebar
  reliably apply date, microgrid, timezone, and resolution changes in Deepnote.
- Active-power background requests no longer round their end timestamp into
  the future, preventing the Reporting API's `INVALID_ARGUMENT` response and
  infinite streaming retry loop.
- Empty active-power caches now perform one guaranteed initial synchronization
  against fast local storage instead of depending on a browser-driven polling
  fragment. Later cache refreshes remain non-blocking, and Deepnote creates its
  persistent `/work/data` cache layout during application startup.
- KPI comparison colours now reflect their meaning: grid and total-consumption values remain neutral, production, self-consumption, autonomy, and self-consumption-rate increases are positive, and battery flows remain neutral.
- The sidebar is more compact, allowing navigation and filter controls to fit without unnecessary scrolling. Reporting and solar sidebar controls also retain separate state in Deepnote.
