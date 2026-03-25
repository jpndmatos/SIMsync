"""
Speakers sync — import published speakers from CSV into Brella's speakers section.

Uses the Brella speakers API (not invites):
  GET    /speakers           — list all speakers
  POST   /speakers           — create speaker
  PATCH  /speakers/{id}      — update speaker
  DELETE /speakers/{id}      — delete speaker

CSV format: comma-delimited Typeform export.
Only rows with Publish column == "Publish" are synced.
"""

import csv
import json
import os
import time
from pathlib import Path
from urllib import request as url_request, error as url_error

from api import (
    build_request_headers, emit,
    build_url, build_update_url,
    create_invite, update_invite,
    find_invite_by_external_id,
    REQUEST_DELAY_SECONDS,
    INVITES_URL_TEMPLATE,
    BRELLA_ATTENDEE_GROUP_IDS,
)

SPEAKERS_GROUP_ID = BRELLA_ATTENDEE_GROUP_IDS.get("speakers", "36334")

# CSV column indices (comma-delimited Typeform export)
COL_FIRST_NAME = 0
COL_LAST_NAME = 1
COL_COMPANY = 2
COL_JOB_TITLE = 3
COL_BIO = 4
COL_PHOTO = 7
COL_LINKEDIN = 8
COL_SPEAKER_EMAIL = 10
COL_TOKEN = 15
COL_PUBLISH = 16


def _speakers_url(speaker_id=None):
    org = os.environ.get("BRELLA_ORG_ID", "1218")
    event = os.environ.get("BRELLA_EVENT_ID", "10672")
    base = f"https://api.brella.io/api/integration/organizations/{org}/events/{event}/speakers"
    if speaker_id:
        return f"{base}/{speaker_id}"
    return base


def _api_call(url, headers, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload else None
    req = url_request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = url_request.urlopen(req)
        body = resp.read().decode()
        return resp.status, json.loads(body) if body else {}
    except url_error.HTTPError as e:
        body = e.read().decode()
        return e.code, body


def _admin_headers():
    """Build DeviseTokenAuth headers for the Brella admin panel API."""
    token = os.environ.get("BRELLA_ADMIN_ACCESS_TOKEN", "")
    client = os.environ.get("BRELLA_ADMIN_CLIENT", "")
    uid = os.environ.get("BRELLA_ADMIN_UID", "")
    if not (token and client and uid):
        return None
    return {
        "access-token": token,
        "client": client,
        "uid": uid,
        "token-type": "Bearer",
        "Accept": "application/vnd.brella.v4+json",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://manager.brella.io",
        "Referer": "https://manager.brella.io/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) "
            "Gecko/20100101 Firefox/151.0"
        ),
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
    }


def _upload_speaker_photo(speaker_id, photo_url, log_callback=None):
    """Download photo from URL and upload to Brella via admin panel API (base64 data URI)."""
    import base64
    from urllib.parse import quote

    admin_hdrs = _admin_headers()
    if not admin_hdrs:
        emit("[WARN] Photo upload skipped — admin tokens not set", log_callback=log_callback)
        return None

    # Download the image
    try:
        encoded_url = quote(photo_url, safe=':/?#[]@!$&\'()*+,;=-_.~')
        req = url_request.Request(encoded_url)
        resp = url_request.urlopen(req, timeout=15)
        image_data = resp.read()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        # Normalize content type
        if "jpeg" in content_type or "jpg" in content_type:
            mime = "image/jpeg"
        elif "png" in content_type:
            mime = "image/png"
        else:
            mime = content_type.split(";")[0].strip()
    except Exception as e:
        emit(f"[WARN] Photo download failed: {e}", log_callback=log_callback)
        return None

    # Convert to base64 data URI
    b64 = base64.b64encode(image_data).decode("ascii")
    data_uri = f"data:{mime};base64,{b64}"

    # PATCH via admin panel API with base64 photo
    event = os.environ.get("BRELLA_EVENT_ID", "10672")
    url = f"https://api.brella.io/api/admin_panel/events/{event}/speakers/{speaker_id}"
    admin_hdrs["Content-Type"] = "application/json"
    payload = json.dumps({"speaker": {"photo": data_uri}}).encode()

    req = url_request.Request(url, data=payload, headers=admin_hdrs, method="PATCH")
    try:
        resp = url_request.urlopen(req)
        return resp.status
    except url_error.HTTPError as e:
        err_body = e.read().decode()[:300]
        emit(f"[WARN] Photo upload (base64): {e.code} {err_body}", log_callback=log_callback)
        # Fallback: try field name "photo_url" with data URI
        try:
            payload2 = json.dumps({"speaker": {"photo_url": data_uri}}).encode()
            req2 = url_request.Request(url, data=payload2, headers=admin_hdrs, method="PATCH")
            resp2 = url_request.urlopen(req2)
            return resp2.status
        except url_error.HTTPError as e2:
            emit(f"[WARN] Photo upload (photo_url): {e2.code} {e2.read().decode()[:200]}",
                 log_callback=log_callback)
            return e2.code


def list_speakers(headers):
    status, data = _api_call(_speakers_url(), headers)
    if status != 200:
        raise RuntimeError(f"Failed to list speakers: {status}")
    return data.get("data", [])


def create_speaker(headers, speaker_data):
    return _api_call(_speakers_url(), headers, method="POST",
                     payload={"speaker": speaker_data})


def update_speaker(headers, speaker_id, speaker_data):
    return _api_call(_speakers_url(speaker_id), headers, method="PATCH",
                     payload={"speaker": speaker_data})


def delete_speaker(headers, speaker_id):
    return _api_call(_speakers_url(speaker_id), headers, method="DELETE")


def parse_speakers_csv(csv_path, log_callback=None):
    path = Path(csv_path)
    raw = path.read_bytes()
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    text = raw.decode("utf-8")

    records = []
    skipped = 0
    missing_info = []

    reader = csv.reader(text.splitlines(), delimiter=",")
    next(reader, None)  # skip header

    for line_num, row in enumerate(reader, start=2):
        if len(row) <= COL_PUBLISH:
            skipped += 1
            continue

        publish = row[COL_PUBLISH].strip()
        if publish.lower() != "publish":
            skipped += 1
            emit(f"[SKIP] line {line_num}: not published ({publish or 'empty'})",
                 log_callback=log_callback)
            continue

        first_name = row[COL_FIRST_NAME].strip()
        last_name = row[COL_LAST_NAME].strip()
        email = row[COL_SPEAKER_EMAIL].strip() if len(row) > COL_SPEAKER_EMAIL else ""
        company = row[COL_COMPANY].strip()
        job_title = row[COL_JOB_TITLE].strip()
        bio = row[COL_BIO].strip() if len(row) > COL_BIO else ""
        photo_url = row[COL_PHOTO].strip() if len(row) > COL_PHOTO else ""
        token = row[COL_TOKEN].strip()

        if not email:
            missing_info.append(f"line {line_num}: {first_name} {last_name} (no email)")
            emit(f"[MISSING] line {line_num}: {first_name} {last_name} — no email, skipped",
                 log_callback=log_callback)
            continue

        external_id = token if token else email

        speaker_data = {
            "first_name": first_name,
            "last_name": last_name,
            "company_name": company,
            "job_title": job_title,
            "bio": bio,
            "external_id": external_id,
        }

        records.append((line_num, speaker_data, f"{first_name} {last_name}", email, photo_url))

    emit(f"Parsed {len(records)} published speakers, {skipped} skipped.",
         log_callback=log_callback)

    return records, missing_info


def _build_invite_payload(speaker_data, email, ext_id):
    """Build a Brella invite payload for the speaker (participant entry)."""
    return {
        "event_invite": {
            "external_email": email,
            "external_id": ext_id,
            "external_first_name": speaker_data["first_name"],
            "external_last_name": speaker_data["last_name"],
            "seats": 1,
            "external_company": speaker_data.get("company_name", ""),
            "attendee_group_id": SPEAKERS_GROUP_ID,
        },
        "import_interest_selections": False,
        "import_identity_selections": False,
    }


def run_speakers_sync(csv_path, dry_run=False, prune_missing=False, log_callback=None):
    # Reload config
    import api
    api.API_KEY = os.environ.get("BRELLA_API_KEY", "")
    api.ORG_ID = os.environ.get("BRELLA_ORG_ID", "1218")
    api.EVENT_ID = os.environ.get("BRELLA_EVENT_ID", "10672")

    headers = build_request_headers()
    invite_headers = dict(headers)
    headers["Content-Type"] = "application/json"

    invites_url = build_url(INVITES_URL_TEMPLATE)

    records, missing_info = parse_speakers_csv(csv_path, log_callback=log_callback)

    # Build external_id -> brella speaker map
    existing_speakers = list_speakers(headers)
    existing_map = {}  # external_id -> speaker dict
    for sp in existing_speakers:
        ext_id = sp.get("attributes", {}).get("external-id")
        if ext_id:
            existing_map[ext_id] = sp

    emit(f"Found {len(existing_speakers)} existing speakers in Brella ({len(existing_map)} with external_id).",
         log_callback=log_callback)

    desired_external_ids = set()
    added = []
    updated = []
    removed = []
    failed = 0

    for line_num, speaker_data, name, email, photo_url in records:
        ext_id = speaker_data["external_id"]
        desired_external_ids.add(ext_id)

        if dry_run:
            action = "UPDATE" if ext_id in existing_map else "CREATE"
            emit(f"[PREVIEW] line {line_num}: {action} {name} <{email}> (speaker + participant)",
                 log_callback=log_callback)
            if action == "CREATE":
                added.append(name)
            else:
                updated.append(name)
            continue

        try:
            # --- Speaker profile ---
            sp_id = None
            if ext_id in existing_map:
                sp_id = existing_map[ext_id]["id"]
                status, resp = update_speaker(headers, sp_id, speaker_data)
                if status in (200, 201, 204):
                    updated.append(name)
                    emit(f"[OK] Speaker updated: {name}", log_callback=log_callback)
                else:
                    failed += 1
                    emit(f"[ERROR] line {line_num} speaker update: {status}",
                         log_callback=log_callback)
            else:
                status, resp = create_speaker(headers, speaker_data)
                if status in (200, 201, 204):
                    added.append(name)
                    sp_id = resp.get("data", {}).get("id") if isinstance(resp, dict) else None
                    emit(f"[OK] Speaker created: {name} (id: {sp_id})", log_callback=log_callback)
                else:
                    failed += 1
                    emit(f"[ERROR] line {line_num} speaker create: {status} {resp}",
                         log_callback=log_callback)

            # --- Upload photo via admin panel API ---
            if sp_id and photo_url:
                sc = _upload_speaker_photo(sp_id, photo_url, log_callback=log_callback)
                if sc and sc in (200, 201, 204):
                    emit(f"[OK] Photo uploaded: {name}", log_callback=log_callback)

            time.sleep(REQUEST_DELAY_SECONDS)

            # --- Participant invite ---
            invite_payload = _build_invite_payload(speaker_data, email, ext_id)
            invite_id = find_invite_by_external_id(invite_headers, ext_id)
            if invite_id:
                sc, _ = update_invite(build_update_url(invite_id), invite_headers, invite_payload)
                if sc in (200, 201, 204):
                    emit(f"[OK] Participant updated: {name} <{email}>", log_callback=log_callback)
                else:
                    emit(f"[WARN] Participant update {email}: {sc}", log_callback=log_callback)
            else:
                sc, _ = create_invite(invites_url, invite_headers, invite_payload)
                if sc in (200, 201, 204):
                    emit(f"[OK] Participant created: {name} <{email}>", log_callback=log_callback)
                else:
                    emit(f"[WARN] Participant create {email}: {sc}", log_callback=log_callback)

            time.sleep(REQUEST_DELAY_SECONDS)

        except Exception as exc:
            failed += 1
            emit(f"[ERROR] line {line_num} {email}: {exc}", log_callback=log_callback)

    # Prune: remove speakers in Brella that are not in the CSV
    if prune_missing:
        emit("Checking for speakers to prune...", log_callback=log_callback)
        for ext_id, sp in existing_map.items():
            if ext_id in desired_external_ids:
                continue

            sp_id = sp["id"]
            attrs = sp.get("attributes", {})
            name = f"{attrs.get('first-name', '')} {attrs.get('last-name', '')}".strip()

            if dry_run:
                emit(f"[PREVIEW] Would remove: {name} (ext_id: {ext_id})",
                     log_callback=log_callback)
                removed.append(name or ext_id)
            else:
                status, resp = delete_speaker(headers, sp_id)
                if status in (200, 202, 204):
                    removed.append(name or ext_id)
                    emit(f"[OK] Removed: {name}", log_callback=log_callback)
                else:
                    failed += 1
                    emit(f"[ERROR] Remove {ext_id}: {status}", log_callback=log_callback)
                time.sleep(REQUEST_DELAY_SECONDS)

    processed = len(records)
    emit(f"Done. Processed: {processed}, Created: {len(added)}, Updated: {len(updated)}, "
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
