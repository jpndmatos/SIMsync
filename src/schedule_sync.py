import csv
import difflib
import gzip
import importlib
import json
import os
import re
import time
import unicodedata
import zlib
from pathlib import Path
from urllib import request as url_request, error as url_error

from api import build_request_headers, emit, REQUEST_DELAY_SECONDS


def _is_verbose_logging():

    raw = os.environ.get("SIMSYNC_VERBOSE_LOGS", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _emit_log(message, log_callback=None, verbose_only=False):
    if verbose_only and not _is_verbose_logging():
        return
    emit(message, log_callback=log_callback)


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
    def _decode_raw_response(raw_bytes, response_headers):
        encoding = str(response_headers.get("Content-Encoding", "")).lower()


        try:
            if "gzip" in encoding:
                raw_bytes = gzip.decompress(raw_bytes)
            elif "deflate" in encoding:
                raw_bytes = zlib.decompress(raw_bytes)
            elif "br" in encoding:
                try:
                    brotli = importlib.import_module("br" + "otli")
                    raw_bytes = brotli.decompress(raw_bytes)
                except Exception:
                    pass
        except Exception:
            pass

        return raw_bytes.decode("utf-8", errors="replace")

    data = json.dumps(payload).encode() if payload else None
    req = url_request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = url_request.urlopen(req)
        raw = resp.read()
        body = _decode_raw_response(raw, resp.headers)

        body_stripped = body.strip()
        if not body_stripped:
            return resp.status, {}

        try:
            return resp.status, json.loads(body_stripped)
        except json.JSONDecodeError:
            return resp.status, body
    except url_error.HTTPError as e:
        raw = e.read()
        try:
            body = _decode_raw_response(raw, e.headers)
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
        "Accept-Encoding": "gzip, deflate",
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

    for value in data.values():
        if isinstance(value, list) and value:
            return value
    return None


def _build_speaker_assignment_map(included):

    assignment_map = {}
    if not isinstance(included, list):
        return assignment_map

    for item in included:
        if not isinstance(item, dict) or item.get("type") != "speaker-assignment":
            continue

        assignment_id = _normalize_speaker_id(item.get("id"))
        if not assignment_id:
            continue

        attrs = item.get("attributes") or {}
        rels = item.get("relationships") or {}
        speaker_rel = rels.get("speaker") or {}
        speaker_data = speaker_rel.get("data") if isinstance(speaker_rel, dict) else None

        if isinstance(speaker_data, dict):
            speaker_id = _normalize_speaker_id(speaker_data.get("id"))
        else:
            speaker_id = ""

        try:
            position = int(attrs.get("position"))
        except (TypeError, ValueError):
            position = None

        if speaker_id:
            assignment_map[assignment_id] = {
                "speaker_id": speaker_id,
                "position": position,
            }

    return assignment_map


def list_timeslots(headers, org, event):
    status, data = _api_call(_timeslots_url(org, event), headers)
    if status != 200:
        raise RuntimeError(f"Failed to list timeslots: {status} {data}")
    return data.get("data", [])


def list_timeslots_response(headers, org, event):

    status, data = _api_call(_timeslots_url(org, event), headers)
    if status != 200:
        raise RuntimeError(f"Failed to list timeslots: {status} {data}")
    return data


def create_timeslot(headers, org, event, payload):
    return _api_call(_timeslots_url(org, event), headers, method="POST",
                     payload={"timeslot": payload})


def update_timeslot(headers, org, event, timeslot_id, payload):
    return _api_call(_timeslots_url(org, event, timeslot_id), headers, method="PATCH",
                     payload={"timeslot": payload})


def _to_draftjs(text):

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

    stage_map = {}
    for s in stages:
        if isinstance(s, dict):
            name = s.get("attributes", {}).get("name", s.get("name", "")).strip()
            if name:
                stage_map[name.lower()] = s
    return stage_map


def _normalize_timeslot_datetime(value):

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


_TITLE_CHAR_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'",
    "\u201C": '"', "\u201D": '"',
    "\u2013": "-", "\u2014": "-",
    "\u200B": "", "\u200C": "", "\u200D": "",
    "\u00A0": " ",
})


def _normalize_title(title):
\

    s = str(title or "").translate(_TITLE_CHAR_MAP).strip()
    return re.sub(r"\s+", " ", s).lower()


def _timeslot_match_key(title, start_time):

    title_key = _normalize_title(title)
    start_key = _normalize_timeslot_datetime(start_time)
    if not title_key or not start_key:
        return ""
    return f"{title_key}|{start_key}"


def _diff_timeslot(rec_title, start_time, end_time, duration, existing_ts):
\
\

    if not isinstance(existing_ts, dict):
        return []
    attrs = existing_ts.get("attributes") or {}
    changes = []

    existing_title = str(attrs.get("title") or "").strip()
    new_title = str(rec_title or "").strip()
    if existing_title != new_title:
        changes.append(("title", existing_title, new_title))

    existing_start = _normalize_timeslot_datetime(
        attrs.get("start-time") or attrs.get("start_time") or ""
    )
    new_start = _normalize_timeslot_datetime(start_time)
    if existing_start != new_start:
        changes.append(("start_time", existing_start or "-", new_start or "-"))

    existing_end = _normalize_timeslot_datetime(
        attrs.get("end-time") or attrs.get("end_time") or ""
    )
    new_end = _normalize_timeslot_datetime(end_time)
    if existing_end != new_end:
        changes.append(("end_time", existing_end or "-", new_end or "-"))

    existing_dur = attrs.get("duration")
    try:
        existing_dur_i = int(existing_dur) if existing_dur is not None else None
    except (TypeError, ValueError):
        existing_dur_i = None
    try:
        new_dur_i = int(duration) if duration is not None else None
    except (TypeError, ValueError):
        new_dur_i = None
    if existing_dur_i != new_dur_i:
        changes.append(("duration", str(existing_dur_i), str(new_dur_i)))

    return changes


def _format_changes(changes):
\

    parts = []
    for field, old, new in changes:
        parts.append(f"{field}: «{old}» → «{new}»")
    return " · ".join(parts)


def _normalize_speaker_id(value):
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return str(int(raw))
    except (TypeError, ValueError):
        return raw


def _normalize_person_name(value):
    raw = str(value or "").strip().lower()
    if not raw:
        return ""

    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = re.sub(r"[^\w]+", " ", raw, flags=re.UNICODE)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw


def _speaker_ids_from_assignments(assignments):

    if not isinstance(assignments, list):
        return []

    ordered = []
    has_explicit_position = False
    for index, item in enumerate(assignments):
        if not isinstance(item, dict):
            continue

        speaker_id = _normalize_speaker_id(
            item.get("speaker_id")
            or item.get("speaker-id")
            or item.get("speakerId")
            or item.get("id")
        )
        if not speaker_id:
            continue

        try:
            position = int(item.get("position"))
            has_explicit_position = True
        except (TypeError, ValueError):
            position = index + 1

        ordered.append((position, index, speaker_id))

    if has_explicit_position:
        ordered.sort(key=lambda row: (row[0], row[1]))

    return [speaker_id for _, _, speaker_id in ordered]


def _extract_existing_speaker_ids(existing_ts, speaker_assignment_map=None):

    if not isinstance(existing_ts, dict):
        return []

    attrs = existing_ts.get("attributes") or {}
    assignment_candidates = [
        attrs.get("speaker-assignments"),
        attrs.get("speaker_assignments"),
        existing_ts.get("speaker-assignments"),
        existing_ts.get("speaker_assignments"),
    ]

    for candidate in assignment_candidates:
        if isinstance(candidate, list):
            return _speaker_ids_from_assignments(candidate)

    rel_assignments = (existing_ts.get("relationships") or {}).get("speaker-assignments")
    rel_data = rel_assignments.get("data") if isinstance(rel_assignments, dict) else None
    if isinstance(rel_data, list) and speaker_assignment_map:
        ordered = []
        for index, item in enumerate(rel_data):
            if not isinstance(item, dict):
                continue

            assignment_id = _normalize_speaker_id(item.get("id"))
            assignment = speaker_assignment_map.get(assignment_id)
            if not assignment:
                continue

            speaker_id = _normalize_speaker_id(assignment.get("speaker_id"))
            if not speaker_id:
                continue

            position = assignment.get("position")
            try:
                position = int(position)
            except (TypeError, ValueError):
                position = index + 1

            ordered.append((position, index, speaker_id))

        if ordered:
            ordered.sort(key=lambda row: (row[0], row[1]))
            return [speaker_id for _, _, speaker_id in ordered]

    rel_speakers = (existing_ts.get("relationships") or {}).get("speakers")
    rel_data = rel_speakers.get("data") if isinstance(rel_speakers, dict) else None
    if isinstance(rel_data, list):
        speaker_ids = []
        for item in rel_data:
            if not isinstance(item, dict):
                continue
            speaker_id = _normalize_speaker_id(item.get("id"))
            if speaker_id:
                speaker_ids.append(speaker_id)
        return speaker_ids

    attr_speakers = attrs.get("speakers")
    if isinstance(attr_speakers, list):
        speaker_ids = []
        for item in attr_speakers:
            if isinstance(item, dict):
                speaker_id = _normalize_speaker_id(
                    item.get("id")
                    or item.get("speaker_id")
                    or item.get("speaker-id")
                )
            else:
                speaker_id = _normalize_speaker_id(item)
            if speaker_id:
                speaker_ids.append(speaker_id)
        return speaker_ids

    return []


def _build_speaker_id_name_map(existing_speakers):

    id_map = {}
    for sp in existing_speakers:
        if not isinstance(sp, dict):
            continue

        speaker_id = _normalize_speaker_id(sp.get("id"))
        if not speaker_id:
            continue

        attrs = sp.get("attributes") or {}
        display_name = _speaker_display_name(attrs) or f"id:{speaker_id}"
        id_map[speaker_id] = display_name

    return id_map


def _format_speaker_list(speaker_ids, speaker_id_name_map):
    if not speaker_ids:
        return "-"
    return ", ".join(speaker_id_name_map.get(sid, f"id:{sid}") for sid in speaker_ids)


def _diff_speaker_assignments(existing_ts, desired_assignments, speaker_id_name_map, speaker_assignment_map=None):

    if not isinstance(existing_ts, dict):
        return []

    existing_ids = _extract_existing_speaker_ids(existing_ts, speaker_assignment_map)
    desired_ids = _speaker_ids_from_assignments(desired_assignments)
    if existing_ids == desired_ids:
        return []

    return [(
        "speakers",
        _format_speaker_list(existing_ids, speaker_id_name_map),
        _format_speaker_list(desired_ids, speaker_id_name_map),
    )]


def _build_existing_title_start_map(existing_timeslots, log_callback=None):
    match_map = {}
    duplicate_count = 0
    duplicate_labels = []
    duplicate_ext_ids = set()
    by_day = {}

    def _ext_id_of(ts):
        return (ts.get("attributes", {}) or {}).get("external-id") or ""

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
        ext_id = _ext_id_of(ts)
        if key in match_map:
            duplicate_count += 1
            duplicate_labels.append(f"{title} @ {start_time}")
            if ext_id:
                duplicate_ext_ids.add(ext_id)
            prev_ext_id = _ext_id_of(match_map[key])
            if prev_ext_id:
                duplicate_ext_ids.add(prev_ext_id)
            continue
        match_map[key] = ts

        title_norm = _normalize_title(title)
        start_norm = _normalize_timeslot_datetime(start_time)
        if title_norm and start_norm:
            date_part = start_norm.split(" ")[0]
            day_key = (title_norm, date_part)
            prev = by_day.get(day_key)
            if prev and prev["start"] != start_norm:
                duplicate_labels.append(
                    f"{title} on {date_part} — {prev['start'].split(' ')[1]} and "
                    f"{start_norm.split(' ')[1]}"
                )
                if ext_id:
                    duplicate_ext_ids.add(ext_id)
                if prev.get("ext_id"):
                    duplicate_ext_ids.add(prev["ext_id"])
            else:
                by_day[day_key] = {"start": start_norm, "ext_id": ext_id}

    if duplicate_count:
        emit(
            f"[WARN] Found {duplicate_count} existing duplicate(s) with same title/start_time.",
            log_callback=log_callback,
        )
    for label in duplicate_labels:
        emit(f"[DUP] {label}", log_callback=log_callback)
    return match_map, duplicate_labels, duplicate_ext_ids


def _build_existing_title_map(existing_timeslots, log_callback=None):
    title_map = {}
    duplicate_titles = set()

    for ts in existing_timeslots:
        attrs = ts.get("attributes", {}) if isinstance(ts, dict) else {}
        title = attrs.get("title") or attrs.get("subtitle") or ""
        title_norm = _normalize_title(title)
        if not title_norm:
            continue
        if title_norm in title_map:
            duplicate_titles.add(title_norm)
            title_map.pop(title_norm, None)
            continue
        if title_norm not in duplicate_titles:
            title_map[title_norm] = ts

    for title_norm in sorted(duplicate_titles):
        emit(f"[DUP] title appears multiple times in Brella: {title_norm}", log_callback=log_callback)

    return title_map


def _admin_patch_timeslot(event, timeslot_id, patches, log_callback=None):

    admin_hdrs = _admin_headers()
    if not admin_hdrs or not patches:
        return
    url = f"https://api.brella.io/api/admin_panel/events/{event}/timeslots/{timeslot_id}"
    sc, sr = _api_call(url, admin_hdrs, method="PATCH", payload={"timeslot": patches})
    if sc not in (200, 201, 204):
        emit(f"[WARN] Admin patch: {sc} {str(sr)[:300]}", log_callback=log_callback)
    return sc, sr


def _recreate_timeslot_with_speakers(headers, org, event, timeslot_id, payload, log_callback=None):
    sc, _ = _api_call(_timeslots_url(org, event, timeslot_id), headers, method="DELETE")
    if sc not in (200, 202, 204):
        emit(f"[WARN] Could not delete timeslot {timeslot_id} for speaker update: {sc}",
            log_callback=log_callback)
        return None, None

    time.sleep(REQUEST_DELAY_SECONDS)
    return _api_call(_timeslots_url(org, event), headers, method="POST",
                    payload={"timeslot": payload})


def delete_timeslot(headers, org, event, timeslot_id):
    return _api_call(_timeslots_url(org, event, timeslot_id), headers, method="DELETE")

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

    name_map = {}
    for sp in existing_speakers:
        if not isinstance(sp, dict):
            continue

        attrs = sp.get("attributes") or {}
        for candidate in _speaker_name_candidates(attrs):
            normalized = _normalize_person_name(candidate)
            if normalized and normalized not in name_map:
                name_map[normalized] = sp
    return name_map


def _speaker_name_candidates(attrs):

    key_pairs = (
        ("first-name", "last-name"),
        ("first_name", "last_name"),
        ("external-first-name", "external-last-name"),
        ("external_first_name", "external_last_name"),
    )

    for first_key, last_key in key_pairs:
        first = str(attrs.get(first_key) or "").strip()
        last = str(attrs.get(last_key) or "").strip()
        full = " ".join(part for part in (first, last) if part)
        if full:
            yield full

    for key in ("name", "full_name", "full-name", "display_name", "display-name"):
        value = str(attrs.get(key) or "").strip()
        if value:
            yield value


def _speaker_display_name(attrs):

    for candidate in _speaker_name_candidates(attrs):
        if candidate:
            return candidate
    return ""


def _name_tokens_match(left_name, right_name):
    left_tokens = _normalize_person_name(left_name).split()
    right_tokens = _normalize_person_name(right_name).split()
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return False

    def _is_subsequence(smaller, larger):
        index = 0
        for token in larger:
            if token == smaller[index]:
                index += 1
                if index == len(smaller):
                    return True
        return False

    return _is_subsequence(left_tokens, right_tokens) or _is_subsequence(right_tokens, left_tokens)


def _find_fallback_speaker(normalized_name, existing_speakers):
    normalized_name = _normalize_person_name(normalized_name)
    if not normalized_name:
        return None

    target_first = normalized_name.split()[0] if normalized_name.split() else ""

    for sp in existing_speakers:
        if not isinstance(sp, dict):
            continue

        attrs = sp.get("attributes") or {}
        for candidate in _speaker_name_candidates(attrs):
            if _name_tokens_match(normalized_name, candidate):
                return sp

    best_sp = None
    best_score = 0.0
    best_tied = False

    for sp in existing_speakers:
        if not isinstance(sp, dict):
            continue

        attrs = sp.get("attributes") or {}
        for candidate in _speaker_name_candidates(attrs):
            candidate_norm = _normalize_person_name(candidate)
            if not candidate_norm:
                continue

            candidate_first = candidate_norm.split()[0] if candidate_norm.split() else ""
            if target_first and candidate_first != target_first:
                continue

            score = difflib.SequenceMatcher(None, normalized_name, candidate_norm).ratio()
            if score > best_score + 1e-9:
                best_sp = sp
                best_score = score
                best_tied = False
            elif abs(score - best_score) <= 1e-9 and score > 0:
                best_tied = True

    if best_sp and best_score >= 0.93 and not best_tied:
        return best_sp

    return None

def _normalize_csv_header(name):

    key = (name or "").strip().lower()
    key = re.sub(r"\s*\[[^\]]+\]\s*$", "", key)
    key = key.replace(" ", "_")
    return key

def _allowed_tracks_from_env():

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
        _emit_log(
            f"Track whitelist enabled from BRELLA_ALLOWED_TRACKS ({len(allowed_tracks)} values).",
            log_callback=log_callback,
            verbose_only=True,
        )

    reader = csv.DictReader(text.splitlines())
    raw_headers = [h.strip() for h in (reader.fieldnames or []) if h]
    normalized_headers = [_normalize_csv_header(h) for h in raw_headers]
    if raw_headers:
        _emit_log(
            f"Detected CSV headers: {', '.join(raw_headers)}",
            log_callback=log_callback,
            verbose_only=True,
        )
        _emit_log(
            f"Normalized CSV headers: {', '.join(normalized_headers)}",
            log_callback=log_callback,
            verbose_only=True,
        )
    else:
        emit("[WARN] No CSV headers detected; check CSV format.", log_callback=log_callback)

    for line_num, row in enumerate(reader, start=2):
        normalized_row = {
            _normalize_csv_header(k): (v or "").strip()
            for k, v in row.items()
            if _normalize_csv_header(k)
        }

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
            "title": title,
            "track": track,
            "description": normalized_row.get("content", ""),
            "speaker_names": speaker_names,
            "external_id": _make_external_id(title),
        })

    emit(f"Parsed {len(records)} sessions, {skipped} skipped.", log_callback=log_callback)
    return records

def _speakers_info(speaker_names):

    if speaker_names:
        return f" | speakers: {', '.join(speaker_names)}"
    return ""

def run_schedule_sync(csv_path, dry_run=False, prune_missing=False,
                      update_existing=False, log_callback=None):
    import api
    api.API_KEY = os.environ.get("BRELLA_API_KEY", "")
    api.ORG_ID = os.environ.get("BRELLA_ORG_ID", "1218")
    api.EVENT_ID = os.environ.get("BRELLA_EVENT_ID", "10672")

    org = api.ORG_ID
    event = api.EVENT_ID

    headers = build_request_headers()
    headers["Content-Type"] = "application/json"

    records = parse_schedule_csv(csv_path, log_callback=log_callback)

    timeslot_response = list_timeslots_response(headers, org, event)
    existing_timeslots = timeslot_response.get("data", [])
    speaker_assignment_map = _build_speaker_assignment_map(timeslot_response.get("included", []))
    existing_map = {
        ts.get("attributes", {}).get("external-id"): ts
        for ts in existing_timeslots
        if ts.get("attributes", {}).get("external-id")
    }
    (existing_title_start_map, duplicate_sessions,
     duplicate_ext_ids) = _build_existing_title_start_map(
        existing_timeslots,
        log_callback=log_callback,
    )
    existing_title_map = _build_existing_title_map(existing_timeslots, log_callback=log_callback)
    _emit_log(
        f"Found {len(existing_timeslots)} existing timeslots "
        f"({len(existing_map)} with external_id).",
        log_callback=log_callback,
        verbose_only=True,
    )
    _emit_log(
        f"Fallback match keys available (title+start_time): {len(existing_title_start_map)}",
        log_callback=log_callback,
        verbose_only=True,
    )
    _emit_log(
        f"Fallback title keys available: {len(existing_title_map)}",
        log_callback=log_callback,
        verbose_only=True,
    )

    from speakers import list_speakers
    existing_speakers = list_speakers(headers)
    speaker_name_map = _build_speaker_name_map(existing_speakers)
    speaker_id_name_map = _build_speaker_id_name_map(existing_speakers)
    _emit_log(
        f"Found {len(existing_speakers)} speakers in Brella.",
        log_callback=log_callback,
        verbose_only=True,
    )

    existing_stages = list_stages(event, log_callback=log_callback)
    stage_name_map = _build_stage_name_map(existing_stages)
    if existing_stages:
        names = [s.get("attributes", {}).get("name", s.get("name", ""))
                 for s in existing_stages if isinstance(s, dict)]
        _emit_log(
            f"Found {len(existing_stages)} stages in Brella: {', '.join(names)}",
            log_callback=log_callback,
            verbose_only=True,
        )
        _emit_log(
            f"Stage lookup keys: {', '.join(sorted(stage_name_map.keys()))}",
            log_callback=log_callback,
            verbose_only=True,
        )
    else:
        emit("[WARN] No stages found — tracks will not be set. "
             "Check BRELLA_ADMIN_ACCESS_TOKEN, BRELLA_ADMIN_CLIENT, BRELLA_ADMIN_UID in .env",
             log_callback=log_callback)

    from datetime import datetime, timedelta
    import api as _api_mod
    _api_mod.load_env_file(_api_mod.ENV_FILE)
    tz_offset = int(os.environ.get("BRELLA_TIMEZONE_OFFSET", "0"))
    if tz_offset:
        emit(f"Timezone offset: UTC{tz_offset:+d} — subtracting {tz_offset}h before sending.",
             log_callback=log_callback)

    desired_ids = set()
    matched_brella_ids = set()
    added = []
    updated = []
    skipped = []
    removed = []
    only_in_brella = []
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
        legacy_match_key = _timeslot_match_key(rec["title"], rec["start_time"])

        existing_ts = existing_map.get(ext_id)
        if not existing_ts and match_key:

            existing_ts = existing_title_start_map.get(match_key)
            if existing_ts:
                _emit_log(
                    f"[INFO] Matched existing by title+start_time: {session_name}",
                    log_callback=log_callback,
                    verbose_only=True,
                )
        if not existing_ts and legacy_match_key and legacy_match_key != match_key:

            existing_ts = existing_title_start_map.get(legacy_match_key)
            if existing_ts:
                _emit_log(
                    f"[INFO] Matched existing by legacy local start_time: {session_name}",
                    log_callback=log_callback,
                    verbose_only=True,
                )
        if not existing_ts:
            title_key = _normalize_title(rec["title"])
            existing_ts = existing_title_map.get(title_key)
            if existing_ts:
                _emit_log(
                    f"[INFO] Matched existing by title: {session_name}",
                    log_callback=log_callback,
                    verbose_only=True,
                )

        if existing_ts:
            matched_brella_ids.add(existing_ts["id"])

        speaker_ids = []
        session_unmatched = []
        for speaker_name in rec["speaker_names"]:
            norm = _normalize_person_name(speaker_name)
            sp = speaker_name_map.get(norm)
            if not sp:
                sp = _find_fallback_speaker(norm, existing_speakers)
            if sp:
                speaker_ids.append(int(sp["id"]))
            else:
                session_unmatched.append(speaker_name)
                unmatched_speakers.append(f"{speaker_name} (session: {session_name})")

        speaker_assignments = [
            {"speaker_id": str(sp_id), "position": i + 1}
            for i, sp_id in enumerate(speaker_ids)
        ]

        stage_id = None
        if rec["track"]:
            stage = stage_name_map.get(rec["track"].lower().strip())
            if stage:
                stage_id = stage.get("id")
            else:
                emit(f"[WARN] Stage not found in Brella: {rec['track']}", log_callback=log_callback)

        payload = {
            "title": rec["title"],
            "subtitle": "",
            "description": "",
            "start_time": start_time,
            "end_time": end_time,
            "duration": rec["duration"],
            "external_id": ext_id,
            "speaker_assignments": speaker_assignments,
        }

        if session_unmatched:
            for name in session_unmatched:
                emit(f"[WARN] Speaker not found in Brella: {name}", log_callback=log_callback)

        session_changes = (
            _diff_timeslot(rec["title"], start_time, end_time, rec["duration"], existing_ts)
            if existing_ts else []
        )
        speaker_changes = (
            _diff_speaker_assignments(
                existing_ts,
                speaker_assignments,
                speaker_id_name_map,
                speaker_assignment_map,
            )
            if existing_ts else []
        )
        all_changes = (session_changes or []) + (speaker_changes or [])
        speakers_need_recreate = bool(speaker_changes)

        if dry_run:
            if existing_ts and not all_changes:
                skipped.append(session_name)
                emit(f"[SKIP] no changes: {session_name}",
                     log_callback=log_callback)
            elif existing_ts and not update_existing:
                skipped.append(session_name)
                diff_str = _format_changes(all_changes)
                emit(
                    f"[SKIP] would skip (existing, changes available): "
                    f"{session_name} · {diff_str}",
                    log_callback=log_callback,
                )
            elif existing_ts:
                updated.append(session_name)
                diff_str = _format_changes(all_changes)
                emit(
                    f"[PREVIEW] line {rec.get('line_num', '?')}: would update "
                    f"{session_name} · {diff_str}",
                    log_callback=log_callback,
                )
            else:
                added.append(session_name)
                emit(
                    f"[PREVIEW] line {rec.get('line_num', '?')}: would add "
                    f"{session_name} @ {rec['start_time']}"
                    f"{_speakers_info(rec['speaker_names'])}",
                    log_callback=log_callback,
                )
            continue

        if existing_ts and not all_changes:
            skipped.append(session_name)
            emit(f"[SKIP] no changes: {session_name}",
                 log_callback=log_callback)
            continue

        if existing_ts and not update_existing:
            skipped.append(session_name)
            diff_str = _format_changes(all_changes)
            emit(
                f"[SKIP] existing, changes available: "
                f"{session_name} · {diff_str}",
                log_callback=log_callback,
            )
            continue

        try:
            ts_id = None
            if existing_ts:
                ts_id = existing_ts["id"]
                if speakers_need_recreate:

                    status, resp = _recreate_timeslot_with_speakers(
                        headers, org, event, ts_id, payload, log_callback=log_callback)
                    if status in (200, 201):
                        ts_id = resp.get("data", {}).get("id") if isinstance(resp, dict) else None
                        updated.append(session_name)
                        emit(f"[OK] Updated (recreated): {session_name}{_speakers_info(rec['speaker_names'])}",
                             log_callback=log_callback)
                    else:
                        failed += 1
                        emit(f"[ERROR] line {rec['line_num']} recreate: {status} {resp}",
                             log_callback=log_callback)
                        continue
                else:
                    status, resp = update_timeslot(headers, org, event, ts_id, payload)
                    if status in (200, 201, 204):
                        updated.append(session_name)
                        emit(f"[OK] Updated: {session_name}",
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
                        _emit_log(
                            f"[OK] Admin patch — {' | '.join(parts)}",
                            log_callback=log_callback,
                            verbose_only=True,
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
            if ts.get("id") in matched_brella_ids:
                continue
            if ext_id in duplicate_ext_ids:

                emit(
                    f"[SKIP] duplicate — not removed: "
                    f"{ts.get('attributes', {}).get('title', ext_id)}",
                    log_callback=log_callback,
                )
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

    for ts in existing_timeslots:
        if ts["id"] in matched_brella_ids:
            continue
        attrs = ts.get("attributes", {})
        ts_name = attrs.get("title") or attrs.get("subtitle") or ts["id"]
        only_in_brella.append(ts_name)
    if only_in_brella:
        emit(f"[WARN] {len(only_in_brella)} session(s) in Brella but not in CSV:",
             log_callback=log_callback)
        for name in only_in_brella:
            emit(f"  - {name}", log_callback=log_callback)

    emit(
        f"Done. Created: {len(added)}, Updated: {len(updated)}, Removed: {len(removed)}, "
        f"Only in Brella: {len(only_in_brella)}, "
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
        "skipped_participants": skipped,
        "removed_participants": removed,
        "only_in_brella": only_in_brella,
        "duplicate_participants": duplicate_sessions,
        "failed": failed,
        "unmatched_speakers": unmatched_speakers,
    }
