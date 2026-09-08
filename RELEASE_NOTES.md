# Frequenz CS Reporting Library Release Notes

## Summary


## Upgrading


## New Features

- Reporting KPI cards now show the previous-period value and percentage change.
  When the selected period includes the current day and only partial current-day
  data is available, the previous period is capped to the same elapsed duration
  for a fair comparison.
- Component plots for PV, battery, wind, and CHP now include a plot header
  selector to switch between meter data and inverter/component data.

## Bug Fixes

- The sidebar layout now uses tighter spacing for the logo, page navigation,
  filter sections, and form controls, removing large unused gaps.
- Day-ahead price data from ENTSO-E is now optional in the dashboard. If the
  data cannot be fetched, the dashboard shows a warning and skips the related
  price KPIs and plot traces instead of failing.
