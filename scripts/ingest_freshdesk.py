"""One-time (then incremental) export of solved Freshdesk tickets into the normalized
JSON shape build_kb.py expects: {ticket_id, subject, body, tags}.

Freshdesk API v2 docs: https://developers.freshdesk.com/api/
Auth: HTTP Basic with your API key as the username, "X" as the password.
Find your API key: Freshdesk -> profile icon (top right) -> Profile Settings -> API Key.

Usage:
    python scripts/ingest_freshdesk.py --domain your-subdomain --out data/freshdesk_export.json

Only pulls CLOSED/RESOLVED tickets (status 4 and 5) and strips anything not meant for
players: private notes (private=true) and agent-internal conversation are dropped --
only the ticket's original description and PUBLIC agent replies feed the KB, per spec
section 3's "safety, minimal version" rule.
"""
import argparse
import json
import re
import sys
import time

import requests

STATUS_CLOSED = 5
STATUS_RESOLVED = 4


def _strip_html(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html or "")
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def fetch_tickets(domain: str, api_key: str, updated_since: str | None = None):
    base = f"https://{domain}.freshdesk.com/api/v2/tickets"
    auth = (api_key, "X")
    page = 1
    tickets = []
    while True:
        params = {"per_page": 100, "page": page, "order_by": "updated_at", "order_type": "asc"}
        if updated_since:
            params["updated_since"] = updated_since
        resp = requests.get(base, auth=auth, params=params, timeout=30)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", "5"))
            print(f"[warn] rate limited, sleeping {wait}s")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        tickets.extend(batch)
        print(f"[info] fetched page {page} ({len(batch)} tickets, {len(tickets)} total)")
        if len(batch) < 100:
            break
        page += 1
    return [t for t in tickets if t.get("status") in (STATUS_CLOSED, STATUS_RESOLVED)]


def fetch_public_conversation(domain: str, api_key: str, ticket_id: int) -> str:
    """Returns concatenated PUBLIC agent replies only -- private notes excluded."""
    base = f"https://{domain}.freshdesk.com/api/v2/tickets/{ticket_id}/conversations"
    auth = (api_key, "X")
    resp = requests.get(base, auth=auth, timeout=30)
    if resp.status_code != 200:
        return ""
    parts = []
    for c in resp.json():
        if c.get("private"):
            continue  # internal note -- never feeds the KB
        if c.get("incoming"):
            continue  # that's the player talking, not the resolution
        parts.append(_strip_html(c.get("body_text") or c.get("body", "")))
    return "\n".join(p for p in parts if p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", required=True, help="Freshdesk subdomain (the X in X.freshdesk.com)")
    ap.add_argument("--api-key", default=None, help="Falls back to FRESHDESK_API_KEY env var")
    ap.add_argument("--out", default="data/freshdesk_export.json")
    ap.add_argument("--updated-since", default=None, help="ISO timestamp for incremental pulls")
    ap.add_argument("--limit", type=int, default=None, help="Cap ticket count (testing)")
    args = ap.parse_args()

    import os
    api_key = args.api_key or os.environ.get("FRESHDESK_API_KEY")
    if not api_key:
        print("[error] pass --api-key or set FRESHDESK_API_KEY", file=sys.stderr)
        sys.exit(1)

    tickets = fetch_tickets(args.domain, api_key, args.updated_since)
    if args.limit:
        tickets = tickets[: args.limit]
    print(f"[info] {len(tickets)} closed/resolved tickets to process")

    out = []
    for i, t in enumerate(tickets):
        resolution = fetch_public_conversation(args.domain, api_key, t["id"])
        out.append({
            "ticket_id": t["id"],
            "subject": t.get("subject", ""),
            "body": _strip_html(t.get("description_text") or t.get("description", "")),
            "resolution": resolution,
            "tags": t.get("tags", []),
        })
        if (i + 1) % 25 == 0:
            print(f"[info] processed {i + 1}/{len(tickets)}")

    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[info] wrote {len(out)} tickets -> {args.out}")


if __name__ == "__main__":
    main()
