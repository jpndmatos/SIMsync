"""
Speakers sync — import published speakers from CSV into Brella as invites.

CSV format: comma-delimited Typeform export.
Only rows with Publish column == "Publish" are synced.
"""

import csv
import os
import time
from pathlib import Path

# Re-use Brella API plumbing from api.py
from api import (
    ORG_ID, EVENT_ID, API_KEY,
    build_url, build_update_url, build_delete_url,
    build_request_headers, preflight_check,
    create_invite, update_invite, delete_invite,
    find_invite_by_external_id, list_invites,
    extract_invite_external_id, extract_invite_email, extract_invite_name,
    emit,
    INVITES_URL_TEMPLATE, PREFLIGHT_URL_TEMPLATE,
    REQUEST_DELAY_SECONDS,
    BRELLA_ATTENDEE_GROUP_IDS,
)

SPEAKERS_GROUP_ID = BRELLA_ATTENDEE_GROUP_IDS.get("speakers", "36334")

# CSV column indices (comma-delimited Typeform export)
COL_FIRST_NAME = 0
COL_LAST_NAME = 1
COL_COMPANY = 2
COL_JOB_TITLE = 3
COL_BIO = 4
COL_SPEAKER_EMAIL = 10
COL_TOKEN = 15
COL_PUBLISH = 16


def parse_speakers_csv(csv_path, log_callback=None):
    """Parse speakers CSV, return list of (line_number, payload) for published speakers."""
    path = Path(csv_path)
    raw = path.read_bytes()
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    text = raw.decode("utf-8")

    records = []
    skipped = 0
    missing_info = []

    reader = csv.reader(text.splitlines(), delimiter=",")
    header = next(reader, None)  # skip header

    for line_num, row in enumerate(reader, start=2):
        if len(row) <= COL_PUBLISH:
            skipped += 1
            continue

        publish = row[COL_PUBLISH].strip()
        if publish.lower() != "publish":
            skipped += 1
            emit(f"[SKIP] line {line_num}: not published ({publish})", log_callback=log_callback)
            continue

        first_name = row[COL_FIRST_NAME].strip()
        last_name = row[COL_LAST_NAME].strip()
        email = row[COL_SPEAKER_EMAIL].strip()
        company = row[COL_COMPANY].strip()
        job_title = row[COL_JOB_TITLE].strip()
        token = row[COL_TOKEN].strip()

        if not email:
            missing_info.append(f"line {line_num}: {first_name} {last_name} (no email)")
            emit(f"[MISSING] line {line_num}: {first_name} {last_name} — no email, skipped",
                 log_callback=log_callback)
            continue

        external_id = token if token else email

        payload = {
            "event_invite": {
                "external_email": email,
                "external_id": external_id,
                "external_first_name": first_name,
                "external_last_name": last_name,
                "seats": 1,
                "external_company": company,
                "external_title": job_title,
                "attendee_group_id": SPEAKERS_GROUP_ID,
            },
            "import_interest_selections": False,
            "import_identity_selections": False,
        }

        records.append((line_num, payload))

    emit(f"Parsed {len(records)} published speakers, {skipped} skipped.",
         log_callback=log_callback)

    return records, missing_info


def run_speakers_sync(csv_path, dry_run=False, prune_missing=False, log_callback=None):
    """Sync speakers from CSV to Brella."""
    # Reload config from env
    import api
    api.API_KEY = os.environ.get("BRELLA_API_KEY", "")
    api.ORG_ID = os.environ.get("BRELLA_ORG_ID", "1218")
    api.EVENT_ID = os.environ.get("BRELLA_EVENT_ID", "10672")

    url = build_url(INVITES_URL_TEMPLATE)
    headers = build_request_headers()

    # Preflight
    preflight_url = build_url(PREFLIGHT_URL_TEMPLATE)
    status_code, response_text = preflight_check(preflight_url, headers)
    if status_code == 401:
        raise RuntimeError(f"Brella auth failed: {response_text}")
    if status_code not in (200, 201, 204):
        emit(f"[WARN] Preflight returned {status_code}: {response_text}", log_callback=log_callback)

    records, missing_info = parse_speakers_csv(csv_path, log_callback=log_callback)
    desired_external_ids = {r[1]["event_invite"]["external_id"] for r in records}

    added = []
    updated = []
    removed = []
    failed = 0

    for line_num, payload in records:
        email = payload["event_invite"]["external_email"]
        ext_id = payload["event_invite"]["external_id"]
        name = f"{payload['event_invite']['external_first_name']} {payload['event_invite']['external_last_name']}"

        if dry_run:
            emit(f"[PREVIEW] line {line_num}: {name} <{email}> -> group {SPEAKERS_GROUP_ID}",
                 log_callback=log_callback)
            continue

        try:
            invite_id = find_invite_by_external_id(headers, ext_id)
            if invite_id:
                status_code, resp = update_invite(build_update_url(invite_id), headers, payload)
                if status_code in (200, 201, 204):
                    updated.append(name)
                    emit(f"[OK] Updated: {name} <{email}>", log_callback=log_callback)
                else:
                    failed += 1
                    emit(f"[ERROR] line {line_num} update {email}: {status_code} - {resp}",
                         log_callback=log_callback)
            else:
                status_code, resp = create_invite(url, headers, payload)
                if status_code in (200, 201, 204):
                    added.append(name)
                    emit(f"[OK] Created: {name} <{email}>", log_callback=log_callback)
                else:
                    failed += 1
                    emit(f"[ERROR] line {line_num} create {email}: {status_code} - {resp}",
                         log_callback=log_callback)

            time.sleep(REQUEST_DELAY_SECONDS)

        except Exception as exc:
            failed += 1
            emit(f"[ERROR] line {line_num} {email}: {exc}", log_callback=log_callback)

    # Prune speakers not in CSV
    if prune_missing:
        emit("Checking for speakers to prune...", log_callback=log_callback)
        existing = list_invites(headers)
        for invite in existing:
            inv_id = invite.get("id") if isinstance(invite, dict) else None
            ext_id = extract_invite_external_id(invite)
            group = invite.get("attendee_group_id") or invite.get("attendee_group", {}).get("id")

            if not inv_id or not ext_id:
                continue
            if str(group) != str(SPEAKERS_GROUP_ID):
                continue
            if ext_id in desired_external_ids:
                continue

            name = extract_invite_name(invite)
            email = extract_invite_email(invite)

            if dry_run:
                emit(f"[PREVIEW] Would remove: {name} <{email}> (ext_id: {ext_id})",
                     log_callback=log_callback)
                removed.append(name or ext_id)
            else:
                sc, resp = delete_invite(build_delete_url(inv_id), headers)
                if sc in (200, 202, 204):
                    removed.append(name or ext_id)
                    emit(f"[OK] Removed: {name} <{email}>", log_callback=log_callback)
                else:
                    failed += 1
                    emit(f"[ERROR] Remove {ext_id}: {sc} - {resp}", log_callback=log_callback)
                time.sleep(REQUEST_DELAY_SECONDS)

    processed = len(records)
    emit(f"Done. Processed: {processed}, Added: {len(added)}, Updated: {len(updated)}, "
         f"Removed: {len(removed)}, Failed: {failed}, Missing info: {len(missing_info)}",
         log_callback=log_callback)

    return {
        "processed": processed,
        "added_participants": added,
        "updated_participants": updated,
        "removed_participants": removed,
        "missing_email_participants": missing_info,
        "failed": failed,
    }
