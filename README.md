# SIMsync

SIMsync is a desktop tool for syncing event data from CSV files into Brella.
It can sync:

- participants
- speakers
- schedule sessions
- missing participant QR codes

## What is in this folder

- `SIMsync.exe` opens the app
- `config.json` stores attendee groups and ticket mapping rules
- `build.bat` rebuilds the executable after code changes
- `SIMsync.spec` stores the build configuration
- `src` contains the source code

For normal use, open `SIMsync.exe`.

## First setup

1. Open `SIMsync.exe`
2. Go to `Setup`
3. Fill in `API Key`
4. Fill in `Org ID`
5. Fill in `Event ID`
6. Also fill in `Access Token`, `Client`, and `UID`
7. Click `Save`
8. Click `Test`

If the test works, the app is connected to the event.

## Where to find the Brella values

### Event ID and Org ID

Open the event in Brella Manager and check the browser URL.
The event URL contains the `Event ID` and the `Org ID`.
Get it from an existing working setup, both values appear in the URL:

```text
https://api.brella.io/api/integration/organizations/1234/events/98765
```

In this example:

- `Org ID` is `1234`
- `Event ID` is `98765`

### API Key

The `API Key` is the Brella integration API key.
It must be created or provided by someone with access to the Brella organization settings or integration settings.
Use this key in the `API Key` field in `Setup`.
This key is required for:

- participants sync
- speakers sync
- schedule sync
- invite updates

### Admin Panel credentials

The Admin Panel credentials are only needed for some extra features:

- speaker photo upload
- schedule track updates
- schedule content updates through the admin endpoint

The fields are:

- `Access Token`
- `Client`
- `UID`

These values come from the authenticated Brella Manager session.
To find them in the browser:

1. Log in with an admin account that can access the event
2. Press `F12` to open Developer Tools
3. Go to the `Network` tab
4. Keep Developer Tools open and refresh Brella Manager
5. Click inside the event, for example open a speaker or schedule page
6. In the `Network` request list, click a request to `manager.brella.io` or `api.brella.io`
7. Open `Headers`
8. Look under `Request Headers`
9. Copy the values for `access-token`, `client`, and `uid`

Paste those values into SIMsync like this:

- `access-token` goes into `Access Token`
- `client` goes into `Client`
- `uid` goes into `UID`

If the request list is empty, make sure the red recording button in the `Network` tab is enabled and refresh the page again.
If the headers are not visible, click another Brella request from the list.
If you only need basic participant sync, you can leave these fields empty.

## Using SIMsync with another event

To use the tool with a different event:

1. Go to `Setup`
2. Replace `Org ID`
3. Replace `Event ID`
4. Replace `API Key`
5. Replace `Access Token`, `Client`, and `UID` if that event needs admin features
6. Click `Save`
7. Click `Test`

If the event has different attendee groups or ticket types, update `Groups & Tickets` in `Setup`.

## Participants

Use a participants CSV exported from 3cket.
Expected columns used by SIMsync: 3cket id or qr; full name; email; tickets; fallback email; company.

1. Go to `Participants`
2. Click `Browse`
3. Select the participants CSV
4. Click `Preview`
5. Check the results
6. Click `Sync`

Options:

- `Quick add` scans the CSV from the bottom and adds only new participants
- `Staff` syncs only staff tickets
- `Update` updates participants that already exist in Brella
- `Remove` removes Brella participants that are not in the CSV

Recommended flow:

1. Run `Preview`
2. Check the result boxes
3. Run `Sync`

## Speakers

Use a speakers CSV.
Expected columns used by SIMsync: first name; last name; company; job title; bio; photo url; contact email; speaker email; token; publish.

1. Go to `Speakers`
2. Click `Browse`
3. Select the speakers CSV
4. Click `Preview`
5. Check the results
6. Click `Sync`

Only rows marked as `Publish` are synced.
If the CSV has photo URLs, SIMsync tries to upload speaker photos using the Admin Panel credentials from `Setup`.

## Schedule

Use a schedule CSV.
Expected columns: date; start_time; duration; title; content; track; speakers; sync (optional).

Usage:

1. Go to `Schedule`
2. Click `Browse`
3. Select the schedule CSV
4. Click `Preview`
5. Check the results
6. Click `Sync`

Important:

- If a session time changes but the title stays the same, SIMsync tries to update the existing Brella session instead of creating a new one
- This helps keep existing RSVPs
- If two Brella sessions have the same title, SIMsync will not guess which one to update
- Run `Speakers` sync before `Schedule` sync if sessions need speaker assignments

## Debug

The `Debug` tab is used to inspect Brella invites and fix missing QR codes.
Use the same participants CSV as the `Participants` tab.
Expected columns used by SIMsync: 3cket id or qr; full name; email; tickets; fallback email; company.
Normal use:

1. Go to `Debug`
2. Click `Browse`
3. Select the participants CSV
4. Click `Refresh`
5. Select a participant
6. Click `Fix`

You can also double-click a row to manually edit the QR value.

## Logs and result boxes

The side panel shows the app log. It includes info, warnings, and errors.
The result boxes show:

- added
- updated
- skipped
- removed
- missing information
- duplicates

If something fails, check the log message. It usually explains what needs to be fixed.

## Rebuilding the executable

Only rebuild if someone changed files inside `src`.

1. Close `SIMsync.exe`
2. Run `build.bat`
3. Wait for the build to finish
4. Open the new `SIMsync.exe`
