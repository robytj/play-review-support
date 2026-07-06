"""SID resolution pass (PROJECT_HANDOFF §4A #3 / §4B) -- SCAFFOLD.

Resolves a player SID for each ticket that lacks one, by looking the player's email
(and/or Discord username) up in MongoDB, then persists the result onto
`conversations.player_id` so it's queried ONCE (not per-render, not per-row) and the
SID -> https://admin.brx.indusgame.com/player/<SID> link lights up in the grid.

Design (matches §4A #3's "must be efficient" requirement):
  1. Collect every distinct email/username across conversations missing a player_id.
  2. ONE bulk Mongo query ($in on the mapped field) -> in-memory {email: sid} map.
  3. One UPDATE per resolved conversation. Re-runnable; only fills blanks.

------------------------------------------------------------------------------
BEFORE THIS RUNS, THREE THINGS MUST BE CONFIRMED (see PROJECT_HANDOFF §5) and wired
into the env vars below. They were NOT available in the SupportBot repo -- the Mongo
credentials live in the play-review-responder project's settings/variables, and the
players collection + field mapping were never documented. Do NOT invent a SID format.

Required env (set them where you run this -- e.g. copy from play-review-responder):
    MONGO_URI                 mongodb+srv://.../ connection string
    MONGO_DB                  database name that holds players
    MONGO_PLAYERS_COLLECTION  collection name (e.g. "players")
    MONGO_EMAIL_FIELD         document field holding the player's email   (default: "email")
    MONGO_SID_FIELD           document field holding the player's SID      (default: "sid")
    MONGO_USERNAME_FIELD      (optional) field holding discord username, for Discord tickets

Usage:
    python -m scripts.resolve_sids --dry-run    # show what would resolve, no writes
    python -m scripts.resolve_sids              # resolve + persist
    python -m scripts.resolve_sids --limit 500  # cap the email set (metered runs)

Requires `pymongo` (add to requirements.txt when you go live with this).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

from app import db

MONGO_URI = os.environ.get("MONGO_URI", "")
MONGO_DB = os.environ.get("MONGO_DB", "")
MONGO_PLAYERS_COLLECTION = os.environ.get("MONGO_PLAYERS_COLLECTION", "players")
MONGO_EMAIL_FIELD = os.environ.get("MONGO_EMAIL_FIELD", "email")
MONGO_SID_FIELD = os.environ.get("MONGO_SID_FIELD", "sid")
MONGO_USERNAME_FIELD = os.environ.get("MONGO_USERNAME_FIELD", "")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _email_for(conv: dict) -> str | None:
    """Best-effort player email for a conversation: context.from (email/freshdesk),
    else the first email address found in the stored message text prefix."""
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
        d = dict(r)
        email = _email_for(d)
        if email:
            targets.append((d["id"], email))
    if limit:
        targets = targets[:limit]
    return targets


def _bulk_lookup(emails: list[str]) -> dict[str, str]:
    """ONE Mongo query. Returns {email_lower: sid}. Replace/verify the field names
    via the env vars above once the players collection schema is confirmed."""
    try:
        from pymongo import MongoClient
    except ImportError:
        print("! pymongo not installed. `pip install pymongo` then re-run.", file=sys.stderr)
        raise
    if not (MONGO_URI and MONGO_DB):
        raise SystemExit("! MONGO_URI / MONGO_DB unset -- see this file's header (PROJECT_HANDOFF §5).")
    client = MongoClient(MONGO_URI)
    coll = client[MONGO_DB][MONGO_PLAYERS_COLLECTION]
    out: dict[str, str] = {}
    # Case-insensitive match: emails are normalized to lower() on our side; if the
    # collection stores mixed-case, add a case-insensitive index or a $regex $in.
    cursor = coll.find(
        {MONGO_EMAIL_FIELD: {"$in": emails}},
        {MONGO_EMAIL_FIELD: 1, MONGO_SID_FIELD: 1},
    )
    for doc in cursor:
        email = str(doc.get(MONGO_EMAIL_FIELD, "")).lower()
        sid = doc.get(MONGO_SID_FIELD)
        if email and sid is not None:
            out[email] = str(sid)
    client.close()
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

    if args.dry_run:
        print("--dry-run: not querying Mongo. Sample emails:", emails[:10])
        return 0

    sid_map = _bulk_lookup(emails)
    print(f"Mongo returned {len(sid_map)} matches.")

    updates = [(sid_map[e], cid) for cid, e in targets if e in sid_map]
    conn.executemany("UPDATE conversations SET player_id = ? WHERE id = ?", updates)
    conn.commit()
    print(f"Persisted player_id on {len(updates)} conversations. "
          f"{len(targets) - len(updates)} still unresolved (no Mongo match).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
