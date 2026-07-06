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
import os, sys, json, sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "data", "supportbot.db"))
EXPORT = os.path.join(BASE, "data", "freshdesk_export.json")


def main():
    dry = "--dry-run" in sys.argv
    tickets = json.load(open(EXPORT, encoding="utf-8"))
    conn = sqlite3.connect(DB_PATH)
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
        cur = conn.execute(
            "INSERT INTO conversations (channel, origin, external_id, status, context) "
            "VALUES ('freshdesk', 'backfill', ?, 'resolved', ?)", (tid, context))
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
