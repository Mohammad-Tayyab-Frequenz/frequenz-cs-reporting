# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for Deepnote's hybrid cache storage helpers."""

import os
from pathlib import Path

import pytest

from frequenz.cs_reporting.services.deepnote_cache import (
    persist_deepnote_hybrid_cache,
    prepare_deepnote_hybrid_cache,
)


def test_prepare_and_persist_hybrid_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
