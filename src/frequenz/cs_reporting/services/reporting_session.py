# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""One-rerun reporting-data reuse for background price synchronization."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from frequenz.cs_reporting.services.parquet_cache import SyncMetadata

_SNAPSHOT_STATE_KEY = "_reporting_data_snapshot"
_REUSE_ONCE_STATE_KEY = "_reuse_reporting_data_once"


@dataclass(frozen=True)
class ReportingDataKey:
    """Inputs that uniquely identify a reporting data request."""

    microgrid_id: int
    start_iso: str
    end_iso: str
    timezone: str
    resolution_seconds: int
    credential_revision: str


@dataclass
class ReportingDataSnapshot:
    """Data that can be reused for the price-completion rerun."""

    key: ReportingDataKey
    active_power: pd.DataFrame
    battery_soc: pd.DataFrame | None
    sync_metadata: SyncMetadata


def store_reporting_data_snapshot(snapshot: ReportingDataSnapshot) -> None:
    """Store the most recently loaded reporting datasets for this session."""
    st.session_state[_SNAPSHOT_STATE_KEY] = snapshot


def request_reporting_data_reuse() -> None:
    """Request reuse of the stored datasets on the next full app rerun."""
    st.session_state[_REUSE_ONCE_STATE_KEY] = True


def take_reporting_data_snapshot(
    key: ReportingDataKey,
) -> ReportingDataSnapshot | None:
    """Consume a one-time reuse request and return its matching snapshot."""
    if not st.session_state.pop(_REUSE_ONCE_STATE_KEY, False):
        return None
    snapshot = st.session_state.get(_SNAPSHOT_STATE_KEY)
    if not isinstance(snapshot, ReportingDataSnapshot) or snapshot.key != key:
        return None
    return snapshot
