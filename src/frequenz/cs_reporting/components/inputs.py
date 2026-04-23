# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Input widgets used across reporting pages."""

from __future__ import annotations

from typing import Any, Iterable, cast

import streamlit as st


def _resolve_container(container: Any | None) -> Any:
    """Return provided container or fallback to sidebar.

    Args:
        container: Optional Streamlit container to render inputs into.

    Returns:
        Provided container or ``st.sidebar`` when ``None``.
    """
    return container if container is not None else st.sidebar


def microgrid_selector(
    label: str = "Microgrid-ID",
    ids: Iterable[int] = range(1, 2),
    key_prefix: str = "",
    container: Any | None = None,
) -> int:
    """Render a selectbox for choosing a microgrid ID.

    Args:
        label: UI label for the selector.
        ids: Iterable of available microgrid IDs.
        key_prefix: Optional prefix for Streamlit widget keys.
        container: Optional Streamlit container to render into.

    Returns:
        Selected microgrid identifier.
    """
    target = _resolve_container(container)
    options: list[int] = list(ids)
    value = target.selectbox(
        label, options=options, index=0, key=f"{key_prefix}microgrid_id"
    )

    return cast(int, value)
