# Frequenz CS Reporting Library Release Notes

## Summary


## Upgrading


## New Features

- Component plots for PV, battery, wind, and CHP now include a plot header
  selector to switch between meter data and inverter/component data.

## Bug Fixes

- Day-ahead price data from ENTSO-E is now optional in the dashboard. If the
  data cannot be fetched, the dashboard shows a warning and skips the related
  price KPIs and plot traces instead of failing.
