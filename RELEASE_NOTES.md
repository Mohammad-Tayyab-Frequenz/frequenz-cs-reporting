# Frequenz CS Reporting Library Release Notes

## Summary


## Upgrading

## New Features


## Bug Fixes

- Background data synchronizations are shared between dashboard sessions and failed synchronizations are throttled before retrying.
- Hybrid cache persistence now copies data atomically, ignores temporary files, and persists available data when a synchronization fails.
- Time series plots with many points now render with WebGL, and the battery overview plot shows the grid feed-in as "Netzeinspeisung".
- Table column choosers are refreshed when the available columns change, e.g. after applying a new date filter.
- Reporting data is now loaded directly instead of waiting for a warm cache or a background refresh, so the displayed data is current for the selected range.
- Battery state-of-charge and grid metering data are fetched in parallel, reducing reporting-page load time.
