# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SIMsync imports event data from local CSVs into Brella (networking platform) via the Brella REST API. It supports syncing participants, speakers, sponsors, and schedule — creating, updating, and optionally pruning entries. Participants, speakers, and schedule are fully implemented; sponsors is a stub.

The project is written in Portuguese (log messages, some UI strings).

## Architecture

- **`api.py`** — all participant sync logic: CSV parsing, Brella API calls (create/update/delete invites via `urllib`), ticket-type-to-attendee-group mapping, CSV download from 3cket. Key functions: `run_sync_v4` (full import), `preview_sync_v4` (dry-run diff), `prepare_csv` (download + fallback). Configuration from `.env` / environment variables. Uses only Python stdlib.
- **`speakers.py`** — speakers sync logic: comma-delimited Typeform CSV (only `Publish == "Publish"` rows), calls the Brella speakers API (`/speakers`) for speaker profiles AND the invites API for participant entries. `external_id` is the Typeform token (falls back to email). Imports helpers from `api.py`.
- **`schedule_sync.py`** — schedule sync logic: comma-delimited CSV (`date`, `start_time`, `duration`, `title`, `subtitle`, `content`, `location`, `tags`, `speakers`). Creates/updates Brella timeslots and assigns speakers by matching full names against existing Brella speaker profiles. `external_id` is slugified `subtitle`. Run speakers sync first.
- **`sync.py`** — CLI entrypoint with subcommands: `participants`, `speakers`, `schedule`, `sponsors`. Each takes `--csv` and `--dry-run`. Sponsors is a stub.
- **`gui.py`** — Local tkinter GUI with sidebar navigation, file pickers per sync type, dry-run/prune options, and a log panel. Runs the sync directly from the local machine.

## Commands

```bash
# CLI
python sync.py participants --csv data/participants.csv              # full sync
python sync.py participants --csv data/participants.csv --dry-run    # preview
python sync.py participants --csv data/participants.csv --no-prune   # sync without deleting

# GUI
python gui.py

# Legacy CLI (still works)
python api.py --csv participants.csv --dry-run --no-download-csv
```

No test suite, no linter config, no package manager — stdlib only.

## Key Design Details

- **CSV format**: semicolon-delimited, UTF-8-BOM. Column indices are hardcoded (col 0 = 3cket ID / QR, col 1 = name, col 3 = email, col 10 = ticket types, col 12 = fallback email).
- **Ticket-to-group mapping**: `TICKET_TYPE_TO_GROUP_ID` maps normalized 3cket ticket names to Brella attendee group IDs. `GROUP_PRIORITY` resolves multiple tickets.
- **Matching logic**: participants matched by `external_id` (3cket row ID). Fetches all Brella invites via paginated API, builds lookup map, diffs against CSV.
- **HTTP**: all via `urllib.request` (no `requests`). Rate limiting via `REQUEST_DELAY_SECONDS`.
- **Environment**: all config from env vars (with a custom `.env` loader, not `python-dotenv`).
