# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Hybrid fast-local and persistent cache storage for Deepnote."""

from __future__ import annotations

import os
import shutil
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from frequenz.cs_reporting.utils.timing import flush_timing_log

_DEFAULT_PERSISTENT_ROOT = Path("/work/data")
_DEFAULT_LOCAL_ROOT = Path("/tmp/frequenz-cs-reporting")
_CACHE_DIRECTORIES = ("parquet", "metadata")
_INITIALIZED_MARKER = ".deepnote-cache-initialized"
_PERSIST_EXECUTOR = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="deepnote-cache-persist",
)
_PERSIST_LOCK = Lock()
_PERSIST_FUTURE: Future[None] | None = None
_PERSIST_PENDING = False


def running_in_deepnote() -> bool:
    """Return whether the process is running in a Deepnote environment."""
    return any(
        key in os.environ
        for key in ("DEEPNOTE_PROJECT_ID", "DEEPNOTE_WORKSPACE_ID", "DEEPNOTE")
    )


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
    # Create the durable layout up front.  Besides making the configured
    # storage visible immediately in Deepnote, this validates that the project
    # mount is writable before a scheduled synchronization needs it.
    for directory in _CACHE_DIRECTORIES:
        (persistent / directory).mkdir(parents=True, exist_ok=True)
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
    # Timing writes are already asynchronous, so waiting here only blocks this
    # persistence worker (or an explicit scheduled command), never Streamlit.
    # It ensures duration_log.txt is part of the same persistent snapshot.
    flush_timing_log()
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


def start_background_deepnote_cache_persist() -> Future[None] | None:
    """Persist the local Deepnote cache without blocking Streamlit.

    Multiple requests are coalesced.  If another request arrives while a copy
    is running, the worker performs one additional pass so updates created
    during the first copy cannot be missed.

    Returns:
        The active persistence future, or ``None`` outside an enabled Deepnote
        hybrid-cache environment.
    """
    global _PERSIST_FUTURE, _PERSIST_PENDING  # pylint: disable=global-statement

    if not running_in_deepnote() or not deepnote_hybrid_cache_enabled():
        return None

    with _PERSIST_LOCK:
        if _PERSIST_FUTURE is not None and not _PERSIST_FUTURE.done():
            _PERSIST_PENDING = True
            return _PERSIST_FUTURE
        _PERSIST_PENDING = False
        _PERSIST_FUTURE = _PERSIST_EXECUTOR.submit(_persist_until_idle)
        return _PERSIST_FUTURE


def _persist_until_idle() -> None:
    """Persist repeatedly until no request arrived during the latest copy."""
    global _PERSIST_FUTURE, _PERSIST_PENDING  # pylint: disable=global-statement

    while True:
        persist_deepnote_hybrid_cache()
        with _PERSIST_LOCK:
            if not _PERSIST_PENDING:
                # Clear this before returning so a request arriving while the
                # Future transitions to done starts a new queued copy.
                _PERSIST_FUTURE = None
                return
            _PERSIST_PENDING = False


def _fsync_files(root: Path) -> None:
    """Durably flush regular files copied to persistent storage."""
    for path in root.rglob("*"):
        if path.is_file() and path.suffix != ".lock":
            with path.open("rb") as input_file:
                os.fsync(input_file.fileno())
