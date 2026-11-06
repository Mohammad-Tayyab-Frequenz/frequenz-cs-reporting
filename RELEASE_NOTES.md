# Frequenz CS Reporting Library Release Notes

## Summary


## Upgrading

Place all microgrid TOML files in the directory selected by
`MICROGRID_CONFIG_DIR`. When it is unset, the app first checks
`frequenz_config_microgrid/assets/` and falls back to `toml_directory/` when
that directory is absent. Deployments using another location can continue
setting `MICROGRID_CONFIG_DIR` explicitly.

## New Features

## Bug Fixes

- Microgrid configurations are enriched with topology data from the Assets API.
- Solar reporting now validates that the selected category contains PV components and turns expected no-data results into an actionable warning containing the microgrid, component IDs, period, and metric.
