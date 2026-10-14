# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Command-line entry point for scheduled reporting-data synchronization."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime, timedelta

from frequenz.cs_reporting.services.data_service import (
    get_day_ahead_prices,
    get_microgrid_data,
    get_microgrid_soc_data,
)
from frequenz.cs_reporting.services.deepnote_cache import (
    deepnote_hybrid_cache_enabled,
    persist_deepnote_hybrid_cache,
    prepare_deepnote_hybrid_cache,
)


def _utc_datetime(value: str) -> datetime:
    """Parse an ISO timestamp and require an explicit timezone."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamps must include a timezone")
    return parsed.astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Synchronize reporting API ranges into the Parquet cache."
    )
    parser.add_argument("--microgrid-id", type=int, action="append")
    parser.add_argument("--start", type=_utc_datetime)
    parser.add_argument("--end", type=_utc_datetime)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--resolution-minutes", type=int, default=15)
    parser.add_argument(
        "--dataset",
        choices=("active-power", "battery-soc", "day-ahead-prices", "all"),
        default="active-power",
    )
    parser.add_argument(
        "--country-code",
        default="DE_LU",
        help="ENTSO-E bidding zone used for day-ahead prices (default: DE_LU).",
    )
    return parser


def main() -> None:
    """Synchronize configured datasets for use by cron or a platform scheduler."""
    use_hybrid_cache = deepnote_hybrid_cache_enabled() and any(
        key in os.environ
        for key in ("DEEPNOTE_PROJECT_ID", "DEEPNOTE_WORKSPACE_ID", "DEEPNOTE")
    )
    if use_hybrid_cache:
        prepare_deepnote_hybrid_cache()

    parser = _parser()
    args = parser.parse_args()
    end = args.end or datetime.now(tz=UTC)
    start = args.start or end - timedelta(days=args.lookback_days)
    resolution = timedelta(minutes=args.resolution_minutes)
    if start >= end:
        raise SystemExit("--start must be earlier than --end")
    if resolution <= timedelta(0):
        raise SystemExit("--resolution-minutes must be greater than zero")
    if args.dataset != "day-ahead-prices" and not args.microgrid_id:
        parser.error("--microgrid-id is required for the selected dataset")

    for microgrid_id in args.microgrid_id or []:
        if args.dataset in ("active-power", "all"):
            get_microgrid_data(microgrid_id, start, end, resolution)
        if args.dataset in ("battery-soc", "all"):
            get_microgrid_soc_data(microgrid_id, start, end, resolution)
    if args.dataset in ("day-ahead-prices", "all"):
        # The afternoon publication contains future prices. Keep tomorrow's
        # values so the dashboard remains covered until the next daily run.
        price_end = args.end or end + timedelta(days=1)
        get_day_ahead_prices(args.country_code, start, price_end)
    if use_hybrid_cache:
        persist_deepnote_hybrid_cache()


if __name__ == "__main__":
    main()
