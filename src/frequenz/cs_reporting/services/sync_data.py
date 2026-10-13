# License: MIT
# Copyright © 2026 Frequenz Energy-as-a-Service GmbH

"""Command-line entry point for scheduled reporting-data synchronization."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta

from frequenz.cs_reporting.services.data_service import (
    get_microgrid_data,
    get_microgrid_soc_data,
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
    parser.add_argument("--microgrid-id", type=int, action="append", required=True)
    parser.add_argument("--start", type=_utc_datetime)
    parser.add_argument("--end", type=_utc_datetime)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--resolution-minutes", type=int, default=15)
    parser.add_argument(
        "--dataset",
        choices=("active-power", "battery-soc", "all"),
        default="active-power",
    )
    return parser


def main() -> None:
    """Synchronize configured datasets for use by cron or a platform scheduler."""
    args = _parser().parse_args()
    end = args.end or datetime.now(tz=UTC)
    start = args.start or end - timedelta(days=args.lookback_days)
    resolution = timedelta(minutes=args.resolution_minutes)
    if start >= end:
        raise SystemExit("--start must be earlier than --end")
    if resolution <= timedelta(0):
        raise SystemExit("--resolution-minutes must be greater than zero")

    for microgrid_id in args.microgrid_id:
        if args.dataset in ("active-power", "all"):
            get_microgrid_data(microgrid_id, start, end, resolution)
        if args.dataset in ("battery-soc", "all"):
            get_microgrid_soc_data(microgrid_id, start, end, resolution)


if __name__ == "__main__":
    main()
