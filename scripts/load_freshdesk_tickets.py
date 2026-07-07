#!/usr/bin/env python3
"""Load data/freshdesk_export.json into the local tickets DB as CLOSED tickets
on the 'freshdesk' channel -- so the unified feed has all three sources
(email / freshdesk / discord) as first-class tickets.

Each Freshdesk ticket -> one conversation (channel='freshdesk',
status='resolved', external_id=ticket_id) + a 'user' message (the player's
body/subject) and, when present, a 'human' message (the public resolution).

Idempotent (skips already-loaded ticket_ids). Reversible:
    DELETE FROM messages WHERE conversation_id IN
      (SELECT id FROM conversations WHERE channel='freshdesk');
    DELETE FROM conversations WHERE channel='freshdesk';
"""
import os, re, sys, json, sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "data", "supportbot.db"))
EXPORT = os.path.join(BASE, "data", "freshdesk_export.json")

# SID-first ingest resolution (SPEC-01 §3.3). Optional: the loader stays a plain
# sqlite3 script; if the app package (or pymongo/MONGO_URI) is unavailable the
# resolution simply yields NULLs and ingestion proceeds unchanged.
sys.path.insert(0, BASE)
try:
    from app import sid_lookup
except Exception:
    sid_lookup = None

EMAIL_ADDR_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def resolve_ticket_sid(t, body):
    """SPEC-01 §3.3: (player_id, sid_source) for one Freshdesk ticket. The
    'Player SID' custom field (once the admin adds it -- see SID_FIRST_INTAKE.md
    runbook) is the claimed SID; today's export has no requester email, so the
    email fallback scans the body for one; then a Mongo-validated body scan.
    (None, None) when nothing validates or Mongo is down -- never raises."""
    if sid_lookup is None:
        return None, None
    claimed = (t.get("player_sid")
               or (t.get("custom_fields") or {}).get("player_sid")
               or (t.get("custom_fields") or {}).get("cf_player_sid"))
    sender = t.get("requester_email") or t.get("email")
    if not sender:
        m = EMAIL_ADDR_RE.search(body or "")
        sender = m.group(0) if m else None
    return sid_lookup.resolve_from_ticket(claimed_sid=claimed, email=sender, body_text=body)


def ensure_sid_source_column(conn):
    """Loaders connect with plain sqlite3, so mirror app/db.py's idempotent
    ALTER here in case init_db() hasn't run since the SPEC-01 migration."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    if "sid_source" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN sid_source TEXT")
        conn.commit()


def main():
    dry = "--dry-run" in sys.argv
    tickets = json.load(open(EXPORT, encoding="utf-8"))
    conn = sqlite3.connect(DB_PATH)
    ensure_sid_source_column(conn)
    existing = {str(r[0]) for r in conn.execute(
        "SELECT external_id FROM conversations WHERE channel='freshdesk'").fetchall()}

    loaded = skipped = msgs = 0
    for t in tickets:
        tid = str(t.get("ticket_id"))
        if tid in existing:
            skipped += 1
            continue
        subject = (t.get("subject") or "").strip()
        body = (t.get("body") or "").strip() or subject
        resolution = (t.get("resolution") or "").strip()
        tags = t.get("tags") or []
        context = json.dumps({
            "source": "freshdesk", "category": "Freshdesk",
            "subject": subject, "tags": tags,
        }, ensure_ascii=False)
        if dry:
            loaded += 1
            msgs += 1 + (1 if resolution else 0)
            continue
        pid, sid_source = resolve_ticket_sid(t, f"{subject}\n{body}")
        cur = conn.execute(
            "INSERT INTO conversations (channel, origin, external_id, status, context, player_id, sid_source) "
            "VALUES ('freshdesk', 'backfill', ?, 'resolved', ?, ?, ?)", (tid, context, pid, sid_source))
        cid = cur.lastrowid
        conn.execute(
            "INSERT INTO messages (conversation_id, role, tier_used, text) VALUES (?,?,?,?)",
            (cid, "user", None, (subject + ("\n\n" + body if body and body != subject else "")).strip()))
        msgs += 1
        if resolution:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, tier_used, text) VALUES (?,?,?,?)",
                (cid, "human", None, resolution))
            msgs += 1
        loaded += 1
    if not dry:
        conn.commit()
    print(f"tickets       : {len(tickets)}")
    print(f"loaded        : {loaded}")
    print(f"skipped (dupe): {skipped}")
    print(f"messages      : {msgs}")
    if not dry:
        n = conn.execute("SELECT COUNT(*) FROM conversations WHERE channel='freshdesk'").fetchone()[0]
        print(f"conversations(channel=freshdesk) now: {n}")
    conn.close()


if __name__ == "__main__":
    main()
