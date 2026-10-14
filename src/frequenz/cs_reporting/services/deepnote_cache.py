# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Hybrid fast-local and persistent cache storage for Deepnote."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_DEFAULT_PERSISTENT_ROOT = Path("/work/data")
_DEFAULT_LOCAL_ROOT = Path("/tmp/frequenz-cs-reporting")
_CACHE_DIRECTORIES = ("parquet", "metadata")
_INITIALIZED_MARKER = ".deepnote-cache-initialized"


def deepnote_hybrid_cache_enabled() -> bool:
    """Return whether Deepnote hybrid cache storage is enabled."""
    value = os.getenv("DEEPNOTE_HYBRID_CACHE_ENABLED", "true")
    return value.strip().lower() not in {"0", "false", "no", "off"}


def prepare_deepnote_hybrid_cache(
    persistent_root: Path | None = None,
    local_root: Path | None = None,
) -> Path:
    """Restore a persistent snapshot to fast local storage and select it.

    The restore is performed only once per Deepnote machine lifetime. The
    returned Parquet path is also assigned to ``PARQUET_STORAGE_PATH``.

    Args:
        persistent_root: Durable cache root, defaulting to ``/work/data``.
        local_root: Fast ephemeral cache root, defaulting to
            ``/tmp/frequenz-cs-reporting``.

    Returns:
        The fast local Parquet directory.
    """
    persistent = persistent_root or Path(
        os.getenv("DEEPNOTE_PERSISTENT_CACHE_ROOT", str(_DEFAULT_PERSISTENT_ROOT))
    )
    local = local_root or Path(
        os.getenv("DEEPNOTE_LOCAL_CACHE_ROOT", str(_DEFAULT_LOCAL_ROOT))
    )
    local.mkdir(parents=True, exist_ok=True)
    marker = local / _INITIALIZED_MARKER
    if not marker.exists():
        for directory in _CACHE_DIRECTORIES:
            source = persistent / directory
            destination = local / directory
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            else:
                destination.mkdir(parents=True, exist_ok=True)
        marker.touch()

    parquet_path = local / "parquet"
    parquet_path.mkdir(parents=True, exist_ok=True)
    (local / "metadata").mkdir(parents=True, exist_ok=True)
    os.environ["PARQUET_STORAGE_PATH"] = str(parquet_path)
    return parquet_path


def persist_deepnote_hybrid_cache(
    persistent_root: Path | None = None,
    local_root: Path | None = None,
) -> None:
    """Copy the fast local cache back to Deepnote's persistent storage.

    This should be called after a scheduled synchronization rather than only
    at process shutdown, which is not guaranteed to run in Deepnote.

    Args:
        persistent_root: Durable cache root, defaulting to ``/work/data``.
        local_root: Fast ephemeral cache root, defaulting to
            ``/tmp/frequenz-cs-reporting``.
    """
    persistent = persistent_root or Path(
        os.getenv("DEEPNOTE_PERSISTENT_CACHE_ROOT", str(_DEFAULT_PERSISTENT_ROOT))
    )
    local = local_root or Path(
        os.getenv("DEEPNOTE_LOCAL_CACHE_ROOT", str(_DEFAULT_LOCAL_ROOT))
    )
    persistent.mkdir(parents=True, exist_ok=True)
    for directory in _CACHE_DIRECTORIES:
        source = local / directory
        if source.is_dir():
            destination = persistent / directory
            shutil.copytree(source, destination, dirs_exist_ok=True)
            _fsync_files(destination)


def _fsync_files(root: Path) -> None:
    """Durably flush regular files copied to persistent storage."""
    for path in root.rglob("*"):
        if path.is_file() and path.suffix != ".lock":
            with path.open("rb") as input_file:
                os.fsync(input_file.fileno())
