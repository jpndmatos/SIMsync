"""
Schedule sync — import sessions from CSV into Brella's schedule.

CSV format: comma-delimited with headers:
    date [YYYY-MM-DD], start_time [HH:MM:SS], duration [int min], title,
    content, track [predetermined tracks in ALL CAPS], location,
    speakers [full names separated by " / "]

- date: YYYY-MM-DD
- start_time: HH:MM:SS
- duration: integer minutes
- title: session name (used as external_id key)
- content: session description
- track: predetermined stage/track name in ALL CAPS
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

        body_stripped = body.strip()
        if not body_stripped:
            return resp.status, {}

        try:
            return resp.status, json.loads(body_stripped)
        except json.JSONDecodeError:
            # Some admin endpoints return HTML or empty-like text with HTTP 200.
            return resp.status, body
    except url_error.HTTPError as e:
        raw = e.read()
        try:
            if e.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            body = raw.decode("utf-8", errors="replace")
        except Exception:
            body = repr(raw)

        body_stripped = body.strip() if isinstance(body, str) else ""
        if not body_stripped:
            return e.code, {}

        if isinstance(body, str):
            try:
                return e.code, json.loads(body_stripped)
            except json.JSONDecodeError:
                pass

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
    """Extract first non-empty list from an API response shape."""
    if isinstance(data, list):
        return data if data else None
    if not isinstance(data, dict):
        return None

    preferred_keys = (
        "data",
        "items",
        "tags",
        "session_types",
        "locations",
        "schedule_locations",
        "event_locations",
        "event-locations",
        "venues",
        "places",
        "results",
    )

    for key in preferred_keys:
        if key not in data:
            continue
        value = data.get(key)
        if isinstance(value, list) and value:
            return value
        if isinstance(value, dict):
            nested = _extract_items_from_response(value)
            if nested:
                return nested

    # Last resort: first non-empty list in the dict.
    for value in data.values():
        if isinstance(value, list) and value:
            return value
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
    url_template = os.environ.get(
        "BRELLA_TRACKS_URL",
        "https://api.brella.io/api/admin_panel/events/{event_id}/tracks",
    )
    url = url_template.format(event_id=event)
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


def list_locations(org, event, log_callback=None):
    """Fetch locations from Brella admin panel API with endpoint fallbacks."""
    admin_hdrs = _admin_headers()
    if not admin_hdrs:
        return []

    primary_template = os.environ.get(
        "BRELLA_LOCATIONS_URL",
        "https://api.brella.io/api/admin_panel/events/{event_id}/locations",
    )

    templates = []
    for tmpl in (
        primary_template,
        "https://api.brella.io/api/admin_panel/organizations/{org_id}/events/{event_id}/locations",
        "https://api.brella.io/api/admin_panel/events/{event_id}/schedule/locations",
        "https://api.brella.io/api/admin_panel/organizations/{org_id}/events/{event_id}/schedule/locations",
        "https://manager.brella.io/api/admin_panel/events/{event_id}/schedule/locations",
        "https://manager.brella.io/api/admin_panel/organizations/{org_id}/events/{event_id}/schedule/locations",
        "https://api.brella.io/api/admin_panel/events/{event_id}/schedule_locations",
        "https://api.brella.io/api/admin_panel/organizations/{org_id}/events/{event_id}/schedule_locations",
        "https://api.brella.io/api/admin_panel/events/{event_id}/event_locations",
        "https://api.brella.io/api/admin_panel/organizations/{org_id}/events/{event_id}/event_locations",
        "https://api.brella.io/api/admin_panel/events/{event_id}/venues",
        "https://api.brella.io/api/admin_panel/organizations/{org_id}/events/{event_id}/venues",
        "https://api.brella.io/api/admin_panel/events/{event_id}/places",
        "https://api.brella.io/api/admin_panel/organizations/{org_id}/events/{event_id}/places",
    ):
        if tmpl and tmpl not in templates:
            templates.append(tmpl)

    attempts = []
    for tmpl in templates:
        try:
            url = tmpl.format(event_id=event, org_id=org)
        except KeyError:
            continue
        status, data = _api_call(url, admin_hdrs)
        attempts.append((url, status, data))
        if status != 200:
            continue

        items = _extract_items_from_response(data)
        if not items and isinstance(data, dict):
            # Last resort: pick a likely location list key.
            for key, value in data.items():
                if not isinstance(value, list) or not value:
                    continue
                key_norm = str(key).lower()
                if any(token in key_norm for token in ("location", "venue", "place", "schedule")):
                    items = value
                    break

        if items:
            if tmpl != primary_template:
                emit(
                    f"[INFO] Locations resolved using fallback endpoint: {url}",
                    log_callback=log_callback,
                )
            return items

    status_info = ", ".join(f"{sc} {url}" for url, sc, _ in attempts)
    emit(
        f"[WARN] Locations lookup returned no usable items (attempts: {status_info}). "
        "Set BRELLA_LOCATIONS_URL if your endpoint differs.",
        log_callback=log_callback,
    )
    return []


def _build_location_name_map(locations):
    """Build normalized name -> location dict from Brella locations list."""
    location_map = {}
    for loc in locations:
        if isinstance(loc, dict):
            attrs = loc.get("attributes", {}) if isinstance(loc.get("attributes"), dict) else {}
            candidates = [
                attrs.get("name"),
                attrs.get("title"),
                attrs.get("label"),
                attrs.get("location-name"),
                attrs.get("location_name"),
                loc.get("name"),
                loc.get("title"),
                loc.get("label"),
                loc.get("location-name"),
                loc.get("location_name"),
            ]
            for candidate in candidates:
                if not candidate:
                    continue
                norm = re.sub(r"\s+", " ", str(candidate).strip()).lower()
                if norm:
                    location_map[norm] = loc
                    break
    return location_map


def _extract_location_id(location_obj):
    """Extract location ID from multiple possible payload shapes."""
    if not isinstance(location_obj, dict):
        return None

    candidates = [
        location_obj.get("id"),
        location_obj.get("location_id"),
        location_obj.get("location-id"),
        location_obj.get("event_location_id"),
        location_obj.get("event-location-id"),
        location_obj.get("schedule_location_id"),
        location_obj.get("schedule-location-id"),
        location_obj.get("venue_id"),
        location_obj.get("venue-id"),
        location_obj.get("place_id"),
        location_obj.get("place-id"),
    ]

    attrs = location_obj.get("attributes", {})
    if isinstance(attrs, dict):
        candidates.extend([
            attrs.get("id"),
            attrs.get("location_id"),
            attrs.get("location-id"),
            attrs.get("event_location_id"),
            attrs.get("event-location-id"),
            attrs.get("schedule_location_id"),
            attrs.get("schedule-location-id"),
            attrs.get("venue_id"),
            attrs.get("venue-id"),
            attrs.get("place_id"),
            attrs.get("place-id"),
        ])

    for candidate in candidates:
        if candidate is None:
            continue
        value = str(candidate).strip()
        if value:
            return value

    return None


def _build_location_name_id_map_from_timeslots(existing_timeslots):
    """Infer location name -> location_id mapping from existing timeslot attributes."""
    mapping = {}

    for ts in existing_timeslots:
        if not isinstance(ts, dict):
            continue

        attrs = ts.get("attributes", {})
        if not isinstance(attrs, dict):
            continue

        location_candidates = []
        for key in ("location", "location-name", "location_name", "venue", "venue_name", "place"):
            value = attrs.get(key)
            if isinstance(value, str) and value.strip():
                location_candidates.append(value)

        nested_location_obj = None
        for key in ("location", "event-location", "event_location", "schedule_location", "venue", "place"):
            value = attrs.get(key)
            if isinstance(value, dict):
                nested_location_obj = value
                for nested_key in ("name", "title", "label", "location-name", "location_name"):
                    nested_name = value.get(nested_key)
                    if isinstance(nested_name, str) and nested_name.strip():
                        location_candidates.append(nested_name)

        direct_id_candidates = [
            attrs.get("location-id"),
            attrs.get("location_id"),
            attrs.get("event-location-id"),
            attrs.get("event_location_id"),
            attrs.get("schedule-location-id"),
            attrs.get("schedule_location_id"),
            attrs.get("venue-id"),
            attrs.get("venue_id"),
            attrs.get("place-id"),
            attrs.get("place_id"),
        ]

        location_id = None
        for candidate in direct_id_candidates:
            if candidate is None:
                continue
            value = str(candidate).strip()
            if value:
                location_id = value
                break

        if not location_id and nested_location_obj:
            location_id = _extract_location_id(nested_location_obj)

        if not location_id:
            continue

        for location_name in location_candidates:
            norm = re.sub(r"\s+", " ", str(location_name).strip()).lower()
            if norm:
                mapping[norm] = location_id

    return mapping


def _normalize_timeslot_datetime(value):
    """Normalize API datetime variants to 'YYYY-MM-DD HH:MM:SS'."""
    from datetime import datetime, timezone

    raw = str(value or "").strip()
    if not raw:
        return ""

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    iso_raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(iso_raw)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass

    return raw.replace("T", " ")[:19]


def _timeslot_match_key(title, start_time):
    """Build a stable comparison key for matching existing timeslots."""
    title_key = re.sub(r"\s+", " ", str(title or "").strip()).lower()
    start_key = _normalize_timeslot_datetime(start_time)
    if not title_key or not start_key:
        return ""
    return f"{title_key}|{start_key}"


def _build_existing_title_start_map(existing_timeslots, log_callback=None):
    """Map normalized title+start_time to existing timeslot for fallback matching."""
    match_map = {}
    duplicate_count = 0

    for ts in existing_timeslots:
        attrs = ts.get("attributes", {}) if isinstance(ts, dict) else {}
        title = attrs.get("title") or attrs.get("subtitle") or ""
        start_time = (
            attrs.get("start-time")
            or attrs.get("start_time")
            or attrs.get("startAt")
            or attrs.get("start_at")
            or ""
        )

        key = _timeslot_match_key(title, start_time)
        if not key:
            continue
        if key in match_map:
            duplicate_count += 1
            continue
        match_map[key] = ts

    if duplicate_count:
        emit(
            f"[WARN] Found {duplicate_count} existing duplicate(s) with same title/start_time.",
            log_callback=log_callback,
        )
    return match_map


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


def _admin_patch_timeslot_location(event, timeslot_id, location_value, location_id=None,
                                   log_callback=None):
    """Patch location via admin panel API using fallback id and name field names."""
    admin_hdrs = _admin_headers()
    if not admin_hdrs or not (location_value or location_id):
        return None, None, None

    url = f"https://api.brella.io/api/admin_panel/events/{event}/timeslots/{timeslot_id}"
    candidate_patches = []
    if location_id:
        candidate_patches.extend([
            ("location_id", location_id),
            ("schedule_location_id", location_id),
            ("event_location_id", location_id),
            ("venue_id", location_id),
            ("place_id", location_id),
        ])
    if location_value:
        candidate_patches.extend([
            ("location", location_value),
            ("location_name", location_value),
            ("venue_name", location_value),
            ("venue", location_value),
        ])

    last_sc, last_sr = None, None

    for key, value in candidate_patches:
        sc, sr = _api_call(
            url,
            admin_hdrs,
            method="PATCH",
            payload={"timeslot": {key: value}},
        )
        if sc in (200, 201, 204):
            return key, sc, sr
        last_sc, last_sr = sc, sr

    emit(
        f"[WARN] Location patch failed: {last_sc} {str(last_sr)[:300]}",
        log_callback=log_callback,
    )
    return None, last_sc, last_sr


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
    return f"{date_str} {time_str.strip()}"


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


def _normalize_csv_header(name):
    """Map headers like 'date [YYYY-MM-DD]' to canonical keys like 'date'."""
    key = (name or "").strip().lower()
    key = re.sub(r"\s*\[[^\]]+\]\s*$", "", key)
    key = key.replace(" ", "_")
    return key


def _allowed_tracks_from_env():
    """Optional strict track whitelist via BRELLA_ALLOWED_TRACKS."""
    raw = os.environ.get("BRELLA_ALLOWED_TRACKS", "").strip()
    if not raw:
        return None
    allowed = {item.strip().upper() for item in raw.split(",") if item.strip()}
    return allowed or None


def parse_schedule_csv(csv_path, log_callback=None):
    from datetime import datetime

    path = Path(csv_path)
    raw = path.read_bytes()
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    text = raw.decode("utf-8")

    records = []
    skipped = 0
    allowed_tracks = _allowed_tracks_from_env()

    if allowed_tracks:
        emit(
            f"Track whitelist enabled from BRELLA_ALLOWED_TRACKS ({len(allowed_tracks)} values).",
            log_callback=log_callback,
        )

    reader = csv.DictReader(text.splitlines())
    raw_headers = [h.strip() for h in (reader.fieldnames or []) if h]
    normalized_headers = [_normalize_csv_header(h) for h in raw_headers]
    if raw_headers:
        emit(f"Detected CSV headers: {', '.join(raw_headers)}", log_callback=log_callback)
        emit(
            f"Normalized CSV headers: {', '.join(normalized_headers)}",
            log_callback=log_callback,
        )
    else:
        emit("[WARN] No CSV headers detected; check CSV format.", log_callback=log_callback)

    for line_num, row in enumerate(reader, start=2):
        normalized_row = {
            _normalize_csv_header(k): (v or "").strip()
            for k, v in row.items()
            if _normalize_csv_header(k)
        }

        # Filter by sync column
        sync_flag = normalized_row.get("sync", "TRUE").upper()
        if sync_flag == "FALSE":
            skipped += 1
            continue

        date = normalized_row.get("date", "")
        start_time = normalized_row.get("start_time", "")
        title = normalized_row.get("title", "")
        track = normalized_row.get("track", "")

        if not date or not start_time or not title or not track:
            skipped += 1
            emit(f"[SKIP] line {line_num}: missing date, start_time, title or track",
                 log_callback=log_callback)
            continue

        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            skipped += 1
            emit(f"[SKIP] line {line_num}: invalid date '{date}' (expected YYYY-MM-DD)",
                 log_callback=log_callback)
            continue
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            skipped += 1
            emit(f"[SKIP] line {line_num}: invalid date '{date}'", log_callback=log_callback)
            continue

        if not re.fullmatch(r"\d{2}:\d{2}:\d{2}", start_time):
            skipped += 1
            emit(
                f"[SKIP] line {line_num}: invalid start_time '{start_time}' "
                "(expected HH:MM:SS)",
                log_callback=log_callback,
            )
            continue
        try:
            datetime.strptime(start_time, "%H:%M:%S")
        except ValueError:
            skipped += 1
            emit(f"[SKIP] line {line_num}: invalid start_time '{start_time}'",
                 log_callback=log_callback)
            continue

        duration_str = normalized_row.get("duration", "")
        try:
            duration = int(duration_str)
        except ValueError:
            skipped += 1
            emit(
                f"[SKIP] line {line_num}: invalid duration '{duration_str}' "
                "(expected integer minutes)",
                log_callback=log_callback,
            )
            continue
        if duration <= 0:
            skipped += 1
            emit(
                f"[SKIP] line {line_num}: invalid duration '{duration}' "
                "(must be > 0 minutes)",
                log_callback=log_callback,
            )
            continue

        if track != track.upper():
            skipped += 1
            emit(
                f"[SKIP] line {line_num}: invalid track '{track}' "
                "(must be ALL CAPS)",
                log_callback=log_callback,
            )
            continue
        if allowed_tracks and track not in allowed_tracks:
            skipped += 1
            emit(
                f"[SKIP] line {line_num}: track '{track}' is not in BRELLA_ALLOWED_TRACKS",
                log_callback=log_callback,
            )
            continue

        speaker_names = []
        raw_speakers = normalized_row.get("speakers", "")
        if raw_speakers:
            if "/" in raw_speakers and " / " not in raw_speakers:
                skipped += 1
                emit(
                    f"[SKIP] line {line_num}: invalid speakers format '{raw_speakers}' "
                    "(use ' / ' separator)",
                    log_callback=log_callback,
                )
                continue
            speaker_names = [s.strip() for s in raw_speakers.split(" / ") if s.strip()]

        records.append({
            "line_num": line_num,
            "start_time": _build_start_time(date, start_time),
            "duration": duration,
            "title": title,                                # session name -> Brella title
            "track": track,                                # track name -> stage mapping
            "description": normalized_row.get("content", ""),
            "location": normalized_row.get("location", ""),  # physical venue
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
    existing_title_start_map = _build_existing_title_start_map(
        existing_timeslots,
        log_callback=log_callback,
    )
    timeslot_location_id_map = _build_location_name_id_map_from_timeslots(existing_timeslots)

    emit(
        f"Found {len(existing_timeslots)} existing timeslots "
        f"({len(existing_map)} with external_id).",
        log_callback=log_callback,
    )
    emit(
        f"Fallback match keys available (title+start_time): {len(existing_title_start_map)}",
        log_callback=log_callback,
    )
    if timeslot_location_id_map:
        emit(
            f"Inferred location ids from existing timeslots: {len(timeslot_location_id_map)}",
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

    # Load Brella locations for location->location_id mapping
    existing_locations = list_locations(org, event, log_callback=log_callback)
    location_name_map = _build_location_name_map(existing_locations)
    if existing_locations:
        names = [loc_item.get("attributes", {}).get("name", loc_item.get("name", ""))
                 for loc_item in existing_locations if isinstance(loc_item, dict)]
        emit(f"Found {len(existing_locations)} locations in Brella: {', '.join(names)}",
             log_callback=log_callback)
    else:
        emit("[WARN] No locations found from admin API — location_id mapping unavailable.",
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
        session_name = rec["title"]

        start_dt = datetime.strptime(rec["start_time"], "%Y-%m-%d %H:%M:%S")
        if tz_offset:
            start_dt -= timedelta(hours=tz_offset)
        start_time = start_dt.strftime("%Y-%m-%d %H:%M:%S")
        end_time = _build_end_time(start_time, rec["duration"])
        match_key = _timeslot_match_key(rec["title"], start_time)

        existing_ts = existing_map.get(ext_id)
        if not existing_ts and match_key:
            existing_ts = existing_title_start_map.get(match_key)
            if existing_ts:
                emit(
                    f"[INFO] Matched existing by title+start_time: {session_name}",
                    log_callback=log_callback,
                )

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
        if rec["track"]:
            stage = stage_name_map.get(rec["track"].lower().strip())
            if stage:
                stage_id = stage.get("id")
            else:
                emit(f"[WARN] Stage not found in Brella: {rec['track']}", log_callback=log_callback)

        # Resolve location name to location ID (if available)
        location_id = None
        if rec["location"]:
            location_lookup = re.sub(r"\s+", " ", rec["location"].strip()).lower()
            loc = location_name_map.get(location_lookup)
            if loc:
                location_id = _extract_location_id(loc) or loc.get("id")
            if not location_id:
                location_id = timeslot_location_id_map.get(location_lookup)
                if location_id:
                    emit(
                        f"[INFO] Location id inferred from existing timeslots: {rec['location']}",
                        log_callback=log_callback,
                    )
            if not location_id and existing_locations:
                emit(
                    f"[WARN] Location not found in Brella: {rec['location']}",
                    log_callback=log_callback,
                )

        payload = {
            "title": rec["title"],
            "subtitle": "",
            "description": "",
            "start_time": start_time,
            "end_time": end_time,
            "duration": rec["duration"],
            "location": rec["location"],
            "external_id": ext_id,
            "speaker_assignments": speaker_assignments,
        }
        if location_id:
            payload["location_id"] = location_id

        if session_unmatched:
            for name in session_unmatched:
                emit(f"[WARN] Speaker not found in Brella: {name}", log_callback=log_callback)

        if dry_run:
            action = "UPDATE" if existing_ts else "CREATE"
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
            if existing_ts:
                ts_id = existing_ts["id"]
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
                            parts.append(f"stage: {rec['track']}")
                        emit(f"[OK] Admin patch — {' | '.join(parts)}", log_callback=log_callback)

                if rec["location"]:
                    location_key, lsc, lsr = _admin_patch_timeslot_location(
                        event,
                        ts_id,
                        rec["location"],
                        location_id=location_id,
                        log_callback=log_callback,
                    )
                    if location_key:
                        emit(
                            f"[OK] Admin patch — location: {rec['location']} ({location_key})",
                            log_callback=log_callback,
                        )

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
            ts_name = attrs.get("title") or attrs.get("subtitle") or ext_id

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
