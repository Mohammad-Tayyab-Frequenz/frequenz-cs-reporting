"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _entsoe_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide a dummy ENTSO-E key so tests never depend on the environment."""
    monkeypatch.setenv("ENTSOE_API_KEY", "test-key")
