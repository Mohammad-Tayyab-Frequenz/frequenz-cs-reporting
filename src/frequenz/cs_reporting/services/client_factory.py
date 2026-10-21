# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Factories for microgrid client creation and configuration loading."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tomllib
from pathlib import Path
from typing import TypeAlias

import streamlit as st
from frequenz.client.assets import AssetsApiClient
from frequenz.client.common.microgrid import MicrogridId
from frequenz.client.reporting import ReportingApiClient
from frequenz.data.microgrid import component_data
from frequenz.gridpool.config import MicrogridConfig, load_configs

from frequenz.cs_reporting.utils.env import require_env
from frequenz.cs_reporting.utils.timing import log_duration

MicrogridConfigRevision: TypeAlias = tuple[str, tuple[tuple[str, str], ...]]
MicrogridConfigSource: TypeAlias = tuple[tuple[str, ...], MicrogridConfigRevision]
ApiCredentialRevision: TypeAlias = str
_ASSETS_API_TIMEOUT_SECONDS = 20.0
_LAST_ASSET_NAMES: dict[str, dict[int, str | None]] = {}


def get_api_credential_revision() -> ApiCredentialRevision:
    """Return a non-secret fingerprint of the current API credentials."""
    digest = hashlib.sha256()
    for variable in ("ASSETS_API_URL", "FREQUENZ_API_KEY", "FREQUENZ_API_SECRET"):
        value = require_env(variable)
        digest.update(variable.encode("utf-8"))
        digest.update(b"\0")
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


@st.cache_resource(show_spinner=False)
def _microgrid_file_index_cached(
    config_files: tuple[str, ...],
) -> dict[int, tuple[str, ...]]:
    """Map each microgrid ID to the TOML files that define it.

    Files are only parsed as plain TOML here, which is cheap compared to
    ``load_configs`` that merges, validates and builds the full catalog.
    """
    index: dict[int, list[str]] = {}
    for config_file in config_files:
        with open(config_file, "rb") as handle:
            data = tomllib.load(handle)
        microgrids = data.get("assets", {}).get("microgrids", {})
        for microgrid_id in microgrids:
            index.setdefault(int(microgrid_id), []).append(config_file)
    return {mid: tuple(files) for mid, files in index.items()}


@st.cache_resource(show_spinner=False)
def _load_microgrid_config_cached(
    microgrid_id: int,
    config_files: tuple[str, ...],
    revision: MicrogridConfigRevision,
) -> MicrogridConfig:
    """Load the configuration of a single microgrid from its own TOML files."""
    del revision

    async def load() -> MicrogridConfig:
        assets_config = await load_configs(default_files=list(config_files))
        return assets_config.microgrids[microgrid_id]

    with log_duration(f"client_factory.load_config.mid{microgrid_id}"):
        return asyncio.run(load())


@st.cache_resource(show_spinner=False)
def _microgrid_config_source_cached(config_root_value: str) -> MicrogridConfigSource:
    """Discover and fingerprint the static TOML file manifest once per process."""
    config_root = Path(config_root_value)
    if not config_root.is_dir():
        raise RuntimeError(f"Microgrid config directory not found: {config_root}")

    config_paths = tuple(sorted(config_root.glob("*.toml")))
    if not config_paths:
        raise RuntimeError(f"No microgrid config files found in: {config_root}")

    manifest = "\0".join(path.name for path in config_paths).encode("utf-8")
    file_revisions = (("static-catalog", hashlib.sha256(manifest).hexdigest()),)
    config_files = tuple(str(path.resolve()) for path in config_paths)
    revision = (str(config_root.resolve()), file_revisions)
    return config_files, revision


def _microgrid_config_source() -> MicrogridConfigSource:
    """Return the process-cached static TOML source."""
    config_root = os.getenv("MICROGRID_CONFIG_DIR", "frequenz_config_microgrid/assets/")
    return _microgrid_config_source_cached(config_root)


def get_microgrid_config_revision() -> MicrogridConfigRevision:
    """Return the process-stable fingerprint of the static TOML catalog."""
    _, revision = _microgrid_config_source()
    return revision


def _load_microgrid_config(microgrid_id: int) -> MicrogridConfig:
    """Return the cached configuration of one microgrid.

    Only the TOML files defining ``microgrid_id`` are loaded, so the cost does
    not grow with the size of the whole configuration directory.

    Raises:
        KeyError: If no TOML file defines the microgrid.
    """
    config_files, revision = _microgrid_config_source()
    files = _microgrid_file_index_cached(config_files).get(microgrid_id)
    if not files:
        raise KeyError(f"Microgrid {microgrid_id} not found in configured microgrids.")
    return _load_microgrid_config_cached(microgrid_id, files, revision)


def get_microgrid_client(microgrid_id: int) -> component_data.MicrogridData:
    """Create a MicrogridData client using cached configs.

    The client is not cached to avoid binding an async HTTP client to the wrong
    event loop when Streamlit reruns the app. Config files remain cached via
    `_load_microgrid_config()`.

    Args:
        microgrid_id: Identifier for the target microgrid.

    Returns:
        Client ready to fetch microgrid data.

    Raises:
        KeyError: If the specified microgrid ID is not found in configs.
    """
    server_url = require_env("REPORTING_API_URL")
    auth_key = require_env("FREQUENZ_API_KEY")
    sign_secret = require_env("FREQUENZ_API_SECRET")

    configs = {microgrid_id: _load_microgrid_config(microgrid_id)}
    return component_data.MicrogridData(
        server_url=server_url,
        auth_key=auth_key,
        sign_secret=sign_secret,
        microgrid_configs=configs,
    )


def get_reporting_client() -> ReportingApiClient:
    """Create a Reporting API client for direct component metric queries."""
    return ReportingApiClient(
        server_url=require_env("REPORTING_API_URL"),
        auth_key=require_env("FREQUENZ_API_KEY"),
        sign_secret=require_env("FREQUENZ_API_SECRET"),
    )


def get_component_types(microgrid_id: int) -> tuple[str, ...]:
    """Return all component types configured for the microgrid.

    Args:
        microgrid_id: Identifier for the target microgrid.

    Returns:
        Component type identifiers.
    """
    mcfg = _load_microgrid_config(microgrid_id)
    return tuple(mcfg.component_types())


def get_microgrid_config(microgrid_id: int) -> MicrogridConfig:
    """Return the MicrogridConfig for a given microgrid.

    Args:
        microgrid_id: Identifier for the target microgrid.

    Returns:
        Loaded configuration for the microgrid.
    """
    return _load_microgrid_config(microgrid_id)


def get_microgrid_ids() -> list[int]:
    """Return microgrid IDs accessible with the current credentials.

    Returns:
        List of accessible microgrid IDs sorted ascending.
    """
    return sorted(get_microgrid_names())


@st.cache_data(show_spinner=False, ttl=3600)
def _get_microgrid_names(
    credential_revision: ApiCredentialRevision,
) -> dict[int, str | None]:
    """Return the microgrids accessible through the Assets API.

    The Assets API limits its response to the current credential scope, so it
    is the single source of the microgrid list and names.  The cache is keyed
    by the credential fingerprint, so changing the integration environment
    variables refreshes it.  The call is bounded by a timeout; on failure the
    last successful result is reused so the sidebar never blocks for minutes.
    """
    auth_key = require_env("FREQUENZ_API_KEY")
    sign_secret = require_env("FREQUENZ_API_SECRET")
    assets_api_url = require_env("ASSETS_API_URL")

    async def load() -> dict[int, str | None]:
        assets_client = AssetsApiClient(
            assets_api_url,
            auth_key=auth_key,
            sign_secret=sign_secret,
        )
        try:
            microgrids = await asyncio.wait_for(
                assets_client.list_microgrids(), _ASSETS_API_TIMEOUT_SECONDS
            )
            return {int(microgrid.id): microgrid.name for microgrid in microgrids}
        finally:
            await assets_client.disconnect()

    try:
        with log_duration("client_factory.assets_list_microgrids"):
            names = asyncio.run(load())
    except (TimeoutError, OSError):
        if credential_revision not in _LAST_ASSET_NAMES:
            raise
        return _LAST_ASSET_NAMES[credential_revision]
    _LAST_ASSET_NAMES[credential_revision] = names
    return names


def get_microgrid_names() -> dict[int, str | None]:
    """Return accessible microgrid IDs and names from the Assets API."""
    return _get_microgrid_names(get_api_credential_revision())


@st.cache_data(show_spinner=False)
def get_meter_display_names(microgrid_id: int) -> dict[str, str]:
    """Return component display names for a microgrid from the Assets API.

    Args:
        microgrid_id: Identifier for the target microgrid.

    Returns:
        Mapping of component ID strings to display names.
    """
    auth_key = require_env("FREQUENZ_API_KEY")
    sign_secret = require_env("FREQUENZ_API_SECRET")
    assets_api_url = require_env("ASSETS_API_URL")

    async def load() -> dict[str, str]:
        assets_client = AssetsApiClient(
            assets_api_url,
            auth_key=auth_key,
            sign_secret=sign_secret,
        )
        try:
            components = await assets_client.list_microgrid_electrical_components(
                MicrogridId(microgrid_id)
            )
            return {
                str(component.id): component.name
                for component in components
                if component.name
            }
        finally:
            await assets_client.disconnect()

    return asyncio.run(load())
