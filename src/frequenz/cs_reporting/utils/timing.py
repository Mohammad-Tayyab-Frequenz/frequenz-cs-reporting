# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""File-backed wall-clock timing diagnostics for Streamlit execution."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock, current_thread
from time import perf_counter

from frequenz.cs_reporting.services.cache_config import get_cache_config

_TIMING_LOG_NAME = "duration_log.txt"
_TIMING_LOG_LOCK = Lock()


def _timing_log_path() -> Path:
    """Return the timing log beside the persistent cache metadata."""
    return get_cache_config().storage_path.parent / "metadata" / _TIMING_LOG_NAME


def _write_timing_line(message: str) -> None:
    """Append one timing line without allowing diagnostics to break the app."""
    try:
        path = _timing_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=UTC).isoformat(timespec="milliseconds")
        context = f"pid={os.getpid()} thread={current_thread().name}"
        with _TIMING_LOG_LOCK, path.open("a", encoding="utf-8") as output:
            fcntl.flock(output.fileno(), fcntl.LOCK_EX)
            output.write(f"{timestamp} [timing] {message} {context}\n")
            output.flush()
            fcntl.flock(output.fileno(), fcntl.LOCK_UN)
    except (OSError, RuntimeError):
        # Performance diagnostics must never prevent a page from rendering.
        return


@contextmanager
def log_duration(operation: str) -> Iterator[None]:
    """Record the wall-clock duration of an operation in the timing log.

    Args:
        operation: Stable, human-readable operation name.
    """
    started = perf_counter()
    _write_timing_line(f"START {operation}")
    try:
        yield
    finally:
        elapsed = perf_counter() - started
        _write_timing_line(f"END {operation} duration={elapsed:.3f}s")
