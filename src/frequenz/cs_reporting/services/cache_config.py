# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Configuration for the persistent reporting-data cache."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _positive_int(name: str, default: int) -> int:
    """Read a positive integer environment setting."""
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw_value!r}") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class CacheConfig:
    """Persistent cache settings loaded from environment variables."""

    storage_path: Path
    sync_interval_minutes: int
    sync_overlap_minutes: int
    request_timeout_seconds: int


def get_cache_config() -> CacheConfig:
    """Return cache settings.

    Values are read on each call so tests and deployments can change the
    environment before starting a Streamlit process.
    """
    return CacheConfig(
        storage_path=Path(os.getenv("PARQUET_STORAGE_PATH", "data/parquet")),
        sync_interval_minutes=_positive_int("SYNC_INTERVAL_MINUTES", 15),
        sync_overlap_minutes=_positive_int("SYNC_OVERLAP_MINUTES", 5),
        request_timeout_seconds=_positive_int("API_REQUEST_TIMEOUT_SECONDS", 300),
    )
