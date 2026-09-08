# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Factories for microgrid client creation and configuration loading."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import streamlit as st
from frequenz.client.assets import AssetsApiClient
from frequenz.client.common.microgrid import MicrogridId
from frequenz.data.microgrid import component_data
from frequenz.gridpool.config import MicrogridConfig, load_configs

from frequenz.cs_reporting.utils.env import require_env


@st.cache_resource(show_spinner=False)
def _load_microgrid_configs() -> dict[int, MicrogridConfig]:
    """Load and cache microgrid configs from disk.

    Returns:
        Mapping of microgrid IDs to configurations.

    Raises:
        RuntimeError: If the configured microgrid directory does not exist.
    """
    config_root = Path(os.getenv("MICROGRID_CONFIG_DIR", "toml_directory/"))
    if not config_root.is_dir():
        raise RuntimeError(f"Microgrid config directory not found: {config_root}")
    config_files: list[str | Path] = sorted(config_root.glob("*.toml"))
    if not config_files:
        raise RuntimeError(f"No microgrid config files found in: {config_root}")
    auth_key = require_env("FREQUENZ_API_KEY")
    sign_secret = require_env("FREQUENZ_API_SECRET")
    assets_api_url = require_env("ASSETS_API_URL")

    async def load() -> dict[int, MicrogridConfig]:
        assets_client = AssetsApiClient(
            assets_api_url,
            auth_key=auth_key,
            sign_secret=sign_secret,
        )
        try:
            assets_config = await load_configs(
                default_files=config_files,
                assets_client=assets_client,
            )
            return assets_config.microgrids
        finally:
            await assets_client.disconnect()

    return asyncio.run(load())


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

    configs = _load_microgrid_configs()
    if microgrid_id not in configs:
        raise KeyError(f"Microgrid {microgrid_id} not found in configured microgrids.")
    return component_data.MicrogridData(
        server_url=server_url,
        auth_key=auth_key,
        sign_secret=None,  # type: ignore[arg-type]
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


@st.cache_data(show_spinner=False)
def get_microgrid_ids() -> list[int]:
    """Return available microgrid IDs sorted ascending.

    Returns:
        List of configured microgrid IDs.
    """
    return sorted(_load_microgrid_configs())


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
