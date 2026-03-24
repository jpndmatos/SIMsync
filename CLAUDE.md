# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

3cket2brella imports event participants from 3cket (ticketing platform) into Brella (networking platform). It reads a semicolon-delimited CSV export from 3cket and syncs participants via the Brella REST API — creating, updating, and optionally pruning invites. The 3cket QR code replaces Brella's default QR.

The project is written in Portuguese (UI strings, log messages, README).

## Architecture

- **`api.py`** — all business logic: CSV parsing, Brella API calls (create/update/delete invites via `urllib`), ticket-type-to-attendee-group mapping, CSV download from 3cket, and the CLI entrypoint. Key functions: `run_sync_v4` (full import), `preview_sync_v4` (dry-run diff), `prepare_csv` (download + fallback). Configuration is loaded from `.env` / environment variables at module level. Uses only Python stdlib.
- **`docs/`** — static GitHub Pages dashboard (HTML/JS/CSS) that triggers GitHub Actions workflows via the GitHub API. User enters a PAT, clicks Preview or Import, and sees logs.
- **`.github/workflows/sync.yml`** — GitHub Actions workflow triggered by `workflow_dispatch`. Runs `python api.py` with flags from the dispatch inputs. Secrets (API keys, cookies) come from GitHub repo secrets.

## Commands

```bash
python api.py                          # full sync: create + update + prune
python api.py --dry-run                # preview only
python api.py --no-prune-missing       # sync without deleting
python api.py --no-download-csv        # skip 3cket CSV download
python api.py --limit N                # process only first N attendees
```

No test suite, no linter config, no package manager — stdlib only.

## Key Design Details

- **CSV format**: semicolon-delimited, UTF-8-BOM. Column indices are hardcoded (col 0 = 3cket ID / QR, col 1 = name, col 3 = email, col 10 = ticket types, col 12 = fallback email).
- **Ticket-to-group mapping**: `TICKET_TYPE_TO_GROUP_ID` maps normalized 3cket ticket names to Brella attendee group IDs. `GROUP_PRIORITY` resolves multiple tickets.
- **Matching logic**: participants matched by `external_id` (3cket row ID). Fetches all Brella invites via paginated API, builds lookup map, diffs against CSV.
- **HTTP**: all via `urllib.request` (no `requests`). Rate limiting via `REQUEST_DELAY_SECONDS`.
- **Environment**: all config from env vars (with a custom `.env` loader, not `python-dotenv`).
