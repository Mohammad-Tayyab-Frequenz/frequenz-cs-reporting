# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for one-time reporting-data reuse."""

import pandas as pd
import pytest
import streamlit as st

from frequenz.cs_reporting.services import reporting_session
from frequenz.cs_reporting.services.parquet_cache import SyncMetadata
from frequenz.cs_reporting.services.reporting_session import (
    ReportingDataKey,
    ReportingDataSnapshot,
)


def test_snapshot_is_reused_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A price rerun consumes one matching reporting snapshot."""
    monkeypatch.setattr(st, "session_state", {})
    key = ReportingDataKey(243, "start", "end", "Europe/Berlin", 900)
    snapshot = ReportingDataSnapshot(
        key=key,
        active_power=pd.DataFrame({"value": [1.0]}),
        battery_soc=None,
        sync_metadata=SyncMetadata(dataset="active_power_mid243_900s"),
    )
    reporting_session.store_reporting_data_snapshot(snapshot)
    reporting_session.request_reporting_data_reuse()

    assert reporting_session.take_reporting_data_snapshot(key) is snapshot
    assert reporting_session.take_reporting_data_snapshot(key) is None


def test_snapshot_is_not_reused_for_different_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed reporting selection invalidates the one-time reuse request."""
    monkeypatch.setattr(st, "session_state", {})
    stored_key = ReportingDataKey(243, "start", "end", "Europe/Berlin", 900)
    requested_key = ReportingDataKey(244, "start", "end", "Europe/Berlin", 900)
    reporting_session.store_reporting_data_snapshot(
        ReportingDataSnapshot(
            key=stored_key,
            active_power=pd.DataFrame(),
            battery_soc=None,
            sync_metadata=SyncMetadata(dataset="active_power_mid243_900s"),
        )
    )
    reporting_session.request_reporting_data_reuse()

    assert reporting_session.take_reporting_data_snapshot(requested_key) is None
