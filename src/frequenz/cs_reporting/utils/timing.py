# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""File-backed wall-clock timing diagnostics for Streamlit execution."""

from __future__ import annotations

import fcntl
import os
import time
from atexit import register
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Lock, Thread, current_thread
from time import perf_counter

from frequenz.cs_reporting.services.cache_config import get_cache_config

_TIMING_LOG_NAME = "duration_log.txt"
_TIMING_QUEUE: Queue[tuple[Path, str]] = Queue()
_TIMING_WORKER_LOCK = Lock()
_TIMING_WORKER: Thread | None = None


def _timing_log_path() -> Path:
    """Return the timing log beside the persistent cache metadata."""
    return get_cache_config().storage_path.parent / "metadata" / _TIMING_LOG_NAME


def _append_timing_batch(entries: list[tuple[Path, str]]) -> None:
    """Append a batch of timing entries from the background writer."""
    entries_by_path: dict[Path, list[str]] = {}
    for path, line in entries:
        entries_by_path.setdefault(path, []).append(line)
    for path, lines in entries_by_path.items():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as output:
                fcntl.flock(output.fileno(), fcntl.LOCK_EX)
                output.writelines(lines)
                fcntl.flock(output.fileno(), fcntl.LOCK_UN)
        except OSError:
            # Performance diagnostics must never prevent a page from rendering.
            continue


def _timing_writer() -> None:
    """Write queued timing entries in small batches without blocking Streamlit."""
    while True:
        first = _TIMING_QUEUE.get()
        entries = [first]
        time.sleep(0.05)
        while True:
            try:
                entries.append(_TIMING_QUEUE.get_nowait())
            except Empty:
                break
        try:
            _append_timing_batch(entries)
        finally:
            for _ in entries:
                _TIMING_QUEUE.task_done()


def _ensure_timing_worker() -> None:
    """Start the single in-process timing writer when needed."""
    global _TIMING_WORKER  # pylint: disable=global-statement
    with _TIMING_WORKER_LOCK:
        if _TIMING_WORKER is None or not _TIMING_WORKER.is_alive():
            _TIMING_WORKER = Thread(
                target=_timing_writer,
                name="timing-log-writer",
                daemon=True,
            )
            _TIMING_WORKER.start()


def _write_timing_line(message: str) -> None:
    """Queue one timing line without blocking the calling operation."""
    try:
        path = _timing_log_path()
        timestamp = datetime.now(tz=UTC).isoformat(timespec="milliseconds")
        context = f"pid={os.getpid()} thread={current_thread().name}"
        _ensure_timing_worker()
        _TIMING_QUEUE.put((path, f"{timestamp} [timing] {message} {context}\n"))
    except RuntimeError:
        # Performance diagnostics must never prevent a page from rendering.
        return


def flush_timing_log() -> None:
    """Wait until all queued timing entries have been written."""
    _TIMING_QUEUE.join()


@contextmanager
def log_duration(operation: str) -> Iterator[None]:
    """Record the wall-clock duration of an operation in the timing log.

    Args:
        operation: Stable, human-readable operation name.
    """
    _write_timing_line(f"START {operation}")
    started = perf_counter()
    try:
        yield
    finally:
        elapsed = perf_counter() - started
        _write_timing_line(f"END {operation} duration={elapsed:.3f}s")


register(flush_timing_log)
