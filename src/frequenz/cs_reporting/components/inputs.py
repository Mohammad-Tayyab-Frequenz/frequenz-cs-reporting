# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Input widgets used across reporting pages."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Iterable, Literal, cast

import streamlit as st


def _resolve_container(container: Any | None) -> Any:
    """Return provided container or fallback to sidebar.

    Args:
        container: Optional Streamlit container to render inputs into.

    Returns:
        Provided container or ``st.sidebar`` when ``None``.
    """
    return container if container is not None else st.sidebar


# pylint: disable=too-many-arguments,too-many-positional-arguments
def microgrid_selector(
    label: str = "Microgrid-ID",
    ids: Iterable[int] = range(1, 2),
    format_func: Callable[[int], str] = str,
    key_prefix: str = "",
    container: Any | None = None,
    label_visibility: Literal["visible", "hidden", "collapsed"] = "visible",
) -> int:
    """Render a selectbox for choosing a microgrid ID.

    Args:
        label: UI label for the selector.
        ids: Iterable of available microgrid IDs.
        format_func: Function used to create an option's display label.
        key_prefix: Optional prefix for Streamlit widget keys.
        container: Optional Streamlit container to render into.
        label_visibility: Visibility mode for the selector label.

    Returns:
        Selected microgrid identifier.
    """
    target = _resolve_container(container)
    options: list[int] = list(ids)
    value = target.selectbox(
        label,
        options=options,
        index=0,
        format_func=format_func,
        key=f"{key_prefix}microgrid_id",
        label_visibility=label_visibility,
    )

    return cast(int, value)
