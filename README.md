<h1><picture><source media="(prefers-color-scheme: dark)" srcset="docs/logo-dark.svg"><img src="docs/logo.svg" alt="SIMsync" width="400" height="72"></picture></h1>

A Windows desktop tool for importing event data from CSV files into Brella. Preview changes before syncing participants, speakers, and schedule sessions. It also includes group and ticket mappings, QR-code fixes, and activity logs.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/workflow-dark.svg">
  <img src="docs/workflow.svg" alt="Workflow diagram: select a CSV, preview changes, then sync to Brella" width="1180">
</picture>

## Use

Open `SIMsync.exe`, configure your event in **Setup**, then select a CSV in the relevant tab. Run **Preview**, review the results, and choose **Sync** when ready. Group and ticket mappings are stored in `config.json`.

The [usage guide](docs/usage.md) covers setup, CSV columns, group mappings, schedule updates, and QR-code repairs.

## Run from source

Python 3 with Tkinter. Runtime code uses the Python standard library.

```sh
python src/gui.py
```

Install PyInstaller to rebuild the Windows executable, then run `build.bat`. API credentials are configured locally in Setup and stored in `.env`.
