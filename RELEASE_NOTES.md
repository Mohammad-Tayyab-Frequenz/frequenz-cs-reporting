# Frequenz CS Reporting Library Release Notes

## Summary

Refactored the battery-optimization reporting code without changing user-facing behavior.

## Upgrading


## New Features


## Bug Fixes

- Day-ahead price synchronization requests only the ranges missing from the cache and no longer re-fetches an overlap of already cached prices.
- The day-ahead price warning is shown in German and lists the date ranges missing from the cached prices. It also warns when the `ENTSOE_API_KEY` is missing, in which case no fetch is attempted and only cached prices are used.
- Data-loading errors no longer show raw exception text (internal paths, API URLs) in the UI. They show a short error ID instead, and the full exception is logged with the same ID.
- Config discovery ignores `.toml` symlinks that point outside the config directory.
- Section divider labels and KPI section titles are HTML-escaped.
- A zero resolution (for example `0min`) is rejected with a clear error.
- Removed the unused `CFG`, `AppConfig` and `Paths` objects from `rep_cs_core.config`.
- The previous-period comparison covers the same local calendar days when the selected period crosses a daylight-saving change (it previously lost one hour).
