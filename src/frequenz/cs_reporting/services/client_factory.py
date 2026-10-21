# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Factories for microgrid client creation and configuration loading."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
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

_logger = logging.getLogger(__name__)

MicrogridConfigRevision: TypeAlias = tuple[str, tuple[tuple[str, str], ...]]
MicrogridConfigSource: TypeAlias = tuple[tuple[str, ...], MicrogridConfigRevision]
ApiCredentialRevision: TypeAlias = str
_ASSETS_API_TIMEOUT_SECONDS = 20.0
_LAST_ASSET_NAMES: dict[str, dict[int, str | None]] = {}
_ENTERPRISE_IDS: dict[int, int] = {}


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


_MICROGRID_ID_PATTERN = re.compile(
    rb"^[ \t]*(?:\[{1,2}[ \t]*)?(?:(?:assets\.)?microgrids\.|(?=\d+\.[A-Za-z_]))(\d+)\b",
    re.MULTILINE,
)


def _microgrid_ids_in_file(config_file: str) -> set[int]:
    """Return microgrid IDs defined in a TOML file without parsing it."""
    with open(config_file, "rb") as handle:
        content = handle.read()
    return {
        int(match.group(1))
        for match in _MICROGRID_ID_PATTERN.finditer(content)
    }


@st.cache_resource(show_spinner=False)
def _microgrid_file_index_cached(
    config_files: tuple[str, ...],
) -> dict[int, tuple[str, ...]]:
    """Map each microgrid ID to the TOML files that define it.

    Files are scanned as plain text in parallel instead of being parsed,
    migrated and validated, which is what makes ``load_configs`` slow.
    """
    index: dict[int, list[str]] = {}
    with log_duration("client_factory.index_microgrid_files"):
        with ThreadPoolExecutor(max_workers=16) as executor:
            for config_file, ids in zip(
                config_files, executor.map(_microgrid_ids_in_file, config_files)
            ):
                for microgrid_id in ids:
                    index.setdefault(microgrid_id, []).append(config_file)
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
    with log_duration("client_factory.discover_config_files"):
        return _discover_config_source(config_root_value)


def _discover_config_source(config_root_value: str) -> MicrogridConfigSource:
    """Glob the TOML files and fingerprint their names."""
    config_root = Path(config_root_value)
    if not config_root.is_dir():
        raise RuntimeError(f"Microgrid config directory not found: {config_root}")

    resolved_root = config_root.resolve()
    with os.scandir(resolved_root) as entries:
        names = sorted(
            entry.name for entry in entries if entry.name.endswith(".toml")
        )
    if not names:
        raise RuntimeError(f"No microgrid config files found in: {config_root}")

    manifest = "\0".join(names).encode("utf-8")
    file_revisions = (("static-catalog", hashlib.sha256(manifest).hexdigest()),)
    config_files = tuple(str(resolved_root / name) for name in names)
    return config_files, (str(resolved_root), file_revisions)


def _config_root() -> str:
    """Return the configured TOML directory."""
    return os.getenv("MICROGRID_CONFIG_DIR", "frequenz_config_microgrid/assets/")


def _microgrid_config_source() -> MicrogridConfigSource:
    """Return the process-cached static TOML source."""
    return _microgrid_config_source_cached(_config_root())


def get_microgrid_config_revision() -> MicrogridConfigRevision:
    """Return the process-stable fingerprint of the static TOML catalog."""
    # The catalog is static for the lifetime of the process, so the directory
    # does not need to be listed just to build a cache key.
    return (str(Path(_config_root())), (("static-catalog", "process"),))


def _load_microgrid_config(microgrid_id: int) -> MicrogridConfig:
    """Return the cached configuration of one microgrid.

    Only the TOML files defining ``microgrid_id`` are loaded, so the cost does
    not grow with the size of the whole configuration directory.

    Raises:
        KeyError: If no TOML file defines the microgrid.
    """
    revision = get_microgrid_config_revision()
    files = _enterprise_config_files(microgrid_id)
    if files is None:
        config_files, _ = _microgrid_config_source()
        files = _microgrid_file_index_cached(config_files).get(microgrid_id)
    if not files:
        raise KeyError(f"Microgrid {microgrid_id} not found in configured microgrids.")
    return _load_microgrid_config_cached(microgrid_id, files, revision)


def _enterprise_config_files(microgrid_id: int) -> tuple[str, ...] | None:
    """Locate a microgrid's TOML file from its enterprise ID without scanning.

    Config files are named ``eid<enterprise_id>.toml``.  The Assets
    API provides each microgrid's enterprise ID, so the file can be opened
    directly.  Returns ``None`` when the convention does not hold, in which
    case the caller falls back to scanning the directory.
    """
    enterprise_id = _ENTERPRISE_IDS.get(microgrid_id)
    if not enterprise_id:
        _logger.warning(
            "No enterprise ID known for microgrid %s (known: %d); scanning config "
            "directory.",
            microgrid_id,
            len(_ENTERPRISE_IDS),
        )
        return None
    root = Path(_config_root())
    for name in (f"eid{enterprise_id}.toml", f"microgrids_eid{enterprise_id}.toml"):
        path = root / name
        try:
            with log_duration(f"client_factory.enterprise_lookup.{path.stem}"):
                found = microgrid_id in _microgrid_ids_in_file(str(path))
        except FileNotFoundError:
            continue
        except OSError as exc:
            _logger.warning("Cannot read %s: %s; scanning config directory.", path, exc)
            return None
        if found:
            return (str(path.resolve()),)
    _logger.warning(
        "Microgrid %s not found in eid%s.toml; scanning config directory.",
        microgrid_id,
        enterprise_id,
    )
    return None


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
            for microgrid in microgrids:
                enterprise_id = getattr(microgrid, "enterprise_id", None)
                if enterprise_id:
                    _ENTERPRISE_IDS[int(microgrid.id)] = int(enterprise_id)
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
