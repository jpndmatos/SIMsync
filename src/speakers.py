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


MAX_PHOTO_BYTES = 2 * 1024 * 1024  # 2MB — compress if larger


def _compress_image(image_data, mime, max_bytes=MAX_PHOTO_BYTES, log_callback=None):
    """Compress image to fit within max_bytes using stdlib subprocess + PowerShell."""
    if len(image_data) <= max_bytes:
        return image_data, mime

    import subprocess
    import tempfile

    # Write original to temp file
    ext = ".jpg" if "jpeg" in mime or "jpg" in mime else ".png"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as src:
        src.write(image_data)
        src_path = src.name
    out_path = src_path + "_resized.jpg"

    try:
        # Use PowerShell + .NET System.Drawing to resize
        ps_script = f"""
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile('{src_path}')
$ratio = [Math]::Min(1200.0 / $img.Width, 1200.0 / $img.Height)
if ($ratio -ge 1) {{ $ratio = 0.5 }}
$w = [int]($img.Width * $ratio)
$h = [int]($img.Height * $ratio)
$bmp = New-Object System.Drawing.Bitmap($w, $h)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.InterpolationMode = 'HighQualityBicubic'
$g.DrawImage($img, 0, 0, $w, $h)
$g.Dispose()
$img.Dispose()
$enc = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object {{ $_.MimeType -eq 'image/jpeg' }}
$params = New-Object System.Drawing.Imaging.EncoderParameters(1)
$params.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, 80L)
$bmp.Save('{out_path}', $enc, $params)
$bmp.Dispose()
"""
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, timeout=15,
        )
        if os.path.exists(out_path):
            with open(out_path, "rb") as f:
                compressed = f.read()
            emit(f"[INFO] Photo compressed: {len(image_data)//1024}KB → {len(compressed)//1024}KB",
                 log_callback=log_callback)
            return compressed, "image/jpeg"
    except Exception as e:
        emit(f"[WARN] Photo compression failed: {e}", log_callback=log_callback)
    finally:
        for p in (src_path, out_path):
            try:
                os.remove(p)
            except OSError:
                pass

    return image_data, mime  # return original if compression failed


def _download_photo(photo_url, log_callback=None):
    """Download photo from URL, return (image_data, mime) or (None, None)."""
    from urllib.parse import quote
    try:
        encoded_url = quote(photo_url, safe=':/?#[]@!$&\'()*+,;=-_.~')
        req = url_request.Request(encoded_url)
        resp = url_request.urlopen(req, timeout=15)
        image_data = resp.read()
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        if "jpeg" in content_type or "jpg" in content_type:
            mime = "image/jpeg"
        elif "png" in content_type:
            mime = "image/png"
        else:
            mime = content_type.split(";")[0].strip()
        return image_data, mime
    except Exception as e:
        emit(f"[WARN] Photo download failed: {e}", log_callback=log_callback)
        return None, None


def _upload_photo_base64(url, admin_hdrs, image_data, mime, log_callback=None):
    """Upload photo as base64 data URI in JSON payload."""
    import base64
    b64 = base64.b64encode(image_data).decode("ascii")
    data_uri = f"data:{mime};base64,{b64}"
    hdrs = dict(admin_hdrs)
    hdrs["Content-Type"] = "application/json"
    payload = json.dumps({"speaker": {"photo": data_uri}}).encode()
    req = url_request.Request(url, data=payload, headers=hdrs, method="PATCH")
    try:
        resp = url_request.urlopen(req)
        return resp.status
    except url_error.HTTPError as e:
        err_body = e.read().decode()[:300]
        emit(f"[WARN] Photo base64 failed ({len(image_data)//1024}KB): {e.code} {err_body}",
             log_callback=log_callback)
        return e.code


def _upload_photo_multipart(url, admin_hdrs, image_data, mime, filename, log_callback=None):
    """Upload photo as multipart/form-data."""
    import uuid
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="speaker[photo]"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode() + image_data + f"\r\n--{boundary}--\r\n".encode()
    hdrs = dict(admin_hdrs)
    hdrs["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    req = url_request.Request(url, data=body, headers=hdrs, method="PATCH")
    try:
        resp = url_request.urlopen(req)
        return resp.status
    except url_error.HTTPError as e:
        emit(f"[WARN] Photo multipart failed ({len(image_data)//1024}KB): {e.code}",
             log_callback=log_callback)
        return e.code


def _upload_speaker_photo(speaker_id, photo_url, log_callback=None):
    """Download photo from URL and upload to Brella via admin panel API."""
    from urllib.parse import urlparse

    admin_hdrs = _admin_headers()
    if not admin_hdrs:
        emit("[WARN] Photo upload skipped — admin tokens not set", log_callback=log_callback)
        return None

    image_data, mime = _download_photo(photo_url, log_callback=log_callback)
    if not image_data:
        return None

    # Compress oversized images
    image_data, mime = _compress_image(image_data, mime, log_callback=log_callback)

    event = os.environ.get("BRELLA_EVENT_ID", "10672")
    url = f"https://api.brella.io/api/admin_panel/events/{event}/speakers/{speaker_id}"
    filename = urlparse(photo_url).path.split("/")[-1] or "photo.jpg"

    # Try base64 first (works for most), fall back to multipart for large images
    sc = _upload_photo_base64(url, admin_hdrs, image_data, mime, log_callback=log_callback)
    if sc in (200, 201, 204):
        return sc

    # Fallback: multipart upload
    sc = _upload_photo_multipart(url, admin_hdrs, image_data, mime, filename, log_callback=log_callback)
    return sc


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
