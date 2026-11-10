# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Tests for concurrent dataset loading on the reporting page."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from frequenz.cs_reporting.app_pages import reporting


def test_submitted_loads_run_concurrently() -> None:
    """Two loads must be in flight at the same time (barrier needs both)."""
    barrier = threading.Barrier(2, timeout=5)

    def load(value: int) -> int:
        barrier.wait()
        return value

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = (
            reporting._submit_with_script_context(  # pylint: disable=protected-access
                executor, load, 1
            )
        )
        second = (
            reporting._submit_with_script_context(  # pylint: disable=protected-access
                executor, load, 2
            )
        )
        assert (first.result(), second.result()) == (1, 2)


def test_submitted_load_error_is_raised_from_result() -> None:
    """A failing load surfaces when its result is read, not at submit time."""

    def fail() -> None:
        raise RuntimeError("boom")

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = (
            reporting._submit_with_script_context(  # pylint: disable=protected-access
                executor, fail
            )
        )
        with pytest.raises(RuntimeError, match="boom"):
            future.result()
