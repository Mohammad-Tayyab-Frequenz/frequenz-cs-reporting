# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for the per-stage Reporting API timing instrumentation."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from frequenz.cs_reporting.services.api_timing import instrument_client
from frequenz.cs_reporting.utils import timing


class _FakeReportingClient:
    async def receive_aggregated_data(self, **_: Any) -> AsyncIterator[dict[str, Any]]:
        for value in range(3):
            yield {"value": value}

    async def receive_microgrid_components_data(
        self, **_: Any
    ) -> AsyncIterator[dict[str, Any]]:
        for value in range(2):
            yield {"value": value}


class _FakeMicrogridData:
    def __init__(self) -> None:
        self._client = _FakeReportingClient()

    async def metric_data(self, **_: Any) -> str:
        async for _sample in self._client.receive_aggregated_data():
            pass
        return "metric"

    async def _component_metric_data(self, **_: Any) -> str:
        async for _sample in self._client.receive_microgrid_components_data():
            pass
        return "components"


def _log_lines(tmp_path: Path) -> list[str]:
    timing.flush_timing_log()
    path = tmp_path / "metadata" / "duration_log.txt"
    return path.read_text(encoding="utf-8").splitlines()


def test_instrumented_client_logs_each_stage_and_keeps_results(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Every stage is timed and sample counts are logged; behaviour is unchanged."""
    monkeypatch.setenv("PARQUET_STORAGE_PATH", str(tmp_path / "parquet"))
    monkeypatch.setenv("CS_REPORTING_TIMING", "1")
    client = _FakeMicrogridData()
    instrument_client(client)

    async def run() -> tuple[str, str]:
        return (
            await client.metric_data(),
            await client._component_metric_data(),  # pylint: disable=protected-access
        )

    assert asyncio.run(run()) == ("metric", "components")

    text = "\n".join(_log_lines(tmp_path))
    assert "END api.metric_data duration=" in text
    assert "END api.aggregated_stream duration=" in text
    assert "NOTE api.aggregated_stream samples=3" in text
    assert "END api.component_metric_data duration=" in text
    assert "END api.component_stream duration=" in text
    assert "NOTE api.component_stream samples=2" in text


def test_instrument_client_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Instrumenting twice must not double-wrap and double-log."""
    monkeypatch.setenv("PARQUET_STORAGE_PATH", str(tmp_path / "parquet"))
    monkeypatch.setenv("CS_REPORTING_TIMING", "1")
    client = _FakeMicrogridData()
    instrument_client(client)
    instrument_client(client)

    asyncio.run(client.metric_data())

    text = "\n".join(_log_lines(tmp_path))
    assert text.count("END api.metric_data ") == 1
    assert text.count("END api.aggregated_stream ") == 1


def test_instrument_client_is_a_no_op_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without CS_REPORTING_TIMING the client methods are not wrapped."""
    monkeypatch.delenv("CS_REPORTING_TIMING", raising=False)
    client = _FakeMicrogridData()
    original = client.metric_data

    instrument_client(client)

    assert client.metric_data == original


def test_missing_wrap_targets_log_warnings(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A renamed upstream attribute is reported instead of silently skipped."""
    monkeypatch.setenv("CS_REPORTING_TIMING", "1")

    class _RenamedMicrogridData:
        async def metric_data(self, **_: Any) -> str:
            return "metric"

    with caplog.at_level("WARNING"):
        instrument_client(_RenamedMicrogridData())

    assert "api.component_metric_data" in caplog.text
    assert "'_client'" in caplog.text
