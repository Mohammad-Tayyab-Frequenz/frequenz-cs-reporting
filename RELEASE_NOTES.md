# Frequenz CS Reporting Library Release Notes

## Summary

- v0.4.8 and v0.4.9 was not released because `pytest_min` was not satisfied. Everything else remains the same, but the minimum library requirements have been updated.

## Upgrading


## New Features


## Bug Fixes

- Day-ahead price data from ENTSO-E is now optional in the dashboard. If the
  data cannot be fetched, the dashboard shows a warning and skips the related
  price KPIs and plot traces instead of failing.
