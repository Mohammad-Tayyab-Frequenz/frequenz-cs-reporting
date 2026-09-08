# Frequenz CS Reporting Library Release Notes

## Summary


## Upgrading

- The minimum supported `frequenz-gridpool` version is now 0.7.1. Configuration
  loading now uses the `AssetsConfig.microgrids` mapping introduced by that
  release.
- Rename `API_KEY` to `FREQUENZ_API_KEY` and `API_SECRET` to
  `FREQUENZ_API_SECRET` in the application environment or `.env` file. Both
  variables are required for authenticated and signed Reporting and Assets API
  requests.

## New Features

- Solar monitoring plots are now rendered as interactive Plotly charts instead
  of static Matplotlib images.
- Reporting KPI cards now show the previous-period value and percentage change.
  When the selected period includes the current day and only partial current-day
  data is available, the previous period is capped to the same elapsed duration
  for a fair comparison.
- Component plots for PV, battery, wind, and CHP now include a plot header
  selector to switch between meter data and inverter/component data.

## Bug Fixes

- Reporting API streaming requests now include `FREQUENZ_API_SECRET` for request
  signing, preventing authentication failures when loading report data.
- Dashboard and Solar workflows now read microgrid IDs and location metadata
  directly from `MicrogridConfig`, avoiding failures caused by the removed
  `meta` attribute in `frequenz-gridpool` 0.7.1.
- The sidebar layout now uses tighter spacing for the logo, page navigation,
  filter sections, and form controls, removing large unused gaps.
- Day-ahead price data from ENTSO-E is now optional in the dashboard. If the
  data cannot be fetched, the dashboard shows a warning and skips the related
  price KPIs and plot traces instead of failing.
