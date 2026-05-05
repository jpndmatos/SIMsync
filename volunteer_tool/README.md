# Volunteer Tool

Simple side-project app for volunteer use.

## Scope

- Participants only
- No speakers
- No schedule
- No pruning/removal from Brella
- Existing participants are skipped (add-only behavior)
- Duplicate people are not shown in the volunteer UI
- Can import only one participant by email (`Import Scope` -> `Only 1 email`)

## Run

From the repository root:

```bash
python volunteer_tool/volunteer_gui.py
```

## Standalone EXE

Build a separate volunteer executable:

```bat
build_volunteer.bat
```

Output:

- `volunteer_tool\standalone\VolunteerTool.exe`
- runtime files copied next to it (`.env`, `config.json`, `data\participants.csv` when available)

## Notes

- Uses the same `.env` and `config.json` as the main SIMsync project.
- Uses the same dark/pink visual style as the main SIMsync app.
- `Setup` now includes only the Connection section:
  - Integration API: `BRELLA_API_KEY`, `BRELLA_ORG_ID`, `BRELLA_EVENT_ID`
  - Admin Panel: `BRELLA_ADMIN_ACCESS_TOKEN`, `BRELLA_ADMIN_CLIENT`, `BRELLA_ADMIN_UID`
- Connection fields are preloaded from your current `.env` (your defaults), and Save writes back to `.env`.
- Default CSV path is `data/participants.csv`.
- "Preview only" lets volunteers validate what would be added before running import.
- If `Only 1 email` is selected, the tool filters the CSV and syncs only that email.
- Import screen is intentionally minimal for volunteers (no quick-add tuning controls).
