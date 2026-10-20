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


_default_microgrids = os.getenv(
    "MICROGRID_CONFIG_DIR", "frequenz_config_microgrid/assets/"
)

CFG = AppConfig(paths=Paths(microgrids_dir=Path(_default_microgrids)))
