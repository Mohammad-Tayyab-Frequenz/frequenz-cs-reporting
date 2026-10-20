# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Factories for microgrid client creation and configuration loading."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tomllib
from pathlib import Path
from threading import Lock
from typing import TypeAlias

import streamlit as st
from frequenz.client.assets import AssetsApiClient
from frequenz.client.common.microgrid import MicrogridId
from frequenz.data.microgrid import component_data
from frequenz.gridpool.config import MicrogridConfig, load_configs

from frequenz.cs_reporting.utils.env import require_env

MicrogridConfigRevision: TypeAlias = tuple[str, tuple[tuple[str, str], ...]]
MicrogridConfigSource: TypeAlias = tuple[tuple[str, ...], MicrogridConfigRevision]

_CONFIG_SOURCE_LOCK = Lock()
_LAST_GOOD_CONFIG_SOURCE: MicrogridConfigSource | None = None


def _configured_microgrid_ids(config_files: tuple[str, ...]) -> list[int]:
    """Read microgrid IDs without validating incomplete configuration entries."""
    microgrid_ids: set[int] = set()
    for config_file in config_files:
        with Path(config_file).open("rb") as file_handle:
            document = tomllib.load(file_handle)

        assets = document.get("assets")
        if assets is None:
            microgrids = document
        elif isinstance(assets, dict):
            microgrids = assets.get("microgrids", {})
        else:
            raise TypeError(f"{config_file}: `assets` must be a table")

        if not isinstance(microgrids, dict):
            raise TypeError(f"{config_file}: `assets.microgrids` must be a table")
        try:
            microgrid_ids.update(int(microgrid_id) for microgrid_id in microgrids)
        except ValueError as exc:
            raise ValueError(f"{config_file}: microgrid IDs must be integers") from exc

    return sorted(microgrid_ids)


@st.cache_resource(show_spinner=False)
def _load_microgrid_configs_cached(
    config_files: tuple[str, ...],
    revision: MicrogridConfigRevision,
) -> dict[int, MicrogridConfig]:
    """Load microgrid configs for one immutable set of file contents."""
    del revision
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
            configured_ids = _configured_microgrid_ids(config_files)
            accessible_microgrids = await assets_client.list_microgrids(
                microgrid_ids=(
                    MicrogridId(microgrid_id) for microgrid_id in configured_ids
                )
            )
            accessible_ids = sorted(
                int(microgrid.id) for microgrid in accessible_microgrids
            )
            assets_config = await load_configs(
                default_files=list(config_files),
                assets_client=assets_client,
                microgrid_ids=accessible_ids,
            )
            return assets_config.microgrids
        finally:
            await assets_client.disconnect()

    return asyncio.run(load())


def _last_good_config_source(config_root: Path) -> MicrogridConfigSource | None:
    """Return the last loaded source when it belongs to the configured directory."""
    with _CONFIG_SOURCE_LOCK:
        source = _LAST_GOOD_CONFIG_SOURCE
    if source is None or source[1][0] != str(config_root.resolve()):
        return None
    return source


def _remember_good_config_source(source: MicrogridConfigSource) -> None:
    """Remember a source only after all of its TOML files loaded successfully."""
    global _LAST_GOOD_CONFIG_SOURCE  # pylint: disable=global-statement
    with _CONFIG_SOURCE_LOCK:
        _LAST_GOOD_CONFIG_SOURCE = source


def _microgrid_config_source() -> MicrogridConfigSource:
    """Return configured TOML paths and a fingerprint of their current contents."""
    config_root = Path(
        os.getenv("MICROGRID_CONFIG_DIR", "frequenz_config_microgrid/assets/")
    )
    if not config_root.is_dir():
        raise RuntimeError(f"Microgrid config directory not found: {config_root}")

    config_paths = tuple(sorted(config_root.glob("*.toml")))
    try:
        file_revisions = tuple(
            (path.name, hashlib.sha256(path.read_bytes()).hexdigest())
            for path in config_paths
        )
    except FileNotFoundError:
        config_paths = ()

    if not config_paths:
        previous_source = _last_good_config_source(config_root)
        if previous_source is not None:
            return previous_source
        raise RuntimeError(f"No microgrid config files found in: {config_root}")

    config_files = tuple(str(path.resolve()) for path in config_paths)
    revision = (str(config_root.resolve()), file_revisions)
    return config_files, revision


def get_microgrid_config_revision() -> MicrogridConfigRevision:
    """Return a fingerprint that changes when the configured TOML files change."""
    _, revision = _microgrid_config_source()
    return revision


def _load_microgrid_configs() -> dict[int, MicrogridConfig]:
    """Load microgrid configs, reloading automatically after TOML changes.

    Returns:
        Mapping of microgrid IDs to configurations.
    """
    source = _microgrid_config_source()
    configs = _load_microgrid_configs_cached(*source)
    _remember_good_config_source(source)
    return configs


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

    The Assets API limits its response to the scope of the current credentials.
    Its response is therefore also used as an allow-list for the configured
    TOML microgrids.  Names and access are refreshed at most every five minutes.
    A configured TOML name is used when an accessible microgrid has no API name.
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
            microgrids = await assets_client.list_microgrids(
                microgrid_ids=(MicrogridId(microgrid_id) for microgrid_id in configs)
            )
            return {int(microgrid.id): microgrid.name for microgrid in microgrids}
        finally:
            await assets_client.disconnect()

    asset_names = asyncio.run(load())

    return {
        microgrid_id: asset_names[microgrid_id] or configured_name
        for microgrid_id, configured_name in names.items()
        if microgrid_id in asset_names
    }


def get_microgrid_names() -> dict[int, str | None]:
    """Return accessible microgrid names, invalidating after TOML changes."""
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
