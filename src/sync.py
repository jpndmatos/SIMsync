"""
SIMsync CLI — sync event data from local CSVs to Brella.

Usage:
    python sync.py participants --csv data/participants.csv
    python sync.py participants --csv data/participants.csv --dry-run
    python sync.py speakers --csv data/speakers.csv
    python sync.py schedule --csv data/schedule.csv
"""

import argparse
import sys
from pathlib import Path


def cmd_participants(args):
    from api import prepare_csv, run_sync_v4

    csv_path = Path(args.csv)
    prepare_csv(csv_path, download_csv=False)
    run_sync_v4(
        csv_path,
        dry_run=args.dry_run,
        prune_missing=args.prune,
    )


def cmd_speakers(args):
    from speakers import run_speakers_sync
    run_speakers_sync(
        args.csv,
        dry_run=args.dry_run,
        prune_missing=getattr(args, "prune", False),
    )


def cmd_schedule(args):
    from schedule_sync import run_schedule_sync
    run_schedule_sync(
        args.csv,
        dry_run=args.dry_run,
        prune_missing=getattr(args, "prune", False),
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="sync",
        description="SIMsync — sync event CSVs to Brella.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- participants --
    p = sub.add_parser("participants", help="Sync participant list to Brella")
    p.add_argument("--csv", required=True, help="Path to participants CSV")
    p.add_argument("--dry-run", action="store_true", help="Preview without changes")
    p.add_argument("--prune", action="store_true", default=True,
                   help="Remove Brella invites not in CSV (default: on)")
    p.add_argument("--no-prune", dest="prune", action="store_false",
                   help="Keep Brella invites not in CSV")
    p.set_defaults(func=cmd_participants)

    # -- speakers --
    p = sub.add_parser("speakers", help="Sync speakers to Brella")
    p.add_argument("--csv", required=True, help="Path to speakers CSV")
    p.add_argument("--dry-run", action="store_true", help="Preview without changes")
    p.set_defaults(func=cmd_speakers)

    # -- schedule --
    p = sub.add_parser("schedule", help="Sync schedule to Brella")
    p.add_argument("--csv", required=True, help="Path to schedule CSV")
    p.add_argument("--dry-run", action="store_true", help="Preview without changes")
    p.add_argument("--prune", action="store_true", default=False,
                   help="Remove Brella timeslots not in CSV")
    p.add_argument("--no-prune", dest="prune", action="store_false")
    p.set_defaults(func=cmd_schedule)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as exc:
        print(f"\n[FATAL ERROR] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
