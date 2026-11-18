# Frequenz CS Reporting Library Release Notes

## Summary

Improved reporting reliability and responsiveness while data is refreshed, including faster startup in Deepnote.

## Upgrading

## New Features

- In Deepnote, the app now starts with the fast local cache immediately while the persistent cache snapshot is restored in the background. The restore copies cache files in parallel and reporting waits only when it first needs the cache.

## Bug Fixes

