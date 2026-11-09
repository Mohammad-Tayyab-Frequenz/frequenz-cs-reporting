# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for Deepnote's hybrid cache storage helpers."""

import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from frequenz.cs_reporting.services.deepnote_cache import (
    persist_deepnote_hybrid_cache,
    prepare_deepnote_hybrid_cache,
    start_background_deepnote_cache_persist,
)


def test_prepare_and_persist_hybrid_cache(tmp_path: Path) -> None:
    """Persistent data is restored locally and updated data is copied back."""
    persistent = tmp_path / "persistent"
    local = tmp_path / "local"
    (persistent / "parquet").mkdir(parents=True)
    (persistent / "metadata").mkdir()
    (persistent / "parquet" / "prices.parquet").write_bytes(b"old")
    (persistent / "metadata" / "prices.json").write_text("{}", encoding="utf-8")

    parquet_path = prepare_deepnote_hybrid_cache(persistent, local)

    assert parquet_path == local / "parquet"
    assert (parquet_path / "prices.parquet").read_bytes() == b"old"
    assert (local / "metadata" / "prices.json").is_file()
    assert os.environ["PARQUET_STORAGE_PATH"] == str(parquet_path)

    (parquet_path / "prices.parquet").write_bytes(b"new")
    persist_deepnote_hybrid_cache(persistent, local)

    assert (persistent / "parquet" / "prices.parquet").read_bytes() == b"new"


def test_prepare_creates_empty_persistent_cache_layout(tmp_path: Path) -> None:
    """Preparing an empty cache creates both durable cache directories."""
    persistent = tmp_path / "persistent"
    local = tmp_path / "local"

    prepare_deepnote_hybrid_cache(persistent, local)

    assert (persistent / "parquet").is_dir()
    assert (persistent / "metadata").is_dir()
    assert (local / "parquet").is_dir()
    assert (local / "metadata").is_dir()


def test_background_persist_copies_local_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The app can persist Deepnote's local cache without blocking its caller."""
    persistent = tmp_path / "persistent"
    local = tmp_path / "local"
    monkeypatch.setenv("DEEPNOTE_PROJECT_ID", "test-project")
    monkeypatch.setenv("DEEPNOTE_PERSISTENT_CACHE_ROOT", str(persistent))
    monkeypatch.setenv("DEEPNOTE_LOCAL_CACHE_ROOT", str(local))
    prepare_deepnote_hybrid_cache(persistent, local)
    (local / "metadata" / "active_power.json").write_text("{}", encoding="utf-8")

    future = start_background_deepnote_cache_persist()

    assert future is not None
    future.result(timeout=2)
    assert (persistent / "metadata" / "active_power.json").is_file()


def test_persist_skips_temporary_files_and_copies_data_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A snapshot copies data before its coverage metadata or temporary files."""
    persistent = tmp_path / "persistent"
    local = tmp_path / "local"
    prepare_deepnote_hybrid_cache(persistent, local)
    (local / "parquet" / "a.parquet").write_bytes(b"data")
    (local / "parquet" / ".a.parquet.x1.parquet.tmp").write_bytes(b"partial")
    (local / "metadata" / "a.json").write_text("{}", encoding="utf-8")
    copied: list[str] = []
    real_copytree = shutil.copytree

    def recording_copytree(source: Path, *args: Any, **kwargs: Any) -> Any:
        copied.append(Path(source).name)
        return real_copytree(source, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", recording_copytree)

    persist_deepnote_hybrid_cache(persistent, local)

    assert copied == ["parquet", "metadata"]
    assert (persistent / "parquet" / "a.parquet").is_file()
    assert not list((persistent / "parquet").glob("*.tmp"))


def test_interrupted_persist_does_not_publish_new_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An interrupted copy cannot make old data appear covered."""
    persistent = tmp_path / "persistent"
    local = tmp_path / "local"
    prepare_deepnote_hybrid_cache(persistent, local)
    (persistent / "parquet" / "a.parquet").write_bytes(b"old-data")
    (persistent / "metadata" / "a.json").write_text("old-metadata", encoding="utf-8")
    (local / "parquet" / "a.parquet").write_bytes(b"new-data")
    (local / "metadata" / "a.json").write_text("new-metadata", encoding="utf-8")
    real_copytree = shutil.copytree

    def fail_copying_metadata(source: Path, *args: Any, **kwargs: Any) -> Any:
        if Path(source).name == "metadata":
            raise OSError("simulated interruption")
        return real_copytree(source, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", fail_copying_metadata)

    with pytest.raises(OSError, match="simulated interruption"):
        persist_deepnote_hybrid_cache(persistent, local)

    assert (persistent / "parquet" / "a.parquet").read_bytes() == b"new-data"
    assert (persistent / "metadata" / "a.json").read_text(encoding="utf-8") == (
        "old-metadata"
    )
