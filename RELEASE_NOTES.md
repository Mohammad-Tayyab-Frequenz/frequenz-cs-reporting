# Frequenz CS Reporting Library Release Notes

## Summary


## Upgrading


## New Features


## Bug Fixes

- Component plots and tables for PV, battery, wind, and CHP now fall back to
  inverter/component data when meter data is unavailable, preventing empty tabs
  or failures for microgrids without meter-level component data.
- Time-series plot cards now allocate enough vertical space for Plotly charts,
  legends, and range sliders, preventing clipped chart content.

