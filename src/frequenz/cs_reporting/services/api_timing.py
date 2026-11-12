# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Per-stage timing of the Reporting API client, for diagnosing slow loads.

``MicrogridData.metric_data`` runs one aggregated stream per component type,
then a per-component pass, then pandas post-processing, all sequentially.  The
library is not ours to change, so the stages are timed by wrapping the client
instance.  Behaviour and results are unchanged.

In the duration log, post-processing is what remains of ``api.metric_data``
after subtracting the ``api.aggregated_stream`` and
``api.component_metric_data`` entries.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from frequenz.cs_reporting.utils.timing import (
    log_duration,
    log_timing_note,
    timing_enabled,
)

_logger = logging.getLogger(__name__)

_MARKER = "_cs_reporting_timed"


def _timed_call(name: str, method: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an async method so its whole duration is logged."""

    @functools.wraps(method)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        with log_duration(name):
            return await method(*args, **kwargs)

    setattr(wrapper, _MARKER, True)
    return wrapper


def _timed_stream(name: str, method: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap an async generator method; log its duration and sample count."""

    @functools.wraps(method)
    async def wrapper(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        samples = 0
        with log_duration(name):
            async for sample in method(*args, **kwargs):
                samples += 1
                yield sample
        log_timing_note(f"{name} samples={samples}")

    setattr(wrapper, _MARKER, True)
    return wrapper


def _wrap(
    target: Any, attribute: str, wrapper_factory: Callable[..., Any], name: str
) -> None:
    method = getattr(target, attribute, None)
    if method is None:
        # These are private upstream attributes; a rename would otherwise drop
        # the timing and skew the post-processing figure without notice.
        _logger.warning(
            "Cannot time %s: %s has no attribute %r (upstream renamed?).",
            name,
            type(target).__name__,
            attribute,
        )
        return
    if getattr(method, _MARKER, False):
        return
    setattr(target, attribute, wrapper_factory(name, method))


def instrument_client(client: Any) -> None:
    """Time the stages of a ``MicrogridData`` client in place (idempotent).

    Does nothing unless ``CS_REPORTING_TIMING`` is set, so the client is left
    unwrapped in normal operation.
    """
    if not timing_enabled():
        return
    _wrap(client, "metric_data", _timed_call, "api.metric_data")
    _wrap(client, "_component_metric_data", _timed_call, "api.component_metric_data")
    inner = getattr(client, "_client", None)
    if inner is None:
        _logger.warning(
            "Cannot time API streams: %s has no attribute '_client' "
            "(upstream renamed?).",
            type(client).__name__,
        )
    else:
        _wrap(inner, "receive_aggregated_data", _timed_stream, "api.aggregated_stream")
        _wrap(
            inner,
            "receive_microgrid_components_data",
            _timed_stream,
            "api.component_stream",
        )
