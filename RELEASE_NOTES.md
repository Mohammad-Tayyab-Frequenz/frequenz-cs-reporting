# Frequenz CS Reporting Library Release Notes

## Summary

Refactored the battery-optimization reporting code without changing user-facing behavior.

## Upgrading


## New Features


## Bug Fixes
- Data-loading errors no longer show raw exception text (internal paths, API URLs) in the UI. They show a short error ID instead, and the full exception is logged with the same ID.
- Config discovery ignores `.toml` symlinks that point outside the config directory.
