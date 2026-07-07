#!/usr/bin/env python3
"""Load the classified support-email threads (support_emails/*.txt) into the
local tickets DB as CLOSED tickets on the 'email' channel.

Each email thread -> one row in `conversations` (channel='email',
status='resolved', external_id=<gmail thread id>) plus one row per message in
`messages` (role='user' for the player, role='human' for @supergaming.com
replies). This is the base training/reference corpus for the unified support
agent -- it feeds KB building and the autoresponder's prior-response learning.

Idempotent: a thread already loaded (channel='email' + same external_id) is
skipped, so re-runs don't duplicate. Reversible:
    DELETE FROM messages WHERE conversation_id IN
      (SELECT id FROM conversations WHERE channel='email');
    DELETE FROM conversations WHERE channel='email';

Run:  python scripts/load_email_tickets.py            # load
      python scripts/load_email_tickets.py --dry-run  # parse + count only
"""
import os, re, sys, json, glob, sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TXT_DIR = os.path.join(BASE, "support_emails")
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE, "data", "supportbot.db"))

# SID-first ingest resolution (SPEC-01 §3.2). Optional: the loader stays a plain
# sqlite3 script; if the app package (or pymongo/MONGO_URI) is unavailable the
# resolution simply yields NULLs and ingestion proceeds unchanged.
sys.path.insert(0, BASE)
try:
    from app import sid_lookup
except Exception:
    sid_lookup = None

EMAIL_ADDR_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

MSG_RE = re.compile(r"^From:\s*(.*?)\s{2}Date:\s*(.*)$", re.MULTILINE)
HDR_RE = {
    "subject": re.compile(r"^Subject:\s*(.*)$", re.MULTILINE),
    "participants": re.compile(r"^Participants:\s*(.*)$", re.MULTILINE),
    "thread_id": re.compile(r"^Thread ID:\s*(.*)$", re.MULTILINE),
}
SEP = "=" * 60
# Best-effort in-game player id: 8 chars, upper letters+digits, appears near "id"
PID_RE = re.compile(r"\b(?:id|i\.?d|player\s*id)\D{0,6}([A-Z0-9]{7,10})\b", re.IGNORECASE)


def parse_txt(path):
    raw = open(path, encoding="utf-8", errors="ignore").read()
    head, _, body = raw.partition(SEP)
    sm = HDR_RE["subject"].search(head)
    subject = sm.group(1).strip() if sm else ""
    tid = HDR_RE["thread_id"].search(head).group(1).strip() if HDR_RE["thread_id"].search(head) else os.path.splitext(os.path.basename(path))[0]
    parts = HDR_RE["participants"].search(head)
    participants = parts.group(1).strip() if parts else ""
    # Split body into messages by the "From: .. Date: .." markers
    msgs = []
    matches = list(MSG_RE.finditer(body))
    for i, m in enumerate(matches):
        sender = m.group(1).strip()
        mdate = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        text = body[start:end].strip()
        msgs.append({"from": sender, "date": mdate, "text": text})
    return {"thread_id": tid, "subject": subject, "participants": participants, "messages": msgs}


def extract_player_id(msgs):
    for m in msgs:
        if "supergaming.com" in (m["from"] or ""):
            continue
        hit = PID_RE.search(m["text"] or "")
        if hit:
            cand = hit.group(1)
            if any(ch.isdigit() for ch in cand) and cand.upper() == cand:
                return cand
    return None


def resolve_ticket_sid(msgs, player_from):
    """SPEC-01 §3.2: (player_id, sid_source) for one email thread -- claimed SID
    (the id-labelled token, Mongo-validated) beats a sender-email match, beats a
    Mongo-validated body scan. (None, None) when nothing validates or Mongo is
    down -- best-effort, never raises, never blocks ingestion."""
    if sid_lookup is None:
        return None, None
    claimed = extract_player_id(msgs)
    m = EMAIL_ADDR_RE.search(player_from or "")   # "Name <addr>" or plain address
    body = "\n".join((msg["text"] or "") for msg in msgs
                     if "supergaming.com" not in (msg["from"] or ""))
    return sid_lookup.resolve_from_ticket(
        claimed_sid=claimed, email=(m.group(0) if m else None), body_text=body)


def ensure_sid_source_column(conn):
    """Loaders connect with plain sqlite3, so mirror app/db.py's idempotent
    ALTER here in case init_db() hasn't run since the SPEC-01 migration."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    if "sid_source" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN sid_source TEXT")
        conn.commit()


def main():
    dry = "--dry-run" in sys.argv
    files = sorted(glob.glob(os.path.join(TXT_DIR, "*.txt")))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_sid_source_column(conn)
    existing = {r[0] for r in conn.execute(
        "SELECT external_id FROM conversations WHERE channel='email'").fetchall()}

    loaded = skipped = msg_count = empty = 0
    for path in files:
        t = parse_txt(path)
        tid = t["thread_id"]
        if tid in existing:
            skipped += 1
            continue
        if not t["messages"]:
            empty += 1
            continue
        first_date = t["messages"][0]["date"] or "now"
        last_date = t["messages"][-1]["date"] or first_date
        # who is the player (first non-supergaming sender)
        player = next((m["from"] for m in t["messages"] if "supergaming.com" not in (m["from"] or "")), t["messages"][0]["from"])
        context = json.dumps({
            "source": "email", "category": "Email",
            "subject": t["subject"], "from": player,
            "participants": t["participants"],
            "gmail_thread": f"https://mail.google.com/mail/u/0/#all/{tid}",
        }, ensure_ascii=False)
        pid, sid_source = resolve_ticket_sid(t["messages"], player)
        if dry:
            loaded += 1
            msg_count += len(t["messages"])
            continue
        cur = conn.execute(
            "INSERT INTO conversations (channel, origin, external_id, status, context, player_id, sid_source, created_at, updated_at) "
            "VALUES ('email', 'backfill', ?, 'resolved', ?, ?, ?, ?, ?)",
            (tid, context, pid, sid_source, first_date, last_date),
        )
        cid = cur.lastrowid
        for m in t["messages"]:
            role = "human" if "supergaming.com" in (m["from"] or "") else "user"
            conn.execute(
                "INSERT INTO messages (conversation_id, role, tier_used, text, created_at) VALUES (?,?,?,?,?)",
                (cid, role, None, f"[{m['from']}] {m['text']}".strip(), m["date"] or first_date),
            )
            msg_count += 1
        loaded += 1
    if not dry:
        conn.commit()
    print(f"files scanned : {len(files)}")
    print(f"loaded        : {loaded}")
    print(f"skipped (dupe): {skipped}")
    print(f"empty (no msg): {empty}")
    print(f"messages      : {msg_count}")
    if dry:
        print("\nDRY RUN — nothing written.")
    else:
        n = conn.execute("SELECT COUNT(*) FROM conversations WHERE channel='email'").fetchone()[0]
        print(f"\nconversations(channel=email) now: {n}")
    conn.close()


if __name__ == "__main__":
    main()
