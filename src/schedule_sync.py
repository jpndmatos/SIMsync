"""
Schedule sync — import sessions from CSV into Brella's schedule.

CSV format: comma-delimited with headers:
  date, start_time, duration, title, content, track, location, speakers

- date: YYYY-MM-DD
- start_time: HH:MM or HH:MM:SS
- duration: integer minutes
- title: session name (used as external_id key)
- content: session description
- track: stage/track name (e.g., SIM STAGE, STARTUP STUDIO)
- location: physical venue/room name
- speakers: full names separated by " / "

Speaker assignment matches names against Brella speaker profiles.
Run speakers sync first to ensure all speakers exist in Brella.
"""

import csv
import gzip
import json
import os
import re
import time
from pathlib import Path
from urllib import request as url_request, error as url_error

from api import build_request_headers, emit, REQUEST_DELAY_SECONDS


def _timeslots_url(org, event, timeslot_id=None, suffix=None):
    base = (
        f"https://api.brella.io/api/integration/organizations/{org}"
        f"/events/{event}/timeslots"
    )
    if timeslot_id:
        url = f"{base}/{timeslot_id}"
        return f"{url}/{suffix}" if suffix else url
    return base


def _api_call(url, headers, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload else None
    req = url_request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = url_request.urlopen(req)
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        body = raw.decode("utf-8", errors="replace")
        return resp.status, json.loads(body) if body else {}
    except url_error.HTTPError as e:
        raw = e.read()
        try:
            if e.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            body = raw.decode("utf-8", errors="replace")
        except Exception:
            body = repr(raw)
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
        "Content-Type": "application/json",
        "Origin": "https://manager.brella.io",
        "Referer": "https://manager.brella.io/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) "
            "Gecko/20100101 Firefox/151.0"
        ),
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "DNT": "1",
        "TE": "trailers",
    }


def _extract_items_from_response(data):
    """Extract items from an API response (list or dict with known keys)."""
    if isinstance(data, list) and data:
        return data
    if isinstance(data, dict):
        items = (data.get("data") or data.get("tags")
                 or data.get("session_types") or data.get("items") or [])
        if items:
            return items
    return None


def list_timeslots(headers, org, event):
    status, data = _api_call(_timeslots_url(org, event), headers)
    if status != 200:
        raise RuntimeError(f"Failed to list timeslots: {status} {data}")
    return data.get("data", [])


def create_timeslot(headers, org, event, payload):
    return _api_call(_timeslots_url(org, event), headers, method="POST",
                     payload={"timeslot": payload})


def update_timeslot(headers, org, event, timeslot_id, payload):
    return _api_call(_timeslots_url(org, event, timeslot_id), headers, method="PATCH",
                     payload={"timeslot": payload})


def _to_draftjs(text):
    """Convert plain text to DraftJS RawContentState (one block per non-empty line)."""
    import uuid
    blocks = []
    for line in text.splitlines():
        blocks.append({
            "key": uuid.uuid4().hex[:5],
            "text": line.strip(),
            "type": "unstyled",
            "depth": 0,
            "inlineStyleRanges": [],
            "entityRanges": [],
            "data": {},
        })
    if not blocks:
        blocks = [{"key": uuid.uuid4().hex[:5], "text": "", "type": "unstyled",
                   "depth": 0, "inlineStyleRanges": [], "entityRanges": [], "data": {}}]
    return {"blocks": blocks, "entityMap": {}}


def list_stages(event, log_callback=None):
    """Fetch tracks from Brella admin panel API (/tracks endpoint)."""
    admin_hdrs = _admin_headers()
    if not admin_hdrs:
        return []
    url = f"https://api.brella.io/api/admin_panel/events/{event}/tracks"
    status, data = _api_call(url, admin_hdrs)
    if status == 200:
        items = _extract_items_from_response(data)
        return items if items else []
    return []


def _build_stage_name_map(stages):
    """Build normalized name -> track dict from Brella tracks list."""
    stage_map = {}
    for s in stages:
        if isinstance(s, dict):
            name = s.get("attributes", {}).get("name", s.get("name", "")).strip()
            if name:
                stage_map[name.lower()] = s
    return stage_map


def _admin_patch_timeslot(event, timeslot_id, patches, log_callback=None):
    """Single admin panel PATCH covering content (description) and stage_id."""
    admin_hdrs = _admin_headers()
    if not admin_hdrs or not patches:
        return
    url = f"https://api.brella.io/api/admin_panel/events/{event}/timeslots/{timeslot_id}"
    sc, sr = _api_call(url, admin_hdrs, method="PATCH", payload={"timeslot": patches})
    if sc not in (200, 201, 204):
        emit(f"[WARN] Admin patch: {sc} {str(sr)[:300]}", log_callback=log_callback)
    return sc, sr


def delete_timeslot(headers, org, event, timeslot_id):
    return _api_call(_timeslots_url(org, event, timeslot_id), headers, method="DELETE")


def list_timeslot_speakers(headers, org, event, timeslot_id):
    status, data = _api_call(_timeslots_url(org, event, timeslot_id, "speakers"), headers)
    if status != 200:
        return []
    return data.get("data", [])


def assign_speaker(headers, org, event, timeslot_id, speaker_id):
    sc, sr = _api_call(_timeslots_url(org, event, timeslot_id, "speakers"), headers,
                       method="POST", payload={"speaker_id": speaker_id})
    if sc not in (404, 405):
        return sc, sr
    sc, sr = _api_call(_timeslots_url(org, event, timeslot_id, "speakers"), headers,
                       method="POST", payload={"timeslot_speaker": {"speaker_id": speaker_id}})
    if sc not in (404, 405):
        return sc, sr
    return _api_call(_timeslots_url(org, event, timeslot_id, "speakers"), headers,
                     method="POST", payload={"speaker_profile_id": speaker_id})


def remove_speaker_assignment(headers, org, event, timeslot_id, assignment_id):
    return _api_call(
        _timeslots_url(org, event, timeslot_id, f"speakers/{assignment_id}"),
        headers, method="DELETE",
    )


def _make_external_id(subtitle):
    slug = subtitle.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:100]


def _build_start_time(date_str, time_str):
    time_str = time_str.strip()
    if time_str.count(":") == 1:
        time_str += ":00"
    return f"{date_str} {time_str}"


def _build_end_time(start_time_str, duration_minutes):
    from datetime import datetime, timedelta
    dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
    dt_end = dt + timedelta(minutes=duration_minutes)
    return dt_end.strftime("%Y-%m-%d %H:%M:%S")


def _build_speaker_name_map(existing_speakers):
    """Build normalized 'first last' -> speaker dict from Brella speakers list."""
    name_map = {}
    for sp in existing_speakers:
        attrs = sp.get("attributes", {})
        first = attrs.get("first-name", "").strip()
        last = attrs.get("last-name", "").strip()
        full = f"{first} {last}".strip().lower()
        if full:
            name_map[full] = sp
    return name_map


def parse_schedule_csv(csv_path, log_callback=None):
    path = Path(csv_path)
    raw = path.read_bytes()
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    text = raw.decode("utf-8")

    records = []
    skipped = 0

    reader = csv.DictReader(text.splitlines())
    for line_num, row in enumerate(reader, start=2):
        # Filter by sync column
        sync_flag = row.get("sync", "TRUE").strip().upper()
        if sync_flag == "FALSE":
            skipped += 1
            continue

        date = row.get("date", "").strip()
        start_time = row.get("start_time", "").strip()
        title = row.get("title", "").strip()

        if not date or not start_time or not title:
            skipped += 1
            emit(f"[SKIP] line {line_num}: missing date, start_time or title",
                 log_callback=log_callback)
            continue

        duration_str = row.get("duration", "0").strip()
        try:
            duration = int(duration_str)
        except ValueError:
            duration = 0

        speaker_names = []
        raw_speakers = row.get("speakers", "").strip()
        if raw_speakers:
            speaker_names = [s.strip() for s in raw_speakers.split("/") if s.strip()]

        records.append({
            "line_num": line_num,
            "start_time": _build_start_time(date, start_time),
            "duration": duration,
            "title": row.get("track", "").strip(),       # track name -> Brella title
            "subtitle": title,                             # session name -> Brella subtitle
            "description": row.get("content", "").strip(),
            "location": row.get("location", "").strip(),   # physical venue
            "speaker_names": speaker_names,
            "external_id": _make_external_id(title),
        })

    emit(f"Parsed {len(records)} sessions, {skipped} skipped.", log_callback=log_callback)
    return records


def _speakers_info(speaker_names):
    """Format speaker names for log messages, or empty string if none."""
    if speaker_names:
        return f" | speakers: {', '.join(speaker_names)}"
    return ""


def run_schedule_sync(csv_path, dry_run=False, prune_missing=False, log_callback=None):
    import api
    api.API_KEY = os.environ.get("BRELLA_API_KEY", "")
    api.ORG_ID = os.environ.get("BRELLA_ORG_ID", "1218")
    api.EVENT_ID = os.environ.get("BRELLA_EVENT_ID", "10672")

    org = api.ORG_ID
    event = api.EVENT_ID

    headers = build_request_headers()
    headers["Content-Type"] = "application/json"

    records = parse_schedule_csv(csv_path, log_callback=log_callback)

    existing_timeslots = list_timeslots(headers, org, event)
    existing_map = {
        ts.get("attributes", {}).get("external-id"): ts
        for ts in existing_timeslots
        if ts.get("attributes", {}).get("external-id")
    }

    emit(
        f"Found {len(existing_timeslots)} existing timeslots "
        f"({len(existing_map)} with external_id).",
        log_callback=log_callback,
    )

    # Load Brella speakers for name matching
    from speakers import list_speakers
    existing_speakers = list_speakers(headers)
    speaker_name_map = _build_speaker_name_map(existing_speakers)
    emit(f"Found {len(existing_speakers)} speakers in Brella.", log_callback=log_callback)

    # Load Brella stages for track->stage mapping
    existing_stages = list_stages(event, log_callback=log_callback)
    stage_name_map = _build_stage_name_map(existing_stages)
    if existing_stages:
        names = [s.get("attributes", {}).get("name", s.get("name", ""))
                 for s in existing_stages if isinstance(s, dict)]
        emit(f"Found {len(existing_stages)} stages in Brella: {', '.join(names)}",
             log_callback=log_callback)
        emit(f"Stage lookup keys: {', '.join(sorted(stage_name_map.keys()))}",
             log_callback=log_callback)
    else:
        emit("[WARN] No stages found — tracks will not be set. "
             "Check BRELLA_ADMIN_ACCESS_TOKEN, BRELLA_ADMIN_CLIENT, BRELLA_ADMIN_UID in .env",
             log_callback=log_callback)

    # Timezone offset: CSV times are local, Brella stores/displays in UTC.
    from datetime import datetime, timedelta
    import api as _api_mod
    _api_mod.load_env_file(_api_mod.ENV_FILE)
    tz_offset = int(os.environ.get("BRELLA_TIMEZONE_OFFSET", "0"))
    if tz_offset:
        emit(f"Timezone offset: UTC{tz_offset:+d} — subtracting {tz_offset}h before sending.",
             log_callback=log_callback)

    desired_ids = set()
    added = []
    updated = []
    removed = []
    failed = 0
    unmatched_speakers = []

    for rec in records:
        ext_id = rec["external_id"]
        desired_ids.add(ext_id)
        session_name = rec["subtitle"]

        start_dt = datetime.strptime(rec["start_time"], "%Y-%m-%d %H:%M:%S")
        if tz_offset:
            start_dt -= timedelta(hours=tz_offset)
        start_time = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_time = _build_end_time(start_time, rec["duration"])

        # Resolve speaker IDs from name map; track unmatched ones
        speaker_ids = []
        session_unmatched = []
        for speaker_name in rec["speaker_names"]:
            norm = speaker_name.lower().strip()
            sp = speaker_name_map.get(norm)
            if sp:
                speaker_ids.append(int(sp["id"]))
            else:
                session_unmatched.append(speaker_name)
                unmatched_speakers.append(f"{speaker_name} (session: {session_name})")

        speaker_assignments = [
            {"speaker_id": str(sp_id), "position": i + 1}
            for i, sp_id in enumerate(speaker_ids)
        ]

        # Resolve track name to stage ID
        stage_id = None
        if rec["title"]:
            stage = stage_name_map.get(rec["title"].lower().strip())
            if stage:
                stage_id = stage.get("id")
            else:
                emit(f"[WARN] Stage not found in Brella: {rec['title']}", log_callback=log_callback)

        payload = {
            "title": rec["title"],
            "subtitle": rec["subtitle"],
            "description": "",
            "start_time": start_time,
            "end_time": end_time,
            "duration": rec["duration"],
            "location": rec["location"],
            "external_id": ext_id,
            "speaker_assignments": speaker_assignments,
        }

        if session_unmatched:
            for name in session_unmatched:
                emit(f"[WARN] Speaker not found in Brella: {name}", log_callback=log_callback)

        if dry_run:
            action = "UPDATE" if ext_id in existing_map else "CREATE"
            emit(
                f"[PREVIEW] {action}: {session_name} @ {rec['start_time']}"
                f"{_speakers_info(rec['speaker_names'])}",
                log_callback=log_callback,
            )
            if action == "CREATE":
                added.append(session_name)
            else:
                updated.append(session_name)
            continue

        try:
            ts_id = None
            if ext_id in existing_map:
                ts_id = existing_map[ext_id]["id"]
                status, resp = update_timeslot(headers, org, event, ts_id, payload)
                if status in (200, 201, 204):
                    updated.append(session_name)
                    emit(f"[OK] Updated: {session_name}{_speakers_info(rec['speaker_names'])}",
                         log_callback=log_callback)
                else:
                    failed += 1
                    emit(f"[ERROR] line {rec['line_num']} update: {status} {resp}",
                         log_callback=log_callback)
                    continue
            else:
                status, resp = create_timeslot(headers, org, event, payload)
                if status in (200, 201):
                    added.append(session_name)
                    ts_id = resp.get("data", {}).get("id") if isinstance(resp, dict) else None
                    emit(f"[OK] Created: {session_name} (id: {ts_id})"
                         f"{_speakers_info(rec['speaker_names'])}",
                         log_callback=log_callback)
                else:
                    failed += 1
                    emit(f"[ERROR] line {rec['line_num']} create: {status} {resp}",
                         log_callback=log_callback)
                    continue

            # Admin panel PATCH: description (DraftJS) + stage
            if ts_id:
                admin_patches = {}
                if rec["description"]:
                    admin_patches["content"] = _to_draftjs(rec["description"])
                if stage_id:
                    admin_patches["track_id"] = stage_id
                if admin_patches:
                    asc, asr = _admin_patch_timeslot(event, ts_id, admin_patches, log_callback=log_callback)
                    if asc in (200, 201, 204):
                        parts = []
                        if rec["description"]:
                            parts.append("description")
                        if stage_id:
                            parts.append(f"stage: {rec['title']}")
                        emit(f"[OK] Admin patch — {' | '.join(parts)}", log_callback=log_callback)

            time.sleep(REQUEST_DELAY_SECONDS)

        except Exception as exc:
            failed += 1
            emit(f"[ERROR] line {rec['line_num']}: {exc}", log_callback=log_callback)

    if prune_missing:
        emit("Checking for timeslots to prune...", log_callback=log_callback)
        for ext_id, ts in existing_map.items():
            if ext_id in desired_ids:
                continue
            ts_id = ts["id"]
            attrs = ts.get("attributes", {})
            ts_name = attrs.get("subtitle") or attrs.get("title") or ext_id

            if dry_run:
                emit(f"[PREVIEW] Would remove: {ts_name}", log_callback=log_callback)
                removed.append(ts_name)
            else:
                status, _ = delete_timeslot(headers, org, event, ts_id)
                if status in (200, 202, 204):
                    removed.append(ts_name)
                    emit(f"[OK] Removed: {ts_name}", log_callback=log_callback)
                else:
                    failed += 1
                    emit(f"[ERROR] Remove {ext_id}: {status}", log_callback=log_callback)
                time.sleep(REQUEST_DELAY_SECONDS)

    emit(
        f"Done. Created: {len(added)}, Updated: {len(updated)}, Removed: {len(removed)}, "
        f"Failed: {failed}, Unmatched speakers: {len(unmatched_speakers)}",
        log_callback=log_callback,
    )

    if unmatched_speakers:
        emit("Unmatched speakers (run Speakers sync first):", log_callback=log_callback)
        for s in unmatched_speakers:
            emit(f"  - {s}", log_callback=log_callback)

    return {
        "processed": len(records),
        "added_participants": added,
        "updated_participants": updated,
        "removed_participants": removed,
        "failed": failed,
        "unmatched_speakers": unmatched_speakers,
    }
