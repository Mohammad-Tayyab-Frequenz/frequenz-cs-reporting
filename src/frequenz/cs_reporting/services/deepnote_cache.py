# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Hybrid fast-local and persistent cache storage for Deepnote."""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock, Thread, get_ident

from frequenz.cs_reporting.utils.timing import flush_timing_log, log_duration

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
_TIMING_LOG_NAME = "duration_log.txt"
_RESTORE_WORKERS = 8
# Set whenever no background restore is running, so waiting is a no-op outside
# Deepnote and once the restore has finished.
_RESTORE_DONE = Event()
_RESTORE_DONE.set()
_RESTORE_START_LOCK = Lock()


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


def _cache_roots(
    persistent_root: Path | None, local_root: Path | None
) -> tuple[Path, Path]:
    """Return the persistent and local cache roots."""
    persistent = persistent_root or Path(
        os.getenv("DEEPNOTE_PERSISTENT_CACHE_ROOT", str(_DEFAULT_PERSISTENT_ROOT))
    )
    local = local_root or Path(
        os.getenv("DEEPNOTE_LOCAL_CACHE_ROOT", str(_DEFAULT_LOCAL_ROOT))
    )
    return persistent, local


def _select_local_cache(local: Path) -> Path:
    """Create the local cache layout and point ``PARQUET_STORAGE_PATH`` at it."""
    local.mkdir(parents=True, exist_ok=True)
    parquet_path = local / "parquet"
    parquet_path.mkdir(parents=True, exist_ok=True)
    (local / "metadata").mkdir(parents=True, exist_ok=True)
    os.environ["PARQUET_STORAGE_PATH"] = str(parquet_path)
    return parquet_path


def _list_files(
    source_root: Path, destination_root: Path, ignore: tuple[str, ...]
) -> list[tuple[Path, Path]]:
    """List the files below ``source_root`` using one directory read per folder.

    ``os.scandir`` reports each entry's type with the listing, so unlike
    ``rglob`` it needs no extra ``stat`` call per file on the slow mount.
    """
    files: list[tuple[Path, Path]] = []
    pending = [(source_root, destination_root)]
    while pending:
        source_dir, destination_dir = pending.pop()
        destination_dir.mkdir(parents=True, exist_ok=True)
        try:
            with os.scandir(source_dir) as entries:
                for entry in entries:
                    if entry.name in ignore:
                        continue
                    destination = destination_dir / entry.name
                    if entry.is_dir():
                        pending.append((Path(entry.path), destination))
                    elif entry.is_file():
                        files.append((Path(entry.path), destination))
        except FileNotFoundError:
            continue
    return files


def _copy_if_missing(source: Path, destination: Path) -> None:
    """Copy ``source`` to ``destination`` unless the destination already exists.

    The copy is made beside the destination and linked into place, so a file
    the app has already written (or another restore path has already copied)
    is never overwritten, and a reader never sees a partial file.
    """
    if destination.exists():
        return
    temporary = destination.with_name(
        f"{destination.name}.{os.getpid()}.{get_ident()}.restore.tmp"
    )
    try:
        shutil.copy2(source, temporary)
        try:
            os.link(temporary, destination)
        except FileExistsError:
            pass
    except FileNotFoundError:
        pass
    finally:
        temporary.unlink(missing_ok=True)


def _restore_snapshot(
    persistent: Path, local: Path, ignore: tuple[str, ...] = ()
) -> None:
    """Copy the persistent snapshot to local storage once per machine lifetime."""
    marker = local / _INITIALIZED_MARKER
    if marker.exists():
        # Create the durable layout up front.  Besides making the configured
        # storage visible immediately in Deepnote, this validates that the
        # project mount is writable before a scheduled synchronization needs it.
        for directory in _CACHE_DIRECTORIES:
            (persistent / directory).mkdir(parents=True, exist_ok=True)
        return

    def copy(pair: tuple[Path, Path]) -> None:
        source, destination = pair
        with log_duration(f"deepnote_cache.restore.copy.{source.name}"):
            _copy_if_missing(source, destination)

    # The first access to each directory on the mount is slow, so the cache
    # directories are prepared and listed concurrently, and a directory's files
    # start copying as soon as its own listing is done.  This waits on the
    # mount rather than using the CPU.
    with (
        ThreadPoolExecutor(
            max_workers=_RESTORE_WORKERS, thread_name_prefix="deepnote-cache-restore"
        ) as copier,
        ThreadPoolExecutor(
            max_workers=len(_CACHE_DIRECTORIES),
            thread_name_prefix="deepnote-cache-list",
        ) as lister,
    ):

        def restore_directory(directory: str) -> list[Future[None]]:
            with log_duration(f"deepnote_cache.restore.mkdir_persistent.{directory}"):
                (persistent / directory).mkdir(parents=True, exist_ok=True)
            with log_duration(f"deepnote_cache.restore.list_source.{directory}"):
                files = _list_files(persistent / directory, local / directory, ignore)
            return [copier.submit(copy, pair) for pair in files]

        for futures in lister.map(restore_directory, _CACHE_DIRECTORIES):
            for future in futures:
                future.result()
    marker.touch()


def prepare_deepnote_hybrid_cache(
    persistent_root: Path | None = None,
    local_root: Path | None = None,
) -> Path:
    """Restore a persistent snapshot to fast local storage and select it.

    The restore is performed only once per Deepnote machine lifetime. The
    returned Parquet path is also assigned to ``PARQUET_STORAGE_PATH``.  This
    blocks until the copy is complete; the app uses
    :func:`start_deepnote_hybrid_cache_restore` instead.

    Args:
        persistent_root: Durable cache root, defaulting to ``/work/data``.
        local_root: Fast ephemeral cache root, defaulting to
            ``/tmp/frequenz-cs-reporting``.

    Returns:
        The fast local Parquet directory.
    """
    persistent, local = _cache_roots(persistent_root, local_root)
    local.mkdir(parents=True, exist_ok=True)
    _restore_snapshot(persistent, local)
    return _select_local_cache(local)


def _restore_timing_history(persistent: Path, local: Path) -> None:
    """Put the persisted timing history in front of this session's entries.

    The timing log is appended to from the first request on, so it is merged
    under the writer's own file lock instead of being overwritten by the copy.
    """
    history = persistent / "metadata" / _TIMING_LOG_NAME
    if not history.is_file():
        return
    previous = history.read_bytes()
    with (local / "metadata" / _TIMING_LOG_NAME).open("a+b") as output:
        fcntl.flock(output.fileno(), fcntl.LOCK_EX)
        try:
            output.seek(0)
            current = output.read()
            output.truncate(0)
            output.write(previous + current)
        finally:
            fcntl.flock(output.fileno(), fcntl.LOCK_UN)


def start_deepnote_hybrid_cache_restore(
    persistent_root: Path | None = None,
    local_root: Path | None = None,
) -> Path:
    """Select the local cache now and restore the snapshot in the background.

    The first access to the persistent mount can take many seconds on
    Deepnote, which would otherwise delay the home page.  Code that reads or
    writes cache files must call :func:`wait_for_deepnote_cache_restore`
    first; ``ParquetRangeCache`` does so on construction.

    Args:
        persistent_root: Durable cache root, defaulting to ``/work/data``.
        local_root: Fast ephemeral cache root, defaulting to
            ``/tmp/frequenz-cs-reporting``.

    Returns:
        The fast local Parquet directory.
    """
    persistent, local = _cache_roots(persistent_root, local_root)
    parquet_path = _select_local_cache(local)
    # Streamlit re-runs ``app.py`` for every session, so this can be called
    # concurrently; only the first call may start a restore.
    with _RESTORE_START_LOCK:
        if not _RESTORE_DONE.is_set() or (local / _INITIALIZED_MARKER).exists():
            return parquet_path
        _RESTORE_DONE.clear()

    def restore() -> None:
        try:
            with log_duration("deepnote_cache.restore"):
                _restore_snapshot(persistent, local, ignore=(_TIMING_LOG_NAME,))
                _restore_timing_history(persistent, local)
        except OSError:
            logging.getLogger(__name__).exception(
                "Restoring the Deepnote cache snapshot failed"
            )
        finally:
            _RESTORE_DONE.set()

    Thread(target=restore, name="deepnote-cache-restore", daemon=True).start()
    return parquet_path


def wait_for_deepnote_cache_restore() -> None:
    """Block until a background cache restore (if any) has finished."""
    _RESTORE_DONE.wait()


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
    wait_for_deepnote_cache_restore()
    persistent, local = _cache_roots(persistent_root, local_root)
    persistent.mkdir(parents=True, exist_ok=True)
    for directory in _CACHE_DIRECTORIES:
        source = local / directory
        if source.is_dir():
            destination = persistent / directory
            shutil.copytree(
                source,
                destination,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("*.tmp"),
                copy_function=_copy_atomically,
            )
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


def _copy_atomically(source: str, destination: str) -> str:
    """Copy a file so an interruption never leaves a truncated destination."""
    temporary = f"{destination}.persist.tmp"
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)
    return destination


def _fsync_files(root: Path) -> None:
    """Durably flush regular files copied to persistent storage."""
    for path in root.rglob("*"):
        if path.is_file() and path.suffix != ".lock":
            with path.open("rb") as input_file:
                os.fsync(input_file.fileno())
