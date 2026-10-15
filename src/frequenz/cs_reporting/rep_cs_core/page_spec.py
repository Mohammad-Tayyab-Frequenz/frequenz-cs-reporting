# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Page specification dataclass used by Streamlit navigation."""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class PageSpec:
    """Page metadata used to build the navigation and render pages.

    Attributes:
        key: Unique identifier for the page, used in navigation state.
        title: Human-readable title shown in the sidebar.
        icon: Emoji or icon string used in the sidebar.
        order: Sorting order for the navigation list.
        render: Callable that renders the Streamlit page content.
    """

    key: str
    title: str
    icon: str
    order: int
    render: Callable[[], None]
