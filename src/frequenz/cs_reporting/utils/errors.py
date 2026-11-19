# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Helpers for reporting errors without exposing internals to users."""

from __future__ import annotations

import logging
from uuid import uuid4

_logger = logging.getLogger(__name__)


def report_error(exc: BaseException, context: str) -> str:
    """Log an exception with a short id and return a user-facing reference.

    The full exception stays in the server log; users only see the id, which
    support can use to find the matching log entry.

    Args:
        exc: Exception to log.
        context: Short description of what failed, for the log entry.

    Returns:
        Text of the form ``(Fehler-ID: <id>)`` to append to a user message.
    """
    error_id = uuid4().hex[:8]
    _logger.error("%s (error id %s)", context, error_id, exc_info=exc)
    return f"(Fehler-ID: {error_id})"
