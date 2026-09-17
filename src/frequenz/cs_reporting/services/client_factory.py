# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Factories for microgrid client creation and configuration loading."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Iterable
from pathlib import Path
from typing import TypeAlias

import streamlit as st
from frequenz.client.assets import AssetsApiClient
from frequenz.client.assets.electrical_component import Battery
from frequenz.client.assets.metrics import Metric
from frequenz.client.common.microgrid import MicrogridId
from frequenz.data.microgrid import component_data
from frequenz.gridpool.config import MicrogridConfig, load_configs

from frequenz.cs_reporting.utils.env import require_env

MicrogridConfigRevision: TypeAlias = tuple[str, tuple[tuple[str, str], ...]]
MicrogridConfigSource: TypeAlias = tuple[tuple[str, ...], MicrogridConfigRevision]


@st.cache_resource(show_spinner=False)
def _load_microgrid_configs_cached(
    config_files: tuple[str, ...],
    revision: MicrogridConfigRevision,
) -> dict[int, MicrogridConfig]:
    """Load the process-wide static TOML microgrid catalog."""
    del revision

    async def load() -> dict[int, MicrogridConfig]:
        assets_config = await load_configs(
            default_files=list(config_files),
        )
        return assets_config.microgrids

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


def _load_microgrid_configs() -> dict[int, MicrogridConfig]:
    """Return the process-wide static TOML microgrid catalog.

    Returns:
        Mapping of microgrid IDs to configurations.
    """
    source = _microgrid_config_source()
    return _load_microgrid_configs_cached(*source)


def get_microgrid_client(microgrid_id: int) -> component_data.MicrogridData:
    """Create a MicrogridData client using cached configs.

    The client is not cached to avoid binding an async HTTP client to the wrong
    event loop when Streamlit reruns the app. Config files remain cached via
    `_load_microgrid_configs()`.

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

    configs = _load_microgrid_configs()
    if microgrid_id not in configs:
        raise KeyError(f"Microgrid {microgrid_id} not found in configured microgrids.")
    return component_data.MicrogridData(
        server_url=server_url,
        auth_key=auth_key,
        sign_secret=sign_secret,
        microgrid_configs=configs,
    )


def get_component_types(microgrid_id: int) -> tuple[str, ...]:
    """Return all component types configured for the microgrid.

    Args:
        microgrid_id: Identifier for the target microgrid.

    Returns:
        Component type identifiers.
    """
    mcfg = _load_microgrid_configs()[microgrid_id]
    return tuple(mcfg.component_types())


def get_microgrid_config(microgrid_id: int) -> MicrogridConfig:
    """Return the MicrogridConfig for a given microgrid.

    Args:
        microgrid_id: Identifier for the target microgrid.

    Returns:
        Loaded configuration for the microgrid.
    """
    return _load_microgrid_configs()[microgrid_id]


def get_microgrid_ids() -> list[int]:
    """Return configured microgrid IDs accessible with the current credentials.

    Returns:
        List of accessible, configured microgrid IDs sorted ascending.
    """
    return sorted(get_microgrid_names())


@st.cache_data(show_spinner=False, ttl=300)
def _get_microgrid_names(
    revision: MicrogridConfigRevision,
) -> dict[int, str | None]:
    """Return configured microgrids accessible through the Assets API.

    The static TOML catalog supplies configuration.  The Assets API is queried
    separately and limits its response to the current credential scope, so it
    acts only as an allow-list and source of current names.  Visibility and
    names are refreshed at most every five minutes.
    """
    del revision
    configs = _load_microgrid_configs()
    names = {microgrid_id: config.name for microgrid_id, config in configs.items()}
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
            microgrids = await assets_client.list_microgrids()
            return {int(microgrid.id): microgrid.name for microgrid in microgrids}
        finally:
            await assets_client.disconnect()

    asset_names = asyncio.run(load())

    return {
        microgrid_id: asset_names[microgrid_id] or configured_name
        for microgrid_id, configured_name in names.items()
        if microgrid_id in asset_names
    }


def _battery_capacity_kwh_from_components(
    components: Iterable[object],
) -> float | None:
    """Return the summed battery capacity from electrical component metadata."""
    battery_capacity_kwh = 0.0
    for component in components:
        if not isinstance(component, Battery):
            continue

        bounds = component.rated_bounds.get(Metric.BATTERY_CAPACITY)
        if bounds is None or bounds.upper is None:
            continue
        battery_capacity_kwh += float(bounds.upper)

    return battery_capacity_kwh or None


@st.cache_data(show_spinner=False)
def get_battery_capacity_kwh(microgrid_id: int) -> float | None:
    """Return installed battery capacity for a microgrid from the Assets API.

    Args:
        microgrid_id: Identifier for the target microgrid.

    Returns:
        Installed battery capacity in kWh, or ``None`` when unavailable.
    """
    auth_key = require_env("FREQUENZ_API_KEY")
    sign_secret = require_env("FREQUENZ_API_SECRET")
    assets_api_url = require_env("ASSETS_API_URL")

    async def load() -> float | None:
        assets_client = AssetsApiClient(
            assets_api_url,
            auth_key=auth_key,
            sign_secret=sign_secret,
        )
        try:
            components = await assets_client.list_microgrid_electrical_components(
                MicrogridId(microgrid_id)
            )
            return _battery_capacity_kwh_from_components(components)
        finally:
            await assets_client.disconnect()

    return asyncio.run(load())


def get_microgrid_names() -> dict[int, str | None]:
    """Return accessible microgrid names for the static TOML catalog."""
    return _get_microgrid_names(get_microgrid_config_revision())


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
