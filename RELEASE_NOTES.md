# Frequenz CS Reporting Library Release Notes

## Summary


## Upgrading


## New Features

- The reporting sidebar displays each microgrid's ID alongside its current name from the Assets API. The reporting page title now uses the format `MID<id> - <name>`.
- Data tables now provide a compact toolbar in every tab, with controls to select the component data source where applicable, reset active filters, and download the displayed data as CSV.
- KPI cards include a compact help tooltip that explains how the selected period is compared with the preceding period.

## Bug Fixes

- KPI comparison colours now reflect their meaning: grid and total-consumption values remain neutral, production, self-consumption, autonomy, and self-consumption-rate increases are positive, and battery flows remain neutral.
- The sidebar is more compact, allowing navigation and filter controls to fit without unnecessary scrolling. Reporting and solar sidebar controls also retain separate state in Deepnote.
