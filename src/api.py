import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib import parse
from urllib import error, request


def get_runtime_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_runtime_file(filename):
    runtime_dir = get_runtime_dir()

    candidate_paths = [runtime_dir / filename]

    if getattr(sys, "frozen", False):
        candidate_paths.append(runtime_dir.parent / filename)

    for candidate in candidate_paths:
        if candidate.exists():
            return candidate

    return candidate_paths[0]


RUNTIME_DIR = get_runtime_dir()
ENV_FILE = resolve_runtime_file(".env")
DEFAULT_THREECKET_CSV_URL = (
    "https://app.3cket.com/webservices/backoffice/event-manager/participants/"
    "participants-info-csv.php?eventExternalId=d16f4292debc4eb6aaaafbf36f2af562"
)


def load_env_file(env_path):
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file(ENV_FILE)

ORG_ID = os.getenv("BRELLA_ORG_ID", "1218")
EVENT_ID = os.getenv("BRELLA_EVENT_ID", "10672")
API_KEY = os.getenv("BRELLA_API_KEY", "")
REQUEST_DELAY_SECONDS = float(os.getenv("BRELLA_REQUEST_DELAY") or "0.2")
EXTERNAL_QR_COLUMN = int(os.getenv("BRELLA_EXTERNAL_QR_COLUMN", "0"))
AUTH_HEADER_NAME = os.getenv("BRELLA_AUTH_HEADER_NAME", "Brella-API-Access-Token")
AUTH_HEADER_PREFIX = os.getenv("BRELLA_AUTH_HEADER_PREFIX", "")
PREFLIGHT_URL_TEMPLATE = os.getenv(
    "BRELLA_PREFLIGHT_URL",
    "https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}",
)
INVITES_URL_TEMPLATE = os.getenv(
    "BRELLA_INVITES_URL",
    "https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}/invites",
)
LIST_INVITES_URL_TEMPLATE = os.getenv(
    "BRELLA_LIST_INVITES_URL",
    INVITES_URL_TEMPLATE,
)
FIND_INVITE_URL_TEMPLATE = os.getenv(
    "BRELLA_FIND_INVITE_URL",
    "https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}/invites/find/",
)
UPDATE_INVITE_URL_TEMPLATE = os.getenv(
    "BRELLA_UPDATE_INVITE_URL",
    "https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}/invites/{invite_id}",
)
DELETE_INVITE_URL_TEMPLATE = os.getenv(
    "BRELLA_DELETE_INVITE_URL",
    UPDATE_INVITE_URL_TEMPLATE,
)
USER_AGENT = os.getenv(
    "BRELLA_HTTP_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
)
THREECKET_CSV_URL = os.getenv("THREECKET_CSV_URL", DEFAULT_THREECKET_CSV_URL).strip()
THREECKET_COOKIE = os.getenv("THREECKET_COOKIE", "").strip()
THREECKET_AUTH_HEADER_NAME = os.getenv("THREECKET_AUTH_HEADER_NAME", "").strip()
THREECKET_AUTH_HEADER_VALUE = os.getenv("THREECKET_AUTH_HEADER_VALUE", "").strip()
THREECKET_HTTP_USER_AGENT = os.getenv("THREECKET_HTTP_USER_AGENT", USER_AGENT).strip()
TICKETS_COLUMN = int(os.getenv("BRELLA_TICKETS_COLUMN", "10"))

BRELLA_ATTENDEE_GROUP_IDS = {
    "general": "36042",
    "sponsors": "36043",
    "investors": "36333",
    "speakers": "36334",
    "partners": "36335",
    "incubators": "36336",
    "corporate": "36337",
    "startup_showcase": "36338",
    "startup_simple": "36339",
    "student": "36340",
    "guest": "36341",
    "press_media": "36342",
    "staff": "36343",
}

GROUP_PRIORITY = [
    BRELLA_ATTENDEE_GROUP_IDS["startup_showcase"],
    BRELLA_ATTENDEE_GROUP_IDS["startup_simple"],
    BRELLA_ATTENDEE_GROUP_IDS["investors"],
    BRELLA_ATTENDEE_GROUP_IDS["corporate"],
    BRELLA_ATTENDEE_GROUP_IDS["incubators"],
    BRELLA_ATTENDEE_GROUP_IDS["speakers"],
    BRELLA_ATTENDEE_GROUP_IDS["partners"],
    BRELLA_ATTENDEE_GROUP_IDS["student"],
    BRELLA_ATTENDEE_GROUP_IDS["general"],
]

TICKET_TYPE_TO_GROUP_ID = {
    "corporate//1st wave": BRELLA_ATTENDEE_GROUP_IDS["corporate"],
    "corporate//2nd wave": BRELLA_ATTENDEE_GROUP_IDS["corporate"],
    "corporate//early bird": BRELLA_ATTENDEE_GROUP_IDS["corporate"],
    "corporate ticket//super early bird": BRELLA_ATTENDEE_GROUP_IDS["corporate"],
    "corporate ticket//early bird": BRELLA_ATTENDEE_GROUP_IDS["corporate"],
    "corporate ticket//standard": BRELLA_ATTENDEE_GROUP_IDS["corporate"],
    "corporate atendee": BRELLA_ATTENDEE_GROUP_IDS["corporate"],
    "digital ticket": BRELLA_ATTENDEE_GROUP_IDS["general"],
    "general//1st wave": BRELLA_ATTENDEE_GROUP_IDS["general"],
    "general//2nd wave": BRELLA_ATTENDEE_GROUP_IDS["general"],
    "general//early bird": BRELLA_ATTENDEE_GROUP_IDS["general"],
    "general//super early bird": BRELLA_ATTENDEE_GROUP_IDS["general"],
    "general//standard": BRELLA_ATTENDEE_GROUP_IDS["general"],
    "general//late release": BRELLA_ATTENDEE_GROUP_IDS["general"],
    "general atendee": BRELLA_ATTENDEE_GROUP_IDS["general"],
    "general invite": BRELLA_ATTENDEE_GROUP_IDS["general"],
    "incubator/accelerator//1st wave": BRELLA_ATTENDEE_GROUP_IDS["incubators"],
    "incubator/accelerator//2nd wave": BRELLA_ATTENDEE_GROUP_IDS["incubators"],
    "incubator/accelerator//early bird": BRELLA_ATTENDEE_GROUP_IDS["incubators"],
    "incubator/accelerator//super early bird": BRELLA_ATTENDEE_GROUP_IDS["incubators"],
    "incubator/accelerator//standard": BRELLA_ATTENDEE_GROUP_IDS["incubators"],
    "incubator/accelerator//late release": BRELLA_ATTENDEE_GROUP_IDS["incubators"],
    "incubator showcase ticket": BRELLA_ATTENDEE_GROUP_IDS["incubators"],
    "rni incubator/accelerator//invite": BRELLA_ATTENDEE_GROUP_IDS["incubators"],
    "investor/": BRELLA_ATTENDEE_GROUP_IDS["investors"],
    "/investor": BRELLA_ATTENDEE_GROUP_IDS["investors"],
    "investor//1st wave": BRELLA_ATTENDEE_GROUP_IDS["investors"],
    "investor//2nd wave": BRELLA_ATTENDEE_GROUP_IDS["investors"],
    "investor//early bird": BRELLA_ATTENDEE_GROUP_IDS["investors"],
    "investor//super early bird": BRELLA_ATTENDEE_GROUP_IDS["investors"],
    "investor//standard": BRELLA_ATTENDEE_GROUP_IDS["investors"],
    "investor//late release": BRELLA_ATTENDEE_GROUP_IDS["investors"],
    "partner/": BRELLA_ATTENDEE_GROUP_IDS["partners"],
    "/partner": BRELLA_ATTENDEE_GROUP_IDS["partners"],
    "speaker/": BRELLA_ATTENDEE_GROUP_IDS["speakers"],
    "/speaker": BRELLA_ATTENDEE_GROUP_IDS["speakers"],
    "startup/": BRELLA_ATTENDEE_GROUP_IDS["startup_simple"],
    "startup showcase 2nd ticket": BRELLA_ATTENDEE_GROUP_IDS["startup_showcase"],
    "startup showcase//2nd ticket": BRELLA_ATTENDEE_GROUP_IDS["startup_showcase"],
    "startup showcase ticket//1st wave": BRELLA_ATTENDEE_GROUP_IDS["startup_showcase"],
    "startup showcase ticket//2nd wave": BRELLA_ATTENDEE_GROUP_IDS["startup_showcase"],
    "startup showcase ticket//early bird": BRELLA_ATTENDEE_GROUP_IDS["startup_showcase"],
    "startup showcase ticket//super early bird": BRELLA_ATTENDEE_GROUP_IDS["startup_showcase"],
    "startup showcase ticket//standard": BRELLA_ATTENDEE_GROUP_IDS["startup_showcase"],
    "startup showcase ticket//late release": BRELLA_ATTENDEE_GROUP_IDS["startup_showcase"],
    "startup simple ticket": BRELLA_ATTENDEE_GROUP_IDS["startup_simple"],
    "startup simple ticket//1st wave": BRELLA_ATTENDEE_GROUP_IDS["startup_simple"],
    "startup simple ticket//2nd wave": BRELLA_ATTENDEE_GROUP_IDS["startup_simple"],
    "startup simple ticket//early bird": BRELLA_ATTENDEE_GROUP_IDS["startup_simple"],
    "startup simple ticket//super early bird": BRELLA_ATTENDEE_GROUP_IDS["startup_simple"],
    "startup simple ticket//standard": BRELLA_ATTENDEE_GROUP_IDS["startup_simple"],
    "startup simple ticket//late release": BRELLA_ATTENDEE_GROUP_IDS["startup_simple"],
    "student": BRELLA_ATTENDEE_GROUP_IDS["student"],
    "student//standard": BRELLA_ATTENDEE_GROUP_IDS["student"],
}


CONFIG_FILE = RUNTIME_DIR / "config.json"


def _load_config():

    global BRELLA_ATTENDEE_GROUP_IDS, GROUP_PRIORITY, TICKET_TYPE_TO_GROUP_ID
    if not CONFIG_FILE.exists():
        return
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if "attendee_groups" in data and data["attendee_groups"]:
            BRELLA_ATTENDEE_GROUP_IDS = data["attendee_groups"]
        if "group_priority" in data and data["group_priority"]:
            GROUP_PRIORITY = data["group_priority"]
        if "ticket_type_to_group" in data and data["ticket_type_to_group"]:
            TICKET_TYPE_TO_GROUP_ID = data["ticket_type_to_group"]
    except Exception:
        pass


def save_config(attendee_groups=None, group_priority=None, ticket_type_to_group=None):

    global BRELLA_ATTENDEE_GROUP_IDS, GROUP_PRIORITY, TICKET_TYPE_TO_GROUP_ID
    data = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    if attendee_groups is not None:
        data["attendee_groups"] = attendee_groups
        BRELLA_ATTENDEE_GROUP_IDS = attendee_groups
    if group_priority is not None:
        data["group_priority"] = group_priority
        GROUP_PRIORITY = group_priority
    if ticket_type_to_group is not None:
        data["ticket_type_to_group"] = ticket_type_to_group
        TICKET_TYPE_TO_GROUP_ID = ticket_type_to_group
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")


_load_config()


def emit(message, log_callback=None):
    print(message)
    if log_callback:
        log_callback(message)


def normalize_export_line(raw_line):
    line = raw_line.strip()
    if line.startswith('"') and line.endswith('"'):
        return line[1:-1]
    return line


def clean_csv_value(value):
    cleaned = value.strip().replace('""', '"')
    while cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) >= 2:
        cleaned = cleaned[1:-1].strip()
    return cleaned.strip('"').strip()


def build_threecket_headers():
    headers = {
        "User-Agent": THREECKET_HTTP_USER_AGENT,
        "Accept": "text/csv,application/octet-stream;q=0.9,*/*;q=0.8",
    }

    if THREECKET_COOKIE:
        headers["Cookie"] = THREECKET_COOKIE

    if THREECKET_AUTH_HEADER_NAME and THREECKET_AUTH_HEADER_VALUE:
        headers[THREECKET_AUTH_HEADER_NAME] = THREECKET_AUTH_HEADER_VALUE

    return headers


def download_threecket_csv(csv_path, log_callback=None):
    if not THREECKET_CSV_URL:
        return False

    headers = build_threecket_headers()
    http_request = request.Request(THREECKET_CSV_URL, headers=headers, method="GET")

    try:
        with request.urlopen(http_request, timeout=60) as response:
            csv_bytes = response.read()
    except error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401:
            raise RuntimeError(
                "O download do CSV da 3cket devolveu 401. Define THREECKET_COOKIE no .env "
                "ou configura THREECKET_AUTH_HEADER_NAME e THREECKET_AUTH_HEADER_VALUE com a autenticacao certa."
            ) from exc
        raise RuntimeError(
            f"Falha ao descarregar o CSV da 3cket: {exc.code} - {response_text}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(f"Falha ao descarregar o CSV da 3cket: {exc.reason}") from exc

    csv_text = csv_bytes.decode("utf-8-sig", errors="replace")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(csv_text, encoding="utf-8", newline="")

    emit(f"[OK] CSV descarregado da 3cket para: {csv_path}", log_callback=log_callback)
    return True


def iter_threecket_rows(csv_path):
    with csv_path.open(mode="r", encoding="utf-8-sig", newline="") as handle:
        header_skipped = False
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue

            normalized_line = normalize_export_line(raw_line)
            row = next(csv.reader([normalized_line], delimiter=";"))

            if not header_skipped:
                header_skipped = True
                continue

            yield line_number, row


def split_name(full_name):
    name_parts = [part for part in full_name.split() if part]
    if not name_parts:
        return "Unknown", "."
    if len(name_parts) == 1:
        return name_parts[0], "."
    return name_parts[0], " ".join(name_parts[1:])


def pick_email(row):
    for index in (3, 12):
        if len(row) > index and row[index].strip():
            return row[index].strip().lower()
    return ""


def pick_threecket_id(row):
    return clean_csv_value(row[0]) if len(row) > 0 else ""


def pick_full_name(row):
    return clean_csv_value(row[1]) if len(row) > 1 else ""


def format_participant_label(row):
    full_name = pick_full_name(row) or "Sem nome"
    threecket_id = pick_threecket_id(row)

    if threecket_id:
        return f"{full_name} (ID 3cket: {threecket_id})"

    return full_name


def pick_external_qr(row, fallback_value):
    if 0 <= EXTERNAL_QR_COLUMN < len(row):
        qr_value = clean_csv_value(row[EXTERNAL_QR_COLUMN])
        if qr_value:
            return qr_value
    return fallback_value


def normalize_ticket_type(ticket_type):
    normalized = re.sub(r"\s+", " ", str(ticket_type or "").strip().lower())
    normalized = re.sub(r"\s*//\s*", "//", normalized)
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    return normalized


def pick_ticket_types(row):
    if not (0 <= TICKETS_COLUMN < len(row)):
        return []

    raw_tickets = clean_csv_value(row[TICKETS_COLUMN])
    if not raw_tickets:
        return []

    tickets = [clean_csv_value(part) for part in raw_tickets.split("|")]
    return [ticket for ticket in tickets if ticket]


def map_ticket_type_to_group_id(ticket_type):
    normalized = normalize_ticket_type(ticket_type)

    if normalized in TICKET_TYPE_TO_GROUP_ID:
        return TICKET_TYPE_TO_GROUP_ID[normalized]

    if normalized.startswith("student//") and "standard" not in normalized:
        return BRELLA_ATTENDEE_GROUP_IDS["student"]

    if "startup showcase" in normalized:
        return BRELLA_ATTENDEE_GROUP_IDS["startup_showcase"]
    if "startup simple" in normalized or normalized in ("startup", "startup/"):
        return BRELLA_ATTENDEE_GROUP_IDS["startup_simple"]
    if "incubator" in normalized or "accelerator" in normalized:
        return BRELLA_ATTENDEE_GROUP_IDS["incubators"]
    if "investor" in normalized:
        return BRELLA_ATTENDEE_GROUP_IDS["investors"]
    if "corporate" in normalized:
        return BRELLA_ATTENDEE_GROUP_IDS["corporate"]
    if "partner" in normalized:
        return BRELLA_ATTENDEE_GROUP_IDS["partners"]
    if "speaker" in normalized:
        return BRELLA_ATTENDEE_GROUP_IDS["speakers"]
    if "student" in normalized:
        return BRELLA_ATTENDEE_GROUP_IDS["student"]
    if "general" in normalized or "digital ticket" in normalized:
        return BRELLA_ATTENDEE_GROUP_IDS["general"]

    return ""


def pick_attendee_group_id(row):
    mapped_group_ids = []

    for ticket_type in pick_ticket_types(row):
        group_id = map_ticket_type_to_group_id(ticket_type)
        if group_id and group_id not in mapped_group_ids:
            mapped_group_ids.append(group_id)

    if not mapped_group_ids:
        return ""

    if len(mapped_group_ids) == 1:
        return mapped_group_ids[0]

    for group_id in GROUP_PRIORITY:
        if group_id in mapped_group_ids:
            return group_id

    return mapped_group_ids[0]


def build_payload(row):
    threecket_id = pick_threecket_id(row)
    full_name = pick_full_name(row)
    email = pick_email(row)
    company = clean_csv_value(row[13]) if len(row) > 13 else ""

    external_id = email
    external_qr_string = pick_external_qr(row, threecket_id or external_id)
    attendee_group_id = pick_attendee_group_id(row)

    if not email:
        raise ValueError("Missing attendee email")

    first_name, last_name = split_name(full_name)
    if first_name == first_name.upper() and len(first_name) > 1:
        first_name = first_name.title()
    if last_name == last_name.upper() and len(last_name) > 1:
        last_name = last_name.title()

    payload = {
        "event_invite": {
            "external_email": email,
            "external_id": external_id,
            "external_first_name": first_name,
            "external_last_name": last_name,
            "seats": 1,
            "external_company": company,
            "external_qr_string": external_qr_string,
        },
        "import_interest_selections": False,
        "import_identity_selections": False,
    }

    if attendee_group_id:
        payload["event_invite"]["attendee_group_id"] = attendee_group_id

    return payload


def build_url(template):
    try:
        return template.format(org_id=ORG_ID, event_id=EVENT_ID)
    except KeyError as exc:
        raise RuntimeError(
            "Brella URL templates must use {org_id} and {event_id} placeholders if overridden."
        ) from exc


def build_update_url(invite_id):
    try:
        return UPDATE_INVITE_URL_TEMPLATE.format(
            org_id=ORG_ID,
            event_id=EVENT_ID,
            invite_id=invite_id,
        )
    except KeyError as exc:
        raise RuntimeError(
            "BRELLA_UPDATE_INVITE_URL must use {org_id}, {event_id}, and {invite_id} placeholders if overridden."
        ) from exc


def build_delete_url(invite_id):
    try:
        return DELETE_INVITE_URL_TEMPLATE.format(
            org_id=ORG_ID,
            event_id=EVENT_ID,
            invite_id=invite_id,
        )
    except KeyError as exc:
        raise RuntimeError(
            "BRELLA_DELETE_INVITE_URL must use {org_id}, {event_id}, and {invite_id} placeholders if overridden."
        ) from exc


def payload_email(payload):
    return payload["event_invite"]["external_email"]


def payload_external_id(payload):
    return payload["event_invite"]["external_id"]


def payload_external_qr(payload):
    return payload["event_invite"].get("external_qr_string", "")


def payload_attendee_group_id(payload):
    return payload["event_invite"].get("attendee_group_id", "")


def payload_participant_label(payload):
    event_invite = payload.get("event_invite", {})
    first_name = str(event_invite.get("external_first_name", "")).strip()
    last_name = str(event_invite.get("external_last_name", "")).strip()
    email = str(event_invite.get("external_email", "")).strip().lower()
    external_id = str(event_invite.get("external_id", "")).strip()

    full_name = " ".join(part for part in (first_name, last_name) if part and part != ".")
    if full_name and email:
        return f"{full_name} <{email}>"
    if full_name and external_id:
        return f"{full_name} (ID 3cket: {external_id})"
    if email:
        return email
    if external_id:
        return f"ID 3cket: {external_id}"
    return "Participante sem identificacao"


def build_request_headers():
    if not API_KEY:
        raise RuntimeError("Set BRELLA_API_KEY in your environment or .env before running the importer.")

    auth_value = f"{AUTH_HEADER_PREFIX}{API_KEY}"

    return {
        AUTH_HEADER_NAME: auth_value,
        "Content-Type": "application/json",
        "Accept": "application/vnd.brella.v4+json",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": USER_AGENT,
    }


def api_request(url, headers, method, payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    http_request = request.Request(url, data=body, headers=headers, method=method)

    try:
        with request.urlopen(http_request, timeout=30) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except error.URLError as exc:
        raise RuntimeError(f"Brella request failed: {exc.reason}") from exc


def create_invite(url, headers, payload):
    return api_request(url, headers, "POST", payload)


def update_invite(url, headers, payload):
    return api_request(url, headers, "PATCH", payload)


def delete_invite(url, headers):
    return api_request(url, headers, "DELETE")


def sleep_request_delay():
    if REQUEST_DELAY_SECONDS > 0:
        time.sleep(REQUEST_DELAY_SECONDS)


def find_invite_by_external_id(headers, external_id):
    base_url = build_url(FIND_INVITE_URL_TEMPLATE)
    query = parse.urlencode({"external_id": external_id})
    status_code, response_text = api_request(f"{base_url}?{query}", headers, "GET")

    if status_code == 404:
        return None
    if status_code != 200:
        raise RuntimeError(
            f"Brella find invite failed for external_id {external_id}: {status_code} - {response_text}"
        )

    response_json = json.loads(response_text)
    data = response_json.get("data")
    if not data:
        return None
    if isinstance(data, list):
        return data[0].get("id") if data else None
    return data.get("id")


def row_is_staff(row):

    for ticket in pick_ticket_types(row):
        if "staff" in ticket.lower():
            return True
    return False


def collect_csv_payloads(csv_path, limit=0, staff_only=False, reverse_order=False):
    csv_records = []
    invalid_rows = []

    if reverse_order:
        for line_number, row in iter_threecket_rows(csv_path):
            if staff_only and not row_is_staff(row):
                continue

            try:
                payload = build_payload(row)
                csv_records.append((line_number, payload))
            except ValueError as exc:
                invalid_rows.append(
                    {
                        "line_number": line_number,
                        "participant": format_participant_label(row),
                        "reason": str(exc),
                    }
                )

        csv_records.reverse()
        if limit:
            csv_records = csv_records[:limit]
        return csv_records, invalid_rows

    for line_number, row in iter_threecket_rows(csv_path):
        if limit and len(csv_records) >= limit:
            break

        if staff_only and not row_is_staff(row):
            continue

        try:
            payload = build_payload(row)
            csv_records.append((line_number, payload))
        except ValueError as exc:
            invalid_rows.append(
                {
                    "line_number": line_number,
                    "participant": format_participant_label(row),
                    "reason": str(exc),
                }
            )

    return csv_records, invalid_rows


def print_invalid_rows(invalid_rows, log_callback=None):
    for invalid_row in invalid_rows:
        reason = invalid_row["reason"]
        participant = invalid_row["participant"]
        line_number = invalid_row["line_number"]

        if reason == "Missing attendee email":
            emit(
                f"[SKIPPED] line {line_number}: attendee with no email - {participant}",
                log_callback=log_callback,
            )
            continue

        if reason == "Missing 3cket attendee ID":
            emit(
                f"[SKIPPED] line {line_number}: attendee with no 3cket ID - {participant}",
                log_callback=log_callback,
            )
            continue

        emit(
            f"[SKIPPED] line {line_number}: {participant} - {reason}",
            log_callback=log_callback,
        )


def extract_invite_external_id(invite):
    if not isinstance(invite, dict):
        return ""

    event_invite = invite.get("event_invite")
    if isinstance(event_invite, dict):
        external_id = event_invite.get("external_id")
        if external_id:
            return str(external_id).strip()

    for key in ("external_id", "externalId"):
        external_id = invite.get(key)
        if external_id:
            return str(external_id).strip()

    attributes = invite.get("attributes")
    if isinstance(attributes, dict):
        for key in ("external_id", "externalId", "external-id"):
            external_id = attributes.get(key)
            if external_id:
                return str(external_id).strip()

    return ""


def extract_invite_email(invite):
    if not isinstance(invite, dict):
        return ""

    event_invite = invite.get("event_invite")
    if isinstance(event_invite, dict):
        email = event_invite.get("external_email")
        if email:
            return str(email).strip().lower()

    for key in ("external_email", "externalEmail", "email"):
        email = invite.get(key)
        if email:
            return str(email).strip().lower()

    attributes = invite.get("attributes")
    if isinstance(attributes, dict):
        for key in ("external_email", "externalEmail", "external-email", "email"):
            email = attributes.get(key)
            if email:
                return str(email).strip().lower()

    return ""


def extract_invite_name(invite):
    if not isinstance(invite, dict):
        return ""

    event_invite = invite.get("event_invite")
    if isinstance(event_invite, dict):
        first_name = str(event_invite.get("external_first_name", "")).strip()
        last_name = str(event_invite.get("external_last_name", "")).strip()
        full_name = " ".join(part for part in (first_name, last_name) if part and part != ".")
        if full_name:
            return full_name

    attributes = invite.get("attributes")
    if isinstance(attributes, dict):
        first_name = str(
            attributes.get("external-first-name") or attributes.get("external_first_name") or ""
        ).strip()
        last_name = str(
            attributes.get("external-last-name") or attributes.get("external_last_name") or ""
        ).strip()
        full_name = " ".join(part for part in (first_name, last_name) if part and part != ".")
        if full_name:
            return full_name

    return ""


def format_removed_participant_label(candidate):
    name = str(candidate.get("name", "")).strip()
    email = str(candidate.get("email", "")).strip().lower()
    external_id = str(candidate.get("external_id", "")).strip()

    if name and email:
        return f"{name} <{email}>"
    if name and external_id:
        return f"{name} (ID 3cket: {external_id})"
    if email:
        return email
    if external_id:
        return f"ID 3cket: {external_id}"
    return "Participante removido sem identificacao"


def print_summary_list(title, items, log_callback=None):
    emit(f"\n{title} ({len(items)}):", log_callback=log_callback)
    if not items:
        emit("- none", log_callback=log_callback)
        return

    for item in items:
        emit(f"- {item}", log_callback=log_callback)


def print_final_lists(
    missing_email_participants,
    added_participants,
    updated_participants,
    removed_participants,
    log_callback=None,
):
    print_summary_list(
        "Attendees without email in 3cket",
        missing_email_participants,
        log_callback=log_callback,
    )
    print_summary_list(
        "Added",
        added_participants,
        log_callback=log_callback,
    )
    print_summary_list(
        "Updated",
        updated_participants,
        log_callback=log_callback,
    )
    print_summary_list(
        "Removed",
        removed_participants,
        log_callback=log_callback,
    )


def list_invites(headers):
    base_url = build_url(LIST_INVITES_URL_TEMPLATE)
    status_code, response_text = api_request(base_url, headers, "GET")

    if status_code != 200:
        raise RuntimeError(
            f"Brella list invites failed: {status_code} - {response_text}"
        )

    response_json = json.loads(response_text)
    data = response_json.get("data")
    if not isinstance(data, list):
        raise RuntimeError(
            "Brella list invites response did not include a list in the data field."
        )

    meta = response_json.get("meta")

    if isinstance(meta, dict):
        total_pages = meta.get("total_pages")
        if isinstance(total_pages, int) and total_pages > 1:
            raise RuntimeError(
                "Brella invite listing reports multiple pages, but the current API rejected page query parameters. "
                "Set BRELLA_LIST_INVITES_URL to a listing endpoint that returns all invites for the event."
            )

    return data


def build_existing_invite_id_map(headers, invites=None):
    if invites is None:
        invites = list_invites(headers)
    invite_map = {}
    email_map = {}
    seen_ext_ids = set()
    seen_emails = set()
    duplicates = []

    for invite in invites:
        if not isinstance(invite, dict):
            continue

        invite_id = str(invite.get("id") or "").strip()
        if not invite_id:
            continue

        external_id = extract_invite_external_id(invite)
        email = extract_invite_email(invite)
        name = extract_invite_name(invite)

        dup_reason = None
        if external_id and external_id in seen_ext_ids:
            dup_reason = f"external_id {external_id}"
        elif email and email in seen_emails:
            dup_reason = f"email {email}"
        if dup_reason:
            label = name or email or external_id or invite_id
            duplicates.append(f"{label} (duplicate {dup_reason}, invite {invite_id})")

        if external_id:
            invite_map[external_id] = invite_id
            seen_ext_ids.add(external_id)
        if email:
            email_map[email] = invite_id
            seen_emails.add(email)

    return invite_map, email_map, duplicates, invites


def preflight_check(url, headers):
    return api_request(url, headers, "GET")


def collect_prune_candidates(
    headers,
    desired_external_ids,
    desired_emails=None,
    existing_invites=None,
):
\
\
\

    if existing_invites is None:
        existing_invites = list_invites(headers)
    desired_emails = desired_emails or set()
    prune_candidates = []

    for invite in existing_invites:
        invite_id = invite.get("id") if isinstance(invite, dict) else None
        if not invite_id:
            continue

        external_id = extract_invite_external_id(invite)
        email = extract_invite_email(invite)


        if not external_id and not email:
            continue

        if external_id and external_id in desired_external_ids:
            continue
        if email and email in desired_emails:
            continue

        prune_candidates.append(
            {
                "id": invite_id,
                "external_id": external_id,
                "email": email,
                "name": extract_invite_name(invite),
            }
        )

    return prune_candidates


def run_sync_v4(
    csv_path,
    dry_run=False,
    limit=0,
    prune_missing=False,
    update_existing=False,
    staff_only=False,
    log_callback=None,
    include_final_report=True,
    reverse_csv=False,
    suppress_skip_logs=False,
    stop_after_first_existing=False,
    stop_after_existing_skips=0,
):
    if prune_missing and limit:
        raise RuntimeError("--limit nao pode ser usado com prune ativo. Usa --no-prune-missing com --limit.")

    preflight_url = build_url(PREFLIGHT_URL_TEMPLATE)
    url = build_url(INVITES_URL_TEMPLATE)
    requires_api_headers = prune_missing or not dry_run
    headers = build_request_headers() if requires_api_headers else None

    if not dry_run or prune_missing:
        status_code, response_text = preflight_check(preflight_url, headers)
        if status_code == 401:
            raise RuntimeError(
                "Brella authentication failed during preflight. "
                "Check BRELLA_API_KEY and whether BRELLA_AUTH_HEADER_NAME or BRELLA_AUTH_HEADER_PREFIX need to change. "
                f"Response: {response_text}"
            )
        if status_code == 403 and "browser_signature_banned" in response_text:
            raise RuntimeError(
                "Cloudflare blocked the request before it reached Brella. "
                "Update BRELLA_HTTP_USER_AGENT in .env or ask Brella to allow your client."
            )
        if status_code == 403:
            raise RuntimeError(
                "Brella rejected the API token during preflight. "
                "Per Brella docs, the token owner may need Organization Administrator privileges. "
                f"Response: {response_text}"
            )
        if status_code == 404:
            raise RuntimeError(
                "Brella preflight returned 404 for the integration event endpoint. "
                "This usually means BRELLA_ORG_ID or BRELLA_EVENT_ID is wrong, or BRELLA_PREFLIGHT_URL needs a different path template. "
                f"URL: {preflight_url} Response: {response_text}"
            )

    existing_invite_id_map = {}
    existing_email_map = {}
    duplicate_invites = []
    existing_invites = None
    if not dry_run:
        try:
            (existing_invite_id_map, existing_email_map, duplicate_invites, existing_invites
             ) = build_existing_invite_id_map(headers)
            if not suppress_skip_logs:
                for dup_label in duplicate_invites:
                    emit(f"[DUP] {dup_label}", log_callback=log_callback)
        except Exception as exc:
            emit(
                "[WARN] Could not list existing invites before import. "
                "Falling back to per-participant lookup.",
                log_callback=log_callback,
            )
            emit(f"[WARN] detail: {exc}", log_callback=log_callback)

    csv_records, invalid_rows = collect_csv_payloads(
        csv_path,
        limit=limit,
        staff_only=staff_only,
        reverse_order=reverse_csv,
    )
    desired_external_ids = {payload_external_id(payload) for _, payload in csv_records}
    desired_emails = {
        payload_email(payload).lower()
        for _, payload in csv_records
        if payload_email(payload)
    }
    missing_email_participants = [
        invalid_row["participant"]
        for invalid_row in invalid_rows
        if invalid_row["reason"] == "Missing attendee email"
    ]
    added_participants = []
    updated_participants = []
    skipped_participants = []
    removed_participants = []

    total_valid_rows = len(csv_records)
    processed = 0
    succeeded = 0
    failed = len(invalid_rows)

    if reverse_csv:

        emit(
            "[INFO] Quick add mode: processing CSV from end (latest rows first).",
            log_callback=log_callback,
        )
    if suppress_skip_logs:
        emit(
            "[INFO] Existing attendees will be skipped silently.",
            log_callback=log_callback,
        )

    if not suppress_skip_logs:
        print_invalid_rows(invalid_rows, log_callback=log_callback)

    existing_skip_streak = 0
    find_lookup_cache = {}

    for line_number, payload in csv_records:
        processed += 1
        try:
            if dry_run:
                emit(
                    f"[SIMULATION] line {line_number}: {payload_email(payload)} -> "
                    f"external_id {payload_external_id(payload)} qr {payload_external_qr(payload)} "
                    f"group {payload_attendee_group_id(payload) or '-'}",
                    log_callback=log_callback,
                )
                continue

            external_id = payload_external_id(payload)
            email = payload_email(payload).lower()
            invite_id = existing_invite_id_map.get(external_id)
            if not invite_id and email:
                invite_id = existing_email_map.get(email)
            if not invite_id:

                if external_id in find_lookup_cache:
                    invite_id = find_lookup_cache[external_id]
                else:
                    invite_id = find_invite_by_external_id(headers, external_id)
                    find_lookup_cache[external_id] = invite_id
                if invite_id:
                    existing_invite_id_map[external_id] = invite_id
                    if email:
                        existing_email_map[email] = invite_id

            if invite_id and not update_existing:
                existing_skip_streak += 1
                participant_label = payload_participant_label(payload)
                if not suppress_skip_logs:
                    skipped_participants.append(participant_label)
                    emit(
                        f"[SKIP] already exists: {payload_email(payload)}",
                        log_callback=log_callback,
                    )

                stop_on_existing = stop_after_first_existing or (
                    stop_after_existing_skips
                    and existing_skip_streak >= stop_after_existing_skips
                )
                if stop_on_existing:

                    if stop_after_existing_skips:
                        emit(
                            f"[INFO] Quick add complete: reached {stop_after_existing_skips} consecutive attendees that already exist in Brella.",
                            log_callback=log_callback,
                        )
                    else:
                        emit(
                            "[INFO] Quick add complete: reached an attendee that already exists in Brella.",
                            log_callback=log_callback,
                        )
                    break

                continue

            existing_skip_streak = 0

            if invite_id:
                status_code, response_text = update_invite(
                    build_update_url(invite_id),
                    headers,
                    payload,
                )
                operation = "UPDATED"
            else:
                status_code, response_text = create_invite(url, headers, payload)
                operation = "ADDED"


            if status_code in (200, 201):
                succeeded += 1
                participant_label = payload_participant_label(payload)
                if operation == "ADDED":
                    added_participants.append(participant_label)
                else:
                    updated_participants.append(participant_label)
                emit(
                    f"[OK {succeeded}] {operation}: {payload_email(payload)}",
                    log_callback=log_callback,
                )
            else:
                failed += 1
                if status_code == 403 and "browser_signature_banned" in response_text:
                    response_text = (
                        "Cloudflare blocked the request before it reached Brella. "
                        "Update BRELLA_HTTP_USER_AGENT in .env or ask Brella to allow your client. "
                        f"Raw response: {response_text}"
                    )
                emit(
                    f"[ERROR] line {line_number} {payload_email(payload)}: "
                    f"{status_code} - {response_text}",
                    log_callback=log_callback,
                )

            sleep_request_delay()
        except Exception as exc:
            failed += 1
            emit(f"[SKIPPED] line {line_number}: {exc}", log_callback=log_callback)

    if prune_missing:
        prune_candidates = collect_prune_candidates(
            headers,
            desired_external_ids,
            desired_emails,
            existing_invites=existing_invites,
        )

        if dry_run:
            for candidate in prune_candidates:
                email_suffix = f" ({candidate['email']})" if candidate["email"] else ""
                emit(
                    f"[SIMULACAO] remover convite {candidate['id']}: "
                    f"external_id {candidate['external_id']}{email_suffix}",
                    log_callback=log_callback,
                )
        else:
            for candidate in prune_candidates:
                status_code, response_text = delete_invite(
                    build_delete_url(candidate["id"]),
                    headers,
                )
                email_suffix = f" ({candidate['email']})" if candidate["email"] else ""

                if status_code in (200, 202, 204):
                    succeeded += 1
                    removed_participants.append(format_removed_participant_label(candidate))
                    emit(
                        f"[OK {succeeded}] REMOVED: {candidate['external_id']}{email_suffix}",
                        log_callback=log_callback,
                    )
                else:
                    failed += 1
                    emit(
                        f"[ERROR] remove invite {candidate['id']} {candidate['external_id']}: "
                        f"{status_code} - {response_text}",
                        log_callback=log_callback,
                    )

                sleep_request_delay()

    if include_final_report:
        if processed < total_valid_rows:
            processed_msg = f"Processed {processed}/{total_valid_rows} rows"
        else:
            processed_msg = f"Processed {processed} rows"
        emit(
            f"{processed_msg}. "
            f"Succeeded: {succeeded}. Failed or skipped: {failed}.",
            log_callback=log_callback,
        )
        print_final_lists(
            missing_email_participants,
            added_participants,
            updated_participants,
            removed_participants,
            log_callback=log_callback,
        )

    return {
        "processed": processed,
        "succeeded": succeeded,
        "failed": failed,
        "missing_email_participants": missing_email_participants,
        "added_participants": added_participants,
        "updated_participants": updated_participants,
        "skipped_participants": skipped_participants,
        "removed_participants": removed_participants,
        "duplicate_participants": [] if suppress_skip_logs else duplicate_invites,
    }


def preview_sync_v4(
    csv_path,
    limit=0,
    prune_missing=False,
    update_existing=False,
    staff_only=False,
    log_callback=None,
    include_final_report=True,
    reverse_csv=False,
    suppress_skip_logs=False,
    stop_after_first_existing=False,
    stop_after_existing_skips=0,
):
    preflight_url = build_url(PREFLIGHT_URL_TEMPLATE)
    headers = build_request_headers()

    status_code, response_text = preflight_check(preflight_url, headers)
    if status_code == 401:
        raise RuntimeError(
            "Brella authentication failed during preflight. "
            "Check BRELLA_API_KEY and whether BRELLA_AUTH_HEADER_NAME or BRELLA_AUTH_HEADER_PREFIX need to change. "
            f"Response: {response_text}"
        )
    if status_code == 403 and "browser_signature_banned" in response_text:
        raise RuntimeError(
            "Cloudflare blocked the request before it reached Brella. "
            "Update BRELLA_HTTP_USER_AGENT in .env or ask Brella to allow your client."
        )
    if status_code == 403:
        raise RuntimeError(
            "Brella rejected the API token during preflight. "
            "Per Brella docs, the token owner may need Organization Administrator privileges. "
            f"Response: {response_text}"
        )
    if status_code == 404:
        raise RuntimeError(
            "Brella preflight returned 404 for the integration event endpoint. "
            "This usually means BRELLA_ORG_ID or BRELLA_EVENT_ID is wrong, or BRELLA_PREFLIGHT_URL needs a different path template. "
            f"URL: {preflight_url} Response: {response_text}"
        )

    (existing_invite_id_map, existing_email_map, duplicate_invites, existing_invites
     ) = build_existing_invite_id_map(headers)
    if not suppress_skip_logs:
        for dup_label in duplicate_invites:
            emit(f"[DUP] {dup_label}", log_callback=log_callback)

    csv_records, invalid_rows = collect_csv_payloads(
        csv_path,
        limit=limit,
        staff_only=staff_only,
        reverse_order=reverse_csv,
    )
    desired_external_ids = {payload_external_id(payload) for _, payload in csv_records}
    desired_emails = {
        payload_email(payload).lower()
        for _, payload in csv_records
        if payload_email(payload)
    }

    missing_email_participants = [
        invalid_row["participant"]
        for invalid_row in invalid_rows
        if invalid_row["reason"] == "Missing attendee email"
    ]
    would_add = []
    would_update = []
    would_skip = []
    would_remove = []

    total_valid_rows = len(csv_records)
    processed = 0
    existing_skip_streak = 0

    if reverse_csv:
        emit(
            "[INFO] Quick preview mode: processing CSV from end (latest rows first).",
            log_callback=log_callback,
        )
    if suppress_skip_logs:
        emit(
            "[INFO] Existing attendees will be skipped silently.",
            log_callback=log_callback,
        )

    if not suppress_skip_logs:
        print_invalid_rows(invalid_rows, log_callback=log_callback)

    for line_number, payload in csv_records:
        processed += 1
        external_id = payload_external_id(payload)
        email = payload_email(payload).lower()
        invite_id = existing_invite_id_map.get(external_id)
        if not invite_id and email:
            invite_id = existing_email_map.get(email)
        participant_label = payload_participant_label(payload)

        if invite_id and not update_existing:
            existing_skip_streak += 1
            if not suppress_skip_logs:
                would_skip.append(participant_label)
                emit(
                    f"[SKIP] would skip (already exists): {participant_label}",
                    log_callback=log_callback,
                )

            stop_on_existing = stop_after_first_existing or (
                stop_after_existing_skips
                and existing_skip_streak >= stop_after_existing_skips
            )
            if stop_on_existing:
                if stop_after_existing_skips:
                    emit(
                        f"[INFO] Quick preview complete: reached {stop_after_existing_skips} consecutive attendees that already exist in Brella.",
                        log_callback=log_callback,
                    )
                else:
                    emit(
                        "[INFO] Quick preview complete: reached an attendee that already exists in Brella.",
                        log_callback=log_callback,
                    )
                break
        elif invite_id:
            existing_skip_streak = 0
            would_update.append(participant_label)
            emit(
                f"[PREVIEW] line {line_number}: would update {participant_label}",
                log_callback=log_callback,
            )
        else:
            existing_skip_streak = 0
            would_add.append(participant_label)
            emit(
                f"[PREVIEW] line {line_number}: would add {participant_label}",
                log_callback=log_callback,
            )

    if prune_missing:
        prune_candidates = collect_prune_candidates(
            headers,
            desired_external_ids,
            desired_emails,
            existing_invites=existing_invites,
        )
        for candidate in prune_candidates:
            label = format_removed_participant_label(candidate)
            would_remove.append(label)
            emit(
                f"[PREVIEW] would remove {label}",
                log_callback=log_callback,
            )

    if include_final_report:
        if processed < total_valid_rows:
            processed_msg = f"processed {processed}/{total_valid_rows} valid rows"
        else:
            processed_msg = f"processed {processed} valid rows"
        emit(
            f"Preview complete: {processed_msg}.",
            log_callback=log_callback,
        )

        print_final_lists(
            missing_email_participants,
            would_add,
            would_update,
            would_remove,
            log_callback=log_callback,
        )

    return {
        "processed": processed,
        "failed": len(invalid_rows),
        "missing_email_participants": missing_email_participants,
        "added_participants": would_add,
        "updated_participants": would_update,
        "skipped_participants": would_skip,
        "removed_participants": would_remove,
        "duplicate_participants": [] if suppress_skip_logs else duplicate_invites,
    }


def prepare_csv(csv_path, download_csv=True, log_callback=None):
    if download_csv:
        try:
            downloaded = download_threecket_csv(csv_path, log_callback=log_callback)
            if downloaded:
                return
        except RuntimeError:

            if not csv_path.exists():
                raise
            emit(
                "[WARN] Could not download the CSV from 3cket. "
                "Using the existing local file.",
                log_callback=log_callback,
            )

    if not csv_path.exists():
        raise RuntimeError(f"CSV file not found: {csv_path}")
