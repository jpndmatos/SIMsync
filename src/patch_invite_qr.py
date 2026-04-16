"""
One-off utility: patch a single Brella invite's external_qr_string.

Useful when an invite was created outside of SIMsync (e.g. manually as Staff)
and therefore has no 3cket QR — Brella then falls back to showing the
`brella_invite_id=...` URL as the QR. This script rewrites it.

Usage:
    python src/patch_invite_qr.py --invite-id 10820087 --qr "7da366427a154ca7b425d335889c..."
    python src/patch_invite_qr.py --invite-id 10820087 --qr-from-invite 10812345
    python src/patch_invite_qr.py --invite-id 10820087 --qr "..." --dry-run

Tip: you can find the Brella invite id by opening the invite page in Brella —
it appears inside the fallback QR string (`brella_invite_id=<id>`) or in the URL.
"""

import argparse
import json
import sys

from api import (
    api_request,
    build_request_headers,
    build_update_url,
    build_url,
    LIST_INVITES_URL_TEMPLATE,
    update_invite,
)


def fetch_invite(headers, invite_id):
    url = build_update_url(invite_id)
    status_code, response_text = api_request(url, headers, "GET")
    if status_code != 200:
        raise RuntimeError(
            f"Could not fetch invite {invite_id}: {status_code} - {response_text}"
        )
    return json.loads(response_text)


def extract_qr_string(invite_response):
    # Response shape: {"data": {...}} or {"event_invite": {...}} depending on endpoint.
    data = invite_response.get("data", invite_response)
    if isinstance(data, dict):
        event_invite = data.get("event_invite", data)
        if isinstance(event_invite, dict):
            qr = event_invite.get("external_qr_string")
            if qr:
                return str(qr)
    return ""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Patch a single Brella invite's external_qr_string."
    )
    parser.add_argument("--invite-id", required=True,
                        help="Brella invite id to patch (e.g. 10820087)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--qr", help="New external_qr_string value to set")
    group.add_argument("--qr-from-invite",
                       help="Brella invite id to copy the external_qr_string from")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be patched without calling PATCH")
    return parser.parse_args()


def main():
    args = parse_args()
    headers = build_request_headers()

    if args.qr_from_invite:
        source = fetch_invite(headers, args.qr_from_invite)
        new_qr = extract_qr_string(source)
        if not new_qr:
            raise RuntimeError(
                f"Source invite {args.qr_from_invite} has no external_qr_string to copy."
            )
        print(f"Copied QR from invite {args.qr_from_invite}: {new_qr}")
    else:
        new_qr = args.qr

    target = fetch_invite(headers, args.invite_id)
    current_qr = extract_qr_string(target)
    print(f"Invite {args.invite_id} current external_qr_string: {current_qr or '(empty)'}")
    print(f"Invite {args.invite_id} new external_qr_string:     {new_qr}")

    if current_qr == new_qr:
        print("Nothing to do — values already match.")
        return

    if args.dry_run:
        print("[DRY-RUN] Skipping PATCH.")
        return

    payload = {"event_invite": {"external_qr_string": new_qr}}
    status_code, response_text = update_invite(
        build_update_url(args.invite_id), headers, payload
    )
    if status_code not in (200, 201):
        raise RuntimeError(
            f"PATCH failed: {status_code} - {response_text}"
        )
    print(f"[OK] Patched invite {args.invite_id} (status {status_code}).")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        sys.exit(1)
