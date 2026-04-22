# Frequenz CS Reporting Library Release Notes

## Summary

This release overhauls the Reporting UI with a redesigned home/dashboard experience,
improves page navigation and routing reliability, and standardizes CHP naming from
`BHKW` to `KWK` across reporting labels.

## Upgrading

- No breaking API changes are introduced.
- Package assets now explicitly include UI templates and styles (`templates/*.html`,
  `styles/*.css`) in distribution metadata.

## New Features

- Redesign the home page with reusable HTML templates and dedicated CSS styling.
- Introduce centralized UI resource helpers for loading/injecting templates and styles.
- Add a global app theme and refreshed dashboard visual system (section dividers,
  KPI card styling, updated color palette).
- Add section-aware routing from query params (including direct scroll to Data Export
  section when requested).

## Bug Fixes

- Fix navigation state synchronization between sidebar selection and query-parameter
  routing.
- Fix data-export navigation routing and page transitions.
- Fix inconsistent terminology by renaming `BHKW` labels to `KWK` in reporting UI.
- Fix formatting and quality issues reported by `nox` checks.
