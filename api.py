import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from urllib import parse
from urllib import error, request


def get_runtime_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


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
DEFAULT_CSV_PATH = resolve_runtime_file("participants.csv")
ENV_FILE = resolve_runtime_file(".env")


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
REQUEST_DELAY_SECONDS = float(os.getenv("BRELLA_REQUEST_DELAY", "0.2"))
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
LIST_PAGE_SIZE = int(os.getenv("BRELLA_LIST_PAGE_SIZE", "100"))
LIST_MAX_PAGES = int(os.getenv("BRELLA_LIST_MAX_PAGES", "100"))
PAUSE_ON_EXIT_DEFAULT = os.getenv("BRELLA_PAUSE_ON_EXIT", "auto").strip().lower()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Import 3cket attendees into Brella while preserving the 3cket QR value."
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default=str(DEFAULT_CSV_PATH),
        help="Path to the 3cket CSV export.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print payloads without sending them to Brella.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only process the first N valid attendees. Use 0 for no limit.",
    )
    parser.add_argument(
        "--prune-missing",
        action="store_true",
        help="Delete Brella invites whose external_id is not present in the CSV.",
    )
    parser.add_argument(
        "--pause-on-exit",
        action="store_true",
        help="Wait for Enter before closing at the end of execution.",
    )
    return parser.parse_args()


def should_pause_on_exit(force_pause=False):
    if force_pause:
        return True

    if PAUSE_ON_EXIT_DEFAULT in ("1", "true", "yes", "on"):
        return True
    if PAUSE_ON_EXIT_DEFAULT in ("0", "false", "no", "off"):
        return False

    return bool(getattr(sys, "frozen", False))


def pause_on_exit(force_pause=False):
    if not should_pause_on_exit(force_pause=force_pause):
        return

    try:
        input("\nCarrega em Enter para fechar...")
    except EOFError:
        pass


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


def pick_external_qr(row, fallback_value):
    if 0 <= EXTERNAL_QR_COLUMN < len(row):
        qr_value = clean_csv_value(row[EXTERNAL_QR_COLUMN])
        if qr_value:
            return qr_value
    return fallback_value


def build_payload(row):
    threecket_id = clean_csv_value(row[0]) if len(row) > 0 else ""
    full_name = clean_csv_value(row[1]) if len(row) > 1 else ""
    email = pick_email(row)
    company = clean_csv_value(row[13]) if len(row) > 13 else ""
    external_qr_string = pick_external_qr(row, threecket_id)

    if not threecket_id:
        raise ValueError("Missing 3cket attendee ID")
    if not email:
        raise ValueError("Missing attendee email")

    first_name, last_name = split_name(full_name)

    return {
        "event_invite": {
            "external_email": email,
            "external_id": threecket_id,
            "external_first_name": first_name,
            "external_last_name": last_name,
            "seats": 1,
            "external_company": company,
            "external_qr_string": external_qr_string,
        },
        "import_interest_selections": False,
        "import_identity_selections": False,
    }


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


def collect_csv_payloads(csv_path, limit=0):
    csv_records = []

    for line_number, row in iter_threecket_rows(csv_path):
        if limit and len(csv_records) >= limit:
            break

        payload = build_payload(row)
        csv_records.append((line_number, payload))

    return csv_records


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


def preflight_check(url, headers):
    return api_request(url, headers, "GET")


def run_sync_v4(csv_path, dry_run=False, limit=0, prune_missing=False):
    if prune_missing and limit:
        raise RuntimeError("--prune-missing cannot be used together with --limit.")

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

    csv_records = collect_csv_payloads(csv_path, limit=limit)
    desired_external_ids = {payload_external_id(payload) for _, payload in csv_records}

    processed = len(csv_records)
    succeeded = 0
    failed = 0

    for line_number, payload in csv_records:
        try:
            if dry_run:
                print(
                    f"[SIMULACAO] linha {line_number}: {payload_email(payload)} -> "
                    f"external_id {payload_external_id(payload)} qr {payload_external_qr(payload)}"
                )
                continue

            invite_id = find_invite_by_external_id(headers, payload_external_id(payload))
            if invite_id:
                status_code, response_text = update_invite(
                    build_update_url(invite_id),
                    headers,
                    payload,
                )
                operation = "ATUALIZADO"
            else:
                status_code, response_text = create_invite(url, headers, payload)
                operation = "ADICIONADO"

            if status_code in (200, 201):
                succeeded += 1
                print(f"[OK {succeeded}] {operation}: {payload_email(payload)}")
            else:
                failed += 1
                if status_code == 403 and "browser_signature_banned" in response_text:
                    response_text = (
                        "A Cloudflare bloqueou o pedido antes de chegar à Brella. "
                        "Atualiza BRELLA_HTTP_USER_AGENT no .env ou pede à Brella para permitir o teu IP/cliente. "
                        f"Resposta bruta: {response_text}"
                    )
                print(
                    f"[ERRO] linha {line_number} {payload_email(payload)}: "
                    f"{status_code} - {response_text}"
                )

            time.sleep(REQUEST_DELAY_SECONDS)
        except Exception as exc:
            failed += 1
            print(f"[IGNORADO] linha {line_number}: {exc}")

    if prune_missing:
        existing_invites = list_invites(headers)
        prune_candidates = []

        for invite in existing_invites:
            invite_id = invite.get("id") if isinstance(invite, dict) else None
            external_id = extract_invite_external_id(invite)

            if not invite_id or not external_id:
                continue
            if external_id in desired_external_ids:
                continue

            prune_candidates.append(
                {
                    "id": invite_id,
                    "external_id": external_id,
                    "email": extract_invite_email(invite),
                }
            )

        if dry_run:
            for candidate in prune_candidates:
                email_suffix = f" ({candidate['email']})" if candidate["email"] else ""
                print(
                    f"[SIMULACAO] remover convite {candidate['id']}: "
                    f"external_id {candidate['external_id']}{email_suffix}"
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
                    print(
                        f"[OK {succeeded}] REMOVIDO: {candidate['external_id']}{email_suffix}"
                    )
                else:
                    failed += 1
                    print(
                        f"[ERRO] remover convite {candidate['id']} {candidate['external_id']}: "
                        f"{status_code} - {response_text}"
                    )

                time.sleep(REQUEST_DELAY_SECONDS)

    print(
        f"Processados {processed} registos. "
        f"Com sucesso: {succeeded}. Falhados ou ignorados: {failed}."
    )


if __name__ == "__main__":
    try:
        args = parse_args()
        run_sync_v4(
            Path(args.csv_path),
            dry_run=args.dry_run,
            limit=args.limit,
            prune_missing=args.prune_missing,
        )
    except Exception as exc:
        print(f"[ERRO FATAL] {exc}")
    finally:
        pause_on_exit(force_pause="args" in locals() and args.pause_on_exit)