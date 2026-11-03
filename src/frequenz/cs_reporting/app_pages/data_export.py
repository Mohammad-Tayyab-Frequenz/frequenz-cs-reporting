# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Page for exporting the predefined reporting datasets."""

from __future__ import annotations

from frequenz.cs_reporting.app_pages.reporting import render_data_export
from frequenz.cs_reporting.rep_cs_core.page_spec import PageSpec

PAGE = PageSpec(
    key="data_export",
    title="Datenexport",
    icon="",
    order=4,
    render=render_data_export,
)
