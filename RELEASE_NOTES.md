# Frequenz CS Reporting Library Release Notes

## Summary

Improved reporting reliability and responsiveness while data is refreshed.

## Upgrading
- Add duration logs to the battery page for debugging.

## New Features

- Battery reporting now displays cached data while fresh power, state-of-charge, capacity, and day-ahead-price data is loaded in the background.
- The microgrid catalog is fetched in the background at the start of every app run, whichever page is open, and the reporting page modules are preloaded, reducing the wait when opening reporting pages.
- The home page background image is smaller and its encoded form is cached, reducing initial page-load work.
- The `battery_optimization` page module is now loaded lazily, when the page is first opened.
- Timing diagnostics are off by default. Set `CS_REPORTING_TIMING=1` to append page and data-fetch durations, including the extra `api.*` Reporting API stage timings, to `duration_log.txt`.

## Bug Fixes

- The app no longer crashes when the microgrid catalog is temporarily unavailable; it shows a retry message and automatically tries again.
- Reporting and cache synchronization now use bounded shared worker pools, preventing repeated page runs from accumulating threads.
