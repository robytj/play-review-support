"""Cross-session player memory for the support chat ("like a real person would").

Two stores, both written by the chat engine and readable by the dashboard:

  - player_profile: ONE row per SID -- when we first/last saw them, how many
    sessions, what they asked about (topic counters), which recognition
    highlight and flavor lines they've already heard (so every visit says
    something NEW), and their last topic (for a "hope the purchases thing is
    sorted" style callback).
  - chat_intent_log: append-only log of what players actually ask for
    (intent + question per turn). This is the raw material for making the bot
    smarter with real usage: the dashboard can aggregate it, and recurring
    asks become KB articles / canned replies / new data intents.

Everything here is best-effort: a failed profile read/write logs a [warn] and
the chat carries on -- memory must never break the conversation.
"""
from __future__ import annotations

import json

from app import db


def _row(sid: str):
    return db.get_conn().execute(
        "SELECT * FROM player_profile WHERE sid = ?", (sid,)).fetchone()


def get(sid: str) -> dict | None:
    if not sid:
        return None
    try:
        r = _row(sid)
    except Exception as e:
        print(f"[warn] profile: read failed for {sid} ({e!r})")
        return None
    if not r:
        return None
    d = dict(r)
    for key, default in (("used_flavor_json", "[]"), ("topics_json", "{}")):
        try:
            d[key[:-5]] = json.loads(d.get(key) or default)
        except (ValueError, TypeError):
            d[key[:-5]] = json.loads(default)
    return d


def visit(sid: str, session_id: int) -> dict:
    """Record a verified login and return what recognition needs:
    {returning, visits, last_topic, last_highlight_metric, used_flavor}.
    First call for a SID creates the row (visits=1, returning=False)."""
    out = {"returning": False, "visits": 1, "last_topic": None,
           "last_highlight_metric": None, "used_flavor": []}
    if not sid:
        return out
    try:
        prev = get(sid)
        with db.tx() as c:
            if prev is None:
                c.execute(
                    "INSERT INTO player_profile (sid, session_count, last_session_id) "
                    "VALUES (?, 1, ?)", (sid, session_id))
            else:
                c.execute(
                    "UPDATE player_profile SET session_count = session_count + 1, "
                    "last_seen_at = datetime('now'), last_session_id = ? WHERE sid = ?",
                    (session_id, sid))
        if prev is not None:
            out.update({
                "returning": True,
                "visits": (prev.get("session_count") or 0) + 1,
                "last_topic": prev.get("last_topic"),
                "last_highlight_metric": prev.get("last_highlight_metric"),
                "used_flavor": prev.get("used_flavor") or [],
            })
    except Exception as e:
        print(f"[warn] profile: visit update failed for {sid} ({e!r})")
    return out


def set_highlight_metric(sid: str, metric: str):
    if not (sid and metric):
        return
    try:
        with db.tx() as c:
            c.execute("UPDATE player_profile SET last_highlight_metric = ? WHERE sid = ?",
                      (metric, sid))
    except Exception as e:
        print(f"[warn] profile: highlight update failed ({e!r})")


def add_used_flavor(sid: str, keys: list[str]):
    """Union new flavor keys into the profile so jokes/facts never repeat across
    sessions either (capped -- once everything's been heard, the slate resets)."""
    if not (sid and keys):
        return
    try:
        prof = get(sid)
        if prof is None:
            return
        merged = list(dict.fromkeys((prof.get("used_flavor") or []) + list(keys)))
        if len(merged) >= 22:      # heard nearly everything -> start fresh next visit
            merged = []
        with db.tx() as c:
            c.execute("UPDATE player_profile SET used_flavor_json = ? WHERE sid = ?",
                      (json.dumps(merged), sid))
    except Exception as e:
        print(f"[warn] profile: flavor update failed ({e!r})")


def log_intent(session_id: int, sid: str | None, intent: str, question: str = ""):
    """Append to chat_intent_log + roll the profile topic counters. The log is
    the 'learn from real usage' feed; keep intents coarse and stable."""
    try:
        with db.tx() as c:
            c.execute(
                "INSERT INTO chat_intent_log (session_id, sid, intent, question) "
                "VALUES (?, ?, ?, ?)",
                (session_id, sid, intent, (question or "")[:300]))
            if sid and intent not in ("smalltalk", "unclear", "crash"):
                row = c.execute("SELECT topics_json FROM player_profile WHERE sid = ?",
                                (sid,)).fetchone()
                if row:
                    try:
                        topics = json.loads(row["topics_json"] or "{}")
                    except (ValueError, TypeError):
                        topics = {}
                    topics[intent] = int(topics.get(intent, 0)) + 1
                    c.execute(
                        "UPDATE player_profile SET topics_json = ?, last_topic = ?, "
                        "last_topic_at = datetime('now') WHERE sid = ?",
                        (json.dumps(topics), intent, sid))
    except Exception as e:
        print(f"[warn] profile: intent log failed ({e!r})")


# Player-facing names for topic callbacks ("Last time we looked at your ...").
TOPIC_LABELS = {
    "purchases": "your purchases",
    "ban": "your account restriction",
    "account": "your account details",
    "matches": "your match stats",
    "bug": "a bug you reported",
    "bug_filed": "the bug you reported",
    "human_request": "getting you to the team",
}


def topic_label(intent: str | None) -> str | None:
    return TOPIC_LABELS.get(intent or "")
