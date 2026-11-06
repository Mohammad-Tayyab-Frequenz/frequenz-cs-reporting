# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Configuration helpers for the reporting core package."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    """Filesystem paths used by the reporting app configuration.

    Attributes:
        microgrids_dir: Root directory containing microgrid configuration files.
    """

    microgrids_dir: Path


@dataclass(frozen=True)
class AppConfig:
    """Container for library configuration.

    Attributes:
        paths: Paths configuration values.
    """

    paths: Paths


_PACKAGED_MICROGRIDS_DIR = Path("frequenz_config_microgrid/assets/")
_LEGACY_MICROGRIDS_DIR = Path("toml_directory/")


def microgrid_config_dir() -> Path:
    """Return the configured microgrid TOML directory.

    An explicit environment setting takes precedence.  Otherwise, prefer the
    packaged configuration directory and retain the legacy directory as a
    fallback for deployments that do not provide it.
    """
    if (configured_dir := os.getenv("MICROGRID_CONFIG_DIR")) is not None:
        return Path(configured_dir)
    if _PACKAGED_MICROGRIDS_DIR.is_dir():
        return _PACKAGED_MICROGRIDS_DIR
    return _LEGACY_MICROGRIDS_DIR


CFG = AppConfig(paths=Paths(microgrids_dir=microgrid_config_dir()))
