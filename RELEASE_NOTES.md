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

## Bug Fixes

- Page navigation now clears the previous page immediately, preventing stale
  text and other content from remaining visible while the newly selected page
  loads.
- KPI comparison colours now reflect their meaning: grid and total-consumption values remain neutral, production, self-consumption, autonomy, and self-consumption-rate increases are positive, and battery flows remain neutral.
- The sidebar is more compact, allowing navigation and filter controls to fit without unnecessary scrolling. Reporting and solar sidebar controls also retain separate state in Deepnote.
