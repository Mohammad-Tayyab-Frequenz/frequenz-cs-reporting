# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Convenience exports for data service factories."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client_factory import get_microgrid_client

__all__ = [
    "get_microgrid_client",
]


def __getattr__(name: str) -> object:
    """Load convenience exports lazily to avoid package initialization cycles."""
    if name != "get_microgrid_client":
        raise AttributeError(name)
    from .client_factory import (  # pylint: disable=import-outside-toplevel
        get_microgrid_client,
    )

    return get_microgrid_client
