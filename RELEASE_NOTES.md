# Frequenz CS Reporting Library Release Notes

## Summary


## Upgrading
- Add cs-reporting library dependency to the dockerfile.

## New Features


## Bug Fixes

- Background data synchronizations are shared between dashboard sessions and failed synchronizations are throttled before retrying.
- Hybrid cache persistence now copies data atomically, ignores temporary files, and persists available data when a synchronization fails.
