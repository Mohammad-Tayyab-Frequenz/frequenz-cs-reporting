# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Guard the home page background against bloating every render."""

from frequenz.cs_reporting.app_pages import home


def test_background_data_uri_stays_small() -> None:
    """The base64 background is inlined on each home render; keep it small."""
    encoded = home._b64_image(home.BACKGROUND_PATH)  # pylint: disable=protected-access
    assert encoded is not None
    assert len(encoded) < 1_000_000
