# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Helpers for determining component-dependent feature availability."""

from functools import lru_cache

from frequenz.cs_reporting.services.client_factory import (
    MicrogridConfigRevision,
    get_component_types,
    get_microgrid_config_revision,
    get_microgrid_ids,
)


def get_microgrid_ids_with_component(component_type: str) -> tuple[int, ...]:
    """Return accessible microgrid IDs that contain ``component_type``."""
    microgrid_ids = tuple(get_microgrid_ids())
    return _get_microgrid_ids_with_component_cached(
        component_type,
        microgrid_ids,
        get_microgrid_config_revision(),
    )


@lru_cache(maxsize=32)
def _get_microgrid_ids_with_component_cached(
    component_type: str,
    microgrid_ids: tuple[int, ...],
    config_revision: MicrogridConfigRevision,
) -> tuple[int, ...]:
    """Cache component availability across Streamlit reruns."""
    del config_revision
    return tuple(
        microgrid_id
        for microgrid_id in microgrid_ids
        if component_type in get_component_types(microgrid_id)
    )
