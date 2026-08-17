# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Streamlit view utilities and renderers.

Views are business/data-aware: they combine `frequenz.cs_reporting.components`
widgets with reporting data (tables, metrics, microgrid config) to render a
section of a page. Anything that needs to know about report-specific data
shapes belongs here rather than in `components`.
"""
