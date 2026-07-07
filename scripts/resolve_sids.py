"""SID resolution pass (PROJECT_HANDOFF §4A #3) — resolves a player SID for tickets
that lack one, by looking the ticket's sender email up in the brx_main Mongo `account`
collection, then persisting the result onto `conversations.player_id` so the
admin-panel link (https://admin.brx.indusgame.com/player/<SID>) lights up in the grid.

Confirmed schema (brx_main.account, 2026-07-06):
  - player email       -> `email.id`      (INDEXED: email.id_1 — safe for $in)
  - normalized email   -> `email.normalId` (lowercased; not indexed — used only for
                          building the local match map, never queried directly)
  - SID (admin panel)  -> `shortId`        (string; play_reviewer's PLAYER_ADMIN_URL
                          is /player/{sid} where sid == shortId — NOT the numeric _id)

Efficiency (per the "direct/bounded queries only" rule): dedupes emails, then fires
chunked `$in` queries on the indexed `email.id` (default 300/chunk). One UPDATE per
resolved conversation. Re-runnable; only fills blanks. Discord tickets have no email
(only a Discord display name), so they're skipped here.

Requires `pymongo` + `dnspython` and network — run on your machine, NOT the Claude
sandbox (no egress there). After it runs, re-sync the DB to Railway with the safe
VACUUM + WAL-clear procedure (BACKFILL_RUNBOOK §C.5).

    export MONGO_URI='mongodb+srv://...'      # do NOT commit this
    python -m scripts.resolve_sids --dry-run  # show match rate, no writes
    python -m scripts.resolve_sids            # resolve + persist
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from app import db

MONGO_URI = os.environ.get("MONGO_URI", "")
MONGO_ACCOUNT_COLLECTION = os.environ.get("MONGO_ACCOUNT_COLLECTION", "account")
MONGO_EMAIL_FIELD = os.environ.get("MONGO_EMAIL_FIELD", "email.id")
MONGO_NORMAL_EMAIL_FIELD = os.environ.get("MONGO_NORMAL_EMAIL_FIELD", "email.normalId")
MONGO_SID_FIELD = os.environ.get("MONGO_SID_FIELD", "shortId")
CHUNK = int(os.environ.get("MONGO_IN_CHUNK", "300"))

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _dig(doc: dict, dotted: str):
    cur = doc
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _email_for(conv: dict) -> str | None:
    """Best-effort player email for a conversation: context.from (email/freshdesk),
    else the first email address in the stored first-message text ('[email] ...')."""
    try:
        ctx = json.loads(conv["context"] or "{}")
    except Exception:
        ctx = {}
    frm = (ctx.get("from") or "").strip()
    if _EMAIL_RE.fullmatch(frm):
        return frm.lower()
    m = _EMAIL_RE.search(conv.get("first_text") or "")
    return m.group(0).lower() if m else None


def _load_targets(conn, limit: int):
    rows = conn.execute(
        """
        SELECT c.id, c.channel, c.context,
               (SELECT text FROM messages WHERE conversation_id = c.id ORDER BY id ASC LIMIT 1) AS first_text
        FROM conversations c
        WHERE (c.player_id IS NULL OR c.player_id = '')
        """
    ).fetchall()
    targets = []
    for r in rows:
        email = _email_for(dict(r))
        if email:
            targets.append((r["id"], email))
    if limit:
        targets = targets[:limit]
    return targets


def _bulk_lookup(emails: list[str]) -> dict[str, str]:
    """{email_lower: sid(shortId)} via chunked $in on the indexed email.id.
    Keys the map on BOTH email.id and email.normalId (lowercased) so case/normalization
    differences still match our lowercased ticket emails."""
    try:
        from pymongo import MongoClient
    except ImportError:
        sys.exit("pip install pymongo dnspython, then re-run.")
    if not MONGO_URI:
        sys.exit("Set MONGO_URI env var first (the mongodb+srv://... string).")
    cli = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    coll = cli.get_default_database()[MONGO_ACCOUNT_COLLECTION]
    proj = {MONGO_EMAIL_FIELD: 1, MONGO_NORMAL_EMAIL_FIELD: 1, MONGO_SID_FIELD: 1}
    out: dict[str, str] = {}
    uniq = sorted(set(emails))
    for i in range(0, len(uniq), CHUNK):
        chunk = uniq[i:i + CHUNK]
        for doc in coll.find({MONGO_EMAIL_FIELD: {"$in": chunk}}, proj):
            sid = _dig(doc, MONGO_SID_FIELD)
            if sid is None:
                continue
            for f in (MONGO_EMAIL_FIELD, MONGO_NORMAL_EMAIL_FIELD):
                val = _dig(doc, f)
                if isinstance(val, str) and val:
                    out[val.lower()] = str(sid)
    cli.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    db.init_db()
    conn = db.get_conn()
    targets = _load_targets(conn, args.limit)
    emails = sorted({e for _, e in targets})
    print(f"{len(targets)} tickets missing a SID, {len(emails)} distinct emails to look up.")
    if not emails:
        return 0

    sid_map = _bulk_lookup(emails)
    resolved = [(cid, sid_map[e]) for cid, e in targets if e in sid_map]
    print(f"Mongo matched {len(set(e for e in emails if e in sid_map))}/{len(emails)} emails "
          f"-> {len(resolved)} tickets resolvable.")

    if args.dry_run:
        for cid, sid in resolved[:10]:
            print(f"  conv {cid} -> shortId {sid}")
        print("--dry-run: no writes.")
        return 0

    conn.executemany("UPDATE conversations SET player_id = ? WHERE id = ?",
                     [(sid, cid) for cid, sid in resolved])
    conn.commit()
    print(f"Persisted player_id (shortId) on {len(resolved)} conversations. "
          f"{len(targets) - len(resolved)} still unresolved (no email match).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
