# Frequenz CS Reporting Library Release Notes

## Summary

Improved application startup and page navigation performance.

## Upgrading


## New Features

- The microgrid catalog is fetched in the background at the start of every app run, whichever page is open, and the reporting page modules are preloaded, reducing the wait when opening reporting pages.
- The home page background image is smaller and its encoded form is cached, reducing initial page-load work.
- The `battery_optimization` page module is now loaded lazily, when the page is first opened.
- Timing diagnostics are off by default. Set `CS_REPORTING_TIMING=1` to append page and data-fetch durations, including the extra `api.*` Reporting API stage timings, to `duration_log.txt`.

## Bug Fixes

