"""Shadow chat agent state machine (SPEC-08 §2-§3).

GREET -> ASK_GAME -> ASK_SID -> CONFIRM_NAME -> RECOGNITION -> ISSUE_LOOP ->
(RESOLVED | ESCALATED | EXPIRED | ENDED)

Every scripted phase is a deterministic template; the only LLM calls are (a) ONE
Haiku call to phrase the recognition line (template fallback on failure), (b) the
Tier-2 RAG call inside router.suggest() -- reused pure, never forked -- and (c) the
Haiku vision SID extraction for uploaded screenshots. Shadow semantics: sessions
persist in chat_sessions/chat_messages (shadow=1) and NOTHING here touches
metrics_daily (no bump_metric call in this module), messages/answer_cache via the
live answer() path, or the public /chat endpoint. Tone corpus: chat rows are
admitted ONLY once they carry staff signal (approved / edited -- guard in
app/tone.py); raw unreviewed chat output never trains the voice.

Live human takeover: a staff member can flip a session's controller to 'human'
(taken_over_by/taken_over_at). While human-controlled, handle_message() only
stores the player message -- no pipeline, no bot reply, no budgets, no idle
expiry (for 30 min from takeover) -- and staff replies arrive via
agent_message() (role='agent', player-visible). release() hands back to the bot.

All Mongo reads go through app/player_context.py keyed to the session's ONE
resolved SID -- the cross-player guard below is a refusal backstop on top of that
structural guarantee, not the guarantee itself.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import date

from app import (config, db, embeddings, flavor, highlights, intents, llm,
                 player_context, router, scope_gate, ticketing, vectorstore)

# ------------------------------------------------------------------- constants --

TERMINAL_STATES = {"RESOLVED", "ESCALATED", "EXPIRED", "ENDED"}
IDLE_LIMIT_MINUTES = 10          # SPEC-08 §2: idle 10 min -> auto-close (lazy, server-side)
TAKEOVER_GRACE_MINUTES = 30      # human-controlled sessions skip idle expiry this long
LIVE_WINDOW_SECONDS = 120        # session list "live" flag: activity within this window
MAX_SID_TEXT_ATTEMPTS = 3
MAX_IMAGE_ATTEMPTS = 2

GAME_CHIPS = ["PrimeRush.gg (LatAm)", "PrimeRushGame (Global)", "Prime Rush MENA"]

# Voice note (John, 2026-07-09): these lines carry the founder voice — warm,
# high-energy, gamer-to-gamer, specific, never corporate, never robotic. Same
# rules as the Play-review replies: sincere first, playful second, and the
# guardrail SEMANTICS of every line are unchanged — only the delivery.
GREETING = ("Hey, welcome to PrimeRush support! You're talking to the PrimeRush "
            "bot — built by the same crew that builds the game. Which game are "
            "you playing?")
NON_LATAM_NOTE = ("Heads up — this test build supports PrimeRush.gg (LatAm), "
                  "but I'll do my best to help!")
ASK_SID_TEXT = ("Could you share your player SID? It's the 8-character code on your "
                "profile page (letters and numbers, e.g. AB12CD3E).")
SID_RETRY_TEXT = ("Hmm, I couldn't find an account with that SID. Double-check your "
                  "profile page and try again?")
SID_IMAGE_OFFER = ("Still no luck — if it's easier, upload a screenshot of your "
                   "profile or settings screen and I'll read the SID from it.")
DEGRADED_NOTE = ("I couldn't verify your account, so I'll answer from our help articles "
                 "only — no account-specific details. A human can verify you later "
                 "if needed.")
ISSUE_PROMPT = ("So — what can I do for you today? Purchases, account, matches, "
                "bugs… bring it on.")
CONFIRM_RETRY = "Just to be sure — is that your account? A quick Yes or No works."
NAME_NO_TEXT = "I couldn't find you — can you share your SID again?"
CROSS_SID_REFUSAL = ("I can only help with the account we verified in this chat — "
                     "I can't look up or discuss any other player's account.")
SMALLTALK_REPLY = ("Happy to chat! Support questions are where I really shine though "
                   "— what's going on in your game?")
OOS_DEFLECTION = ("That one's outside my arena — I'm all about PrimeRush support: "
                  "your account, purchases, matches, bugs. What's going on with "
                  "your game?")
ABUSE_DEFLECTION = ("I get it — when something's broken it's genuinely maddening. "
                    "I'm here to fix your PrimeRush issue, so let's keep it civil: "
                    "what's going on?")
STRIKES_GOODBYE = ("This doesn't seem to be about PrimeRush support, so I'll close this "
                   "chat here. Start a New Chat anytime you have a game issue — "
                   "I'll be right here!")
CSAT_QUESTION = "Did this solve it?"
RESOLVED_GOODBYE = ("Awesome — glad that sorted it! Now go make someone regret "
                    "dropping near you. See you in the arena \U0001F3AE")
ESCALATE_OFFER = ("Sorry that didn't do it — you deserve better than a shrug. "
                  "Want me to raise this with the team as a ticket?")
ESCALATE_DECLINED = "No problem — what else can I help you with?"
GOODBYE = "Thanks for stopping by — start a New Chat anytime!"
TIMEOUT_GOODBYE = ("Looks like you stepped away, so I'm closing this chat for now — "
                   "start a New Chat anytime!")
HUMAN_TAKEOVER_NOTE = "You're now chatting with a human from PrimeRush support."
BOT_RELEASE_NOTE = "The assistant is back with you."
RATING_QUESTION = "Before you go — how was this conversation?"
RATING_CHIPS = ["1", "2", "3", "4", "5"]
RATING_THANKS = "Thanks for the feedback — it really helps!"

# "4", "4 stars", "4 star", "4/5" -- anything else is NOT a rating (no nagging).
RATING_RE = re.compile(r"^\s*([1-5])\s*(?:/\s*5|\s*stars?)?\s*[.!]*\s*$", re.IGNORECASE)

# SID-shaped token (SPEC-08 §3.2). Scans the raw text (uppercase only) so ordinary
# lowercase words like "download" can't false-positive; players paste SIDs as-is.
SID_TOKEN_RE = re.compile(r"\b[A-Z0-9]{8}\b")

# NOTE: "order" was removed 2026-07-09 -- "in order to ..." was force-routing
# gameplay questions into the purchase summary. app/intents.py is now the main
# detector (typo-tolerant); this regex stays as the zero-cost fast path.
_PURCHASE_RE = re.compile(
    r"\b(purchase[sd]?|payment|paid|pay|bought|buy|charge[ds]?|charged|refund|"
    r"transaction|receipt|billing|invoice|gems?|coins?|diamonds?|top.?up)\b",
    re.IGNORECASE,
)
_BAN_RE = re.compile(
    r"\b(ban(ned)?|unban|suspend(ed)?|locked|appeal|restriction|muted|chat.?ban)\b",
    re.IGNORECASE,
)

# Recognition thanks (payer-aware, PLAYER_DATA_MAP §6). Deterministic templates
# appended to the recognition fallback; the Haiku phrasing call only ever sees the
# band word (facts["supporter"] = "high"|"yes"), never a number. HARD rules: no
# amounts, totals, currencies, or counts anywhere in these strings; never the
# words "payer"/"spender"/"VIP"; and no thanks at all for banned players -- next
# to a ban appeal it reads as mockery. payer_tier deliberately does NOT gate the
# thanks: a lapsed big supporter still deserves the gratitude.
_THANKS_HIGH = (
    "And a huge thank-you for being one of our biggest supporters — it genuinely "
    "keeps the game running.",
    "Huge thanks as well for being one of our biggest supporters — support like "
    "yours genuinely keeps the game running.",
    "And truly, thank you for being one of our strongest supporters — it means a "
    "lot to the whole team and keeps PrimeRush alive.",
)
_THANKS_SUPPORTER = (
    "Thanks so much for supporting the game, too — it really does help!",
    "And thank you for supporting the game — we appreciate you!",
)

_YES = {"yes", "y", "yep", "yeah", "yes please", "sure", "ok", "okay", "correct",
        "that's me", "thats me", "sim", "si", "sí"}
_NO = {"no", "n", "nope", "nah", "não", "nao", "not me", "wrong", "no thanks",
       "no thank you"}

_BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


# ------------------------------------------------------------------ primitives --

class SessionNotFound(Exception):
    pass


class SessionClosed(Exception):
    """Raised when a message hits an already-terminal session (API -> 409)."""
    def __init__(self, state: str):
        self.state = state
        super().__init__(state)


def _is_yes(text: str) -> bool:
    return (text or "").strip().lower().rstrip("!.") in _YES


def _is_no(text: str) -> bool:
    return (text or "").strip().lower().rstrip("!.") in _NO


def _get(session_id: int):
    row = db.get_conn().execute(
        "SELECT * FROM chat_sessions WHERE id = ?", (session_id,)
    ).fetchone()
    if not row:
        raise SessionNotFound(session_id)
    return row


def _meta(session) -> dict:
    try:
        return json.loads(session["meta_json"] or "{}")
    except (ValueError, TypeError):
        return {}


def _save_meta(session_id: int, meta: dict):
    with db.tx() as c:
        c.execute("UPDATE chat_sessions SET meta_json = ? WHERE id = ?",
                  (json.dumps(meta), session_id))


def _update(session_id: int, **fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db.tx() as c:
        c.execute(f"UPDATE chat_sessions SET {sets} WHERE id = ?",
                  (*fields.values(), session_id))


def _touch(session_id: int):
    _update(session_id, last_activity_at=_now())


def _now() -> str:
    row = db.get_conn().execute("SELECT datetime('now') AS t").fetchone()
    return row["t"]


def _clip(v, n: int = 48) -> str | None:
    """Blob guard for player-visible text built from data-source fields: one
    line, hard length cap. Raw provider payloads (receipts, cert chains, JSON)
    must never reach the transcript — summarize or drop (SPEC-08 §3, 'summaries
    only')."""
    if v is None:
        return None
    s = " ".join(str(v).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _add_msg(session_id: int, role: str, type_: str, content: str, meta: dict | None = None) -> dict:
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO chat_messages (session_id, role, type, content, meta_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, type_, content, json.dumps(meta or {})),
        )
        mid = cur.lastrowid
    row = db.get_conn().execute("SELECT * FROM chat_messages WHERE id = ?", (mid,)).fetchone()
    return _msg_dict(row)


def _msg_dict(row) -> dict:
    try:
        meta = json.loads(row["meta_json"] or "{}")
    except (ValueError, TypeError):
        meta = {}
    return {"id": row["id"], "role": row["role"], "type": row["type"],
            "content": row["content"], "meta": meta, "created_at": row["created_at"]}


def budget_dict(session) -> dict:
    return {
        "tier2_used": session["tier2_used"],
        "tier2_limit": config.CHAT_TIER2_PER_SESSION,
        "messages_used": session["msg_count"],
        "messages_limit": config.CHAT_MESSAGES_PER_SESSION,
    }


def _result(session_id: int, msgs: list[dict]) -> dict:
    session = _get(session_id)
    return {"session_id": session_id, "state": session["state"],
            "controller": session["controller"],   # frontend polls while 'human'
            "messages": msgs, "budget": budget_dict(session)}


def _bump_usage(field: str, delta: int = 1):
    today = date.today().isoformat()
    with db.tx() as c:
        c.execute(
            f"INSERT INTO chat_usage (day, {field}) VALUES (?, ?) "
            f"ON CONFLICT(day) DO UPDATE SET {field} = {field} + excluded.{field}",
            (today, delta),
        )


def _daily_tier2_calls() -> int:
    row = db.get_conn().execute(
        "SELECT tier2_calls FROM chat_usage WHERE day = ?", (date.today().isoformat(),)
    ).fetchone()
    return row["tier2_calls"] if row else 0


# ------------------------------------------------------------------ idle expiry --

def _human_hold(session) -> bool:
    """True while a human takeover suspends idle expiry: controller='human' AND
    the takeover is younger than TAKEOVER_GRACE_MINUTES (a forgotten takeover
    can't pin a session open forever)."""
    if session["controller"] != "human" or not session["taken_over_at"]:
        return False
    return bool(db.get_conn().execute(
        "SELECT 1 FROM chat_sessions WHERE id = ? AND taken_over_at >= datetime('now', ?)",
        (session["id"], f"-{TAKEOVER_GRACE_MINUTES} minutes"),
    ).fetchone())


def _expire_if_idle(session) -> tuple[object, list[dict]]:
    """Lazy timeout (SPEC-08 §2): if a live session has been idle > 10 min, close it
    now with a goodbye. Returns (fresh session row, goodbye messages added).
    Skipped while a human controls the session (within the takeover grace)."""
    if session["state"] in TERMINAL_STATES:
        return session, []
    if _human_hold(session):
        return session, []
    stale = db.get_conn().execute(
        "SELECT 1 FROM chat_sessions WHERE id = ? "
        "AND last_activity_at < datetime('now', ?)",
        (session["id"], f"-{IDLE_LIMIT_MINUTES} minutes"),
    ).fetchone()
    if not stale:
        return session, []
    _update(session["id"], state="EXPIRED", ended_at=_now(), end_reason="timeout")
    msg = _add_msg(session["id"], "bot", "text", TIMEOUT_GOODBYE)
    return _get(session["id"]), [msg]


def sweep_expired():
    """Bulk lazy expiry used by the session list (SPEC-08 §2 'list sweeps'). State
    flip only -- the per-session goodbye is added when that session is next opened.
    Human-controlled sessions within the takeover grace are exempt."""
    with db.tx() as c:
        c.execute(
            "UPDATE chat_sessions SET state='EXPIRED', ended_at=datetime('now'), "
            "end_reason='timeout' WHERE state NOT IN ('RESOLVED','ESCALATED','EXPIRED','ENDED') "
            "AND last_activity_at < datetime('now', ?) "
            "AND NOT (controller = 'human' AND taken_over_at >= datetime('now', ?))",
            (f"-{IDLE_LIMIT_MINUTES} minutes", f"-{TAKEOVER_GRACE_MINUTES} minutes"),
        )


# ------------------------------------------------------------------- lifecycle --

def create_session() -> dict:
    """New session; bot speaks first (GREET) and asks which game (ASK_GAME)."""
    with db.tx() as c:
        cur = c.execute("INSERT INTO chat_sessions (state) VALUES ('ASK_GAME')")
        session_id = cur.lastrowid
    _bump_usage("sessions")
    greeting = _add_msg(session_id, "bot", "chips", GREETING, {"chips": GAME_CHIPS})
    return _result(session_id, [greeting])


def end_session(session_id: int, reason: str = "manual") -> dict:
    session = _get(session_id)
    if session["state"] in TERMINAL_STATES:
        return _result(session_id, [])
    state = "EXPIRED" if reason == "timeout" else "ENDED"
    _update(session_id, state=state, ended_at=_now(), end_reason=reason)
    goodbye = _add_msg(session_id, "bot", "text",
                       TIMEOUT_GOODBYE if reason == "timeout" else GOODBYE)
    return _result(session_id, [goodbye])


def get_session(session_id: int) -> dict:
    session = _get(session_id)
    session, extra = _expire_if_idle(session)
    rows = db.get_conn().execute(
        "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id ASC", (session_id,)
    ).fetchall()
    s = dict(session)
    s.pop("meta_json", None)  # internal runtime flags, not part of the API surface
    s["budget"] = budget_dict(session)
    # live flag on the DETAIL response too -- the observer/takeover UI decides from
    # this fetch, not the list (bug fix: it was list-only, so takeover never offered).
    s["live"] = bool(db.get_conn().execute(
        "SELECT (state NOT IN ({t}) AND last_activity_at >= datetime('now', ?)) AS live "
        "FROM chat_sessions WHERE id = ?".format(
            t=",".join(f"'{x}'" for x in sorted(TERMINAL_STATES))),
        (f"-{LIVE_WINDOW_SECONDS} seconds", session_id),
    ).fetchone()["live"])
    return {"session": s, "messages": [_msg_dict(r) for r in rows]}


def list_sessions(limit: int = 50, offset: int = 0) -> dict:
    sweep_expired()
    conn = db.get_conn()
    terminal = ",".join(f"'{s}'" for s in sorted(TERMINAL_STATES))
    rows = conn.execute(
        f"SELECT id, created_at, last_activity_at, state, game_choice, sid, player_name, "
        f"msg_count, tier2_used, strikes, escalated_conversation_id, ended_at, end_reason, "
        f"controller, taken_over_by, rating, "
        f"(state NOT IN ({terminal}) AND last_activity_at >= datetime('now', ?)) AS live "
        f"FROM chat_sessions ORDER BY id DESC LIMIT ? OFFSET ?",
        (f"-{LIVE_WINDOW_SECONDS} seconds", limit, offset),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) AS n FROM chat_sessions").fetchone()["n"]
    # Sidebar issue summaries: latest substantive player message per session
    # (skips chip echoes / yes-no / SIDs; blob-clipped). One query for the page.
    ids = [r["id"] for r in rows]
    summaries: dict[int, str] = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        for m in conn.execute(
            f"SELECT session_id, content FROM chat_messages WHERE session_id IN ({marks}) "
            f"AND role = 'user' ORDER BY id ASC", ids,
        ).fetchall():
            text = (m["content"] or "").strip()
            low = text.lower().rstrip("!.")
            if (len(text) > 12 and low not in _YES and low not in _NO
                    and not SID_TOKEN_RE.fullmatch(text.upper())
                    and text not in GAME_CHIPS and not RATING_RE.match(text)):
                summaries[m["session_id"]] = _clip(text, 64)  # last one wins
    sessions = []
    for r in rows:
        d = dict(r)
        d["live"] = bool(d["live"])  # player plausibly still in the tab -> takeover target
        d["issue_summary"] = summaries.get(d["id"])
        sessions.append(d)
    return {"sessions": sessions, "total": total}


# ------------------------------------------------------------ live human takeover --

class NotHumanControlled(Exception):
    """Raised when an agent action needs controller='human' but the bot holds the
    session (API -> 409)."""


def _messages_tail(session_id: int, limit: int = 50) -> list[dict]:
    rows = db.get_conn().execute(
        "SELECT * FROM (SELECT * FROM chat_messages WHERE session_id = ? "
        "ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
        (session_id, limit),
    ).fetchall()
    return [_msg_dict(r) for r in rows]


def _session_public(session) -> dict:
    s = dict(session)
    s.pop("meta_json", None)
    s["budget"] = budget_dict(session)
    return s


def take_over(session_id: int, staff: str) -> dict:
    """Flip the session to human control. 409 on terminal sessions. Appends a
    player-visible system note and audits a 'takeover' ticket event when the
    session is linked to an escalated conversation."""
    session = _get(session_id)
    if session["state"] in TERMINAL_STATES:
        raise SessionClosed(session["state"])
    _update(session_id, controller="human", taken_over_by=staff,
            taken_over_at=_now(), last_activity_at=_now())
    _add_msg(session_id, "system", "system", HUMAN_TAKEOVER_NOTE,
             {"takeover": True, "staff": staff})
    if session["escalated_conversation_id"]:
        with db.tx() as c:
            ticketing.add_event(c, session["escalated_conversation_id"], staff,
                                "takeover", {"chat_session_id": session_id})
    session = _get(session_id)
    return {"session": _session_public(session), "messages": _messages_tail(session_id)}


def release(session_id: int, staff: str) -> dict:
    """Hand the session back to the bot. 409 unless currently human-controlled.
    taken_over_by/at are kept as a record of the last takeover."""
    session = _get(session_id)
    if session["controller"] != "human":
        raise NotHumanControlled("session is not human-controlled")
    _update(session_id, controller="bot", last_activity_at=_now())
    _add_msg(session_id, "system", "system", BOT_RELEASE_NOTE,
             {"release": True, "staff": staff})
    if session["escalated_conversation_id"]:
        with db.tx() as c:
            ticketing.add_event(c, session["escalated_conversation_id"], staff,
                                "release", {"chat_session_id": session_id})
    session = _get(session_id)
    return {"session": _session_public(session), "messages": _messages_tail(session_id)}


def agent_message(session_id: int, staff: str, text: str) -> dict:
    """A staff reply to the player during a takeover: player-visible role='agent'
    chat message. When the session is linked to an escalated conversation, the
    reply is ALSO written there as a staff reply (messages role='human', same
    role the backfill uses) so future tone learning sees how staff actually
    answered (SPEC-08 §5 refinement)."""
    session = _get(session_id)
    if session["state"] in TERMINAL_STATES:
        raise SessionClosed(session["state"])
    if session["controller"] != "human":
        raise NotHumanControlled("take the session over before replying")
    msg = _add_msg(session_id, "agent", "text", text, {"staff": staff})
    _touch(session_id)
    if session["escalated_conversation_id"]:
        with db.tx() as c:
            c.execute(
                "INSERT INTO messages (conversation_id, role, tier_used, text, author_name) "
                "VALUES (?, 'human', NULL, ?, ?)",
                (session["escalated_conversation_id"], text, staff),
            )
            c.execute("UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
                      (session["escalated_conversation_id"],))
            ticketing.stamp_first_human_response(c, session["escalated_conversation_id"])
    session = _get(session_id)
    return {"session_id": session_id, "state": session["state"],
            "controller": session["controller"], "messages": [msg]}


def get_messages(session_id: int, after_id: int = 0) -> dict:
    """Incremental transcript fetch -- both the observing agent and the player tab
    poll this during a takeover. Runs the lazy expiry (which respects the
    human-controlled hold) so a poll can surface the timeout goodbye."""
    session = _get(session_id)
    session, _extra = _expire_if_idle(session)
    rows = db.get_conn().execute(
        "SELECT * FROM chat_messages WHERE session_id = ? AND id > ? ORDER BY id ASC",
        (session_id, after_id),
    ).fetchall()
    return {"session_id": session_id, "state": session["state"],
            "controller": session["controller"],
            "messages": [_msg_dict(r) for r in rows]}


# ------------------------------------------------------------- message handling --

def handle_message(session_id: int, text: str) -> dict:
    session = _get(session_id)
    if session["state"] in TERMINAL_STATES:
        raise SessionClosed(session["state"])
    session, expiry_msgs = _expire_if_idle(session)
    if expiry_msgs:
        return _result(session_id, expiry_msgs)

    text = (text or "").strip()

    if session["controller"] == "human":
        # Live takeover: store the player message for the human agent and stop --
        # no pipeline, no bot reply, no budgets consumed (msg_count untouched).
        # The agent (and the player tab) pick it up via GET /messages polling.
        _add_msg(session_id, "user", "text", text)
        _touch(session_id)
        return _result(session_id, [])

    user_msg = _add_msg(session_id, "user", "text", text)
    _update(session_id, msg_count=session["msg_count"] + 1, last_activity_at=_now())
    session = _get(session_id)

    state = session["state"]
    if state == "ASK_GAME":
        out = _handle_game_choice(session, text)
    elif state == "ASK_SID":
        out = _handle_sid_text(session, text)
    elif state == "CONFIRM_NAME":
        out = _handle_confirm_name(session, text)
    elif state == "RATING":
        out = _handle_rating(session, text)
    else:  # ISSUE_LOOP
        out = _issue_loop(session, text)
    return _result(session_id, [user_msg] + out)


def handle_image(session_id: int, image_b64: str, media_type: str) -> dict:
    """SID extraction from a screenshot (SPEC-08 §2.2) -- only meaningful while
    identifying the account; max 2 images/session."""
    session = _get(session_id)
    if session["state"] in TERMINAL_STATES:
        raise SessionClosed(session["state"])
    session, expiry_msgs = _expire_if_idle(session)
    if expiry_msgs:
        return _result(session_id, expiry_msgs)
    if session["controller"] == "human":
        # takeover: record the upload for the agent, no vision call, no bot reply
        _add_msg(session_id, "user", "text", "[screenshot uploaded]", {"image": True})
        _touch(session_id)
        return _result(session_id, [])
    if session["state"] != "ASK_SID":
        raise ValueError("images are only accepted while identifying your account")

    user_msg = _add_msg(session_id, "user", "text", "[screenshot uploaded]", {"image": True})
    _update(session_id, msg_count=session["msg_count"] + 1, last_activity_at=_now())
    session = _get(session_id)

    if session["image_attempts"] >= MAX_IMAGE_ATTEMPTS:
        out = _enter_degraded(session)
        return _result(session_id, [user_msg] + out)

    _update(session_id, image_attempts=session["image_attempts"] + 1)
    session = _get(session_id)

    sid = None
    try:
        sid = llm.extract_sid_from_image(image_b64, media_type)
    except Exception as e:
        print(f"[warn] chat: vision SID extraction failed ({e!r})")

    ctx = player_context.get_player_context(sid) if sid else None
    if ctx:
        out = _found_player(session, ctx)
    elif session["image_attempts"] >= MAX_IMAGE_ATTEMPTS:
        out = [_add_msg(session_id, "bot", "text",
                        "I couldn't read a player ID from that one either.")]
        out += _enter_degraded(_get(session_id))
    else:
        out = [_add_msg(session_id, "bot", "text",
                        "I couldn't match a player ID from that screenshot — try a "
                        "clearer shot of your profile page, or type the SID if you can.")]
    return _result(session_id, [user_msg] + out)


# --------------------------------------------------------------- scripted phases --

def _handle_game_choice(session, text: str) -> list[dict]:
    # Choice is conversational only; stored on the session (SPEC-08 §2.1).
    _update(session["id"], game_choice=text[:60], state="ASK_SID")
    out = []
    if re.search(r"\b(global|mena)\b", text, re.IGNORECASE):
        out.append(_add_msg(session["id"], "bot", "text", NON_LATAM_NOTE))
    out.append(_add_msg(session["id"], "bot", "text", ASK_SID_TEXT))
    return out


def _extract_sid_token(text: str) -> str | None:
    # Players paste SIDs in any case during intake -- uppercase before matching
    # (unlike the ISSUE_LOOP guard, there's no false-positive risk here: whatever
    # matches is validated against Mongo before it's trusted).
    m = SID_TOKEN_RE.search((text or "").upper())
    return m.group(0) if m else None


def _handle_sid_text(session, text: str) -> list[dict]:
    token = _extract_sid_token(text)
    ctx = player_context.get_player_context(token) if token else None
    if ctx:
        return _found_player(session, ctx)

    attempts = session["sid_attempts"] + 1
    _update(session["id"], sid_attempts=attempts)
    session = _get(session["id"])
    if attempts < MAX_SID_TEXT_ATTEMPTS:
        return [_add_msg(session["id"], "bot", "text", SID_RETRY_TEXT)]
    if attempts == MAX_SID_TEXT_ATTEMPTS:
        return [_add_msg(session["id"], "bot", "text", SID_IMAGE_OFFER,
                         {"offer_image": True})]
    return _enter_degraded(session)


def _found_player(session, ctx) -> list[dict]:
    _update(session["id"], sid=ctx.sid, player_name=ctx.nickname,
            mongo_user_id=str(ctx.user_id) if ctx.user_id is not None else None,
            state="CONFIRM_NAME")
    card = _add_msg(session["id"], "bot", "context_card",
                    f"Found it — {ctx.nickname} ({ctx.sid})",
                    {"nickname": ctx.nickname, "sid": ctx.sid,
                     "email_masked": ctx.email_masked})
    confirm = _add_msg(session["id"], "bot", "chips",
                       f"You're {ctx.nickname}, right?", {"chips": ["Yes", "No"]})
    return [card, confirm]


def _handle_confirm_name(session, text: str) -> list[dict]:
    if _is_yes(text):
        return _recognition(session)
    if _is_no(text):
        # attempts counter deliberately continues (SPEC-08 §2.3)
        _update(session["id"], sid=None, player_name=None, mongo_user_id=None,
                state="ASK_SID")
        return [_add_msg(session["id"], "bot", "text", NAME_NO_TEXT)]
    return [_add_msg(session["id"], "bot", "chips", CONFIRM_RETRY,
                     {"chips": ["Yes", "No"]})]


def _pick_highlight(stats: dict | None) -> str | None:
    """Deterministic highlight priority (SPEC-08 §2.4):
    matchMvpCount > longestKillStreak > totalWins > totalTimeSpent."""
    s = stats or {}
    v = s.get("matchMvpCount") or 0
    if v > 0:
        return f"{v:,} match MVP awards"
    v = s.get("longestKillStreak") or 0
    if v > 0:
        return f"a longest kill streak of {v:,}"
    v = s.get("totalWins") or 0
    if v > 0:
        return f"{v:,} total wins"
    v = s.get("totalTimeSpent") or 0
    if v > 0:
        hours = int(v // 3600)
        return f"about {hours:,} hours in the arena" if hours >= 1 else None
    return None


def _supporter_thanks(ctx, session_id: int) -> str | None:
    """Deterministic thanks line for the recognition step, or None. Driven by
    supporter_band (HIGH/SUPPORTER/NONE); banned players (is_banned/chatBanned)
    never get one. Variant picked by session-id hash for variety."""
    if ctx is None or ctx.is_banned or ctx.chat_banned:
        return None
    band = getattr(ctx, "supporter_band", "NONE")
    if band == "HIGH":
        variants = _THANKS_HIGH
    elif band == "SUPPORTER":
        variants = _THANKS_SUPPORTER
    else:
        return None
    return variants[hash(session_id) % len(variants)]


def _recognition(session) -> list[dict]:
    ctx = player_context.get_player_context(session["sid"]) if session["sid"] else None
    _update(session["id"], state="ISSUE_LOOP")
    if ctx is None:
        # Mongo dropped between confirm and recognition -- skip the flourish.
        return [_add_msg(session["id"], "bot", "text",
                         f"Thanks, {session['player_name'] or 'there'}! {ISSUE_PROMPT}")]

    # Login-time highlight precompute (app/highlights.py): unique-player facts,
    # computed ONCE from the already-fetched context and parked on the session
    # meta. The best percentile-backed line upgrades the recognition highlight;
    # the rest drip out as "while I check that" flavor during the issue loop.
    top_line = None
    if getattr(config, "CHAT_HIGHLIGHTS_ENABLED", True):
        try:
            hl = highlights.compute_highlights(ctx)
        except Exception as e:
            print(f"[warn] chat: highlight precompute failed ({e!r})")
            hl = []
        if hl:
            meta = _meta(session)
            meta["highlights"] = [h["line"] for h in hl]
            meta["highlights_used"] = 0
            _save_meta(session["id"], meta)
            if hl[0]["top_pct"]:            # only percentile-backed claims may
                top_line = hl[0]["line"]    # upgrade the recognition line
                meta["highlights_used"] = 1
                _save_meta(session["id"], meta)

    thanks = _supporter_thanks(ctx, session["id"])
    facts = {
        "player_name": ctx.nickname,
        "playing_since": ctx.playing_since,
        "matches_played": ctx.matches_played,
        "highlight": top_line or _pick_highlight(ctx.stats),
    }
    if thanks:
        # Haiku only ever sees the band word -- no counts/amounts exist anywhere
        # in its prompt, so the model cannot leak figures (Package A hard rule).
        facts["supporter"] = "high" if ctx.supporter_band == "HIGH" else "yes"
    text = None
    try:
        text = llm.phrase_recognition(facts)  # the ONE scripted-phase Haiku call
    except Exception as e:
        print(f"[warn] chat: recognition phrasing failed, using template ({e!r})")
    if not text:
        bits = []
        if facts["playing_since"]:
            bits.append(f"thanks for playing with us since {facts['playing_since']}")
        if facts["matches_played"]:
            bits.append(f"{facts['matches_played']:,} matches in")
        line = (f"{ctx.nickname}, " + " — ".join(bits) + "!") if bits \
            else f"Great to see you, {ctx.nickname}!"
        if facts["highlight"]:
            line += f" And {facts['highlight']} — seriously impressive."
        if thanks:
            line += f" {thanks}"
        text = line
    rec = _add_msg(session["id"], "bot", "recognition", text, {"facts": facts})
    prompt = _add_msg(session["id"], "bot", "text", ISSUE_PROMPT)
    return [rec, prompt]


def _enter_degraded(session) -> list[dict]:
    meta = _meta(session)
    meta["degraded"] = True
    _save_meta(session["id"], meta)
    _update(session["id"], state="ISSUE_LOOP")
    note = _add_msg(session["id"], "system", "system", DEGRADED_NOTE, {"degraded": True})
    prompt = _add_msg(session["id"], "bot", "text", ISSUE_PROMPT)
    return [note, prompt]


# ------------------------------------------------------------------ star rating --

def _ask_rating(session_id: int, meta: dict, close_state: str, end_reason: str) -> list[dict]:
    """Enter RATING: one player-visible ask with 1-5 chips. Where the session
    closes afterwards (RESOLVED vs ESCALATED) is parked in meta until the answer."""
    meta["rating_close"] = close_state
    meta["rating_end_reason"] = end_reason
    _save_meta(session_id, meta)
    _update(session_id, state="RATING")
    return [_add_msg(session_id, "bot", "rating", RATING_QUESTION,
                     {"chips": list(RATING_CHIPS), "rating": True})]


def _parse_rating(text: str) -> int | None:
    m = RATING_RE.match(text or "")
    return int(m.group(1)) if m else None


def _handle_rating(session, text: str) -> list[dict]:
    """One shot: a parseable 1-5 ('4', '4 stars', '4/5') is stored + thanked;
    anything else closes without a rating -- never nag. Then the session closes
    to whatever the flow dictated (RESOLVED or ESCALATED)."""
    sid = session["id"]
    meta = _meta(session)
    close_state = meta.pop("rating_close", "RESOLVED")
    end_reason = meta.pop("rating_end_reason", "resolved")
    _save_meta(sid, meta)

    out = []
    rating = _parse_rating(text)
    if rating is not None:
        _update(sid, rating=rating)
        if session["escalated_conversation_id"]:
            # linked ticket keeps the signal in its audit trail too
            with db.tx() as c:
                ticketing.add_event(c, session["escalated_conversation_id"], "player",
                                    "rating", {"rating": rating, "chat_session_id": sid})
        out.append(_add_msg(sid, "bot", "text", RATING_THANKS))
    if close_state == "RESOLVED":
        out.append(_add_msg(sid, "bot", "text", RESOLVED_GOODBYE))
    _update(sid, state=close_state, ended_at=_now(), end_reason=end_reason)
    return out


# ------------------------------------------------------------ while-you-wait flavor --

FLAVOR_MAX_PER_SESSION = 4      # after this the bot just works quietly
FLAVOR_MIN_GAP_MSGS = 2         # never two flavored turns back to back


def _flavor_msgs(session, meta: dict) -> list[dict]:
    """One 'while I pull that up' line for a heavy turn (data intent / Tier-2):
    first the player's own precomputed highlights (the good stuff), then
    PrimeRush facts and jokes, alternating, no repeats in a session. Returns []
    whenever it shouldn't speak -- disabled, rate-limited, or out of material."""
    if not getattr(config, "CHAT_FLAVOR_ENABLED", True):
        return []
    sid = session["id"]
    if meta.get("flavor_shown", 0) >= FLAVOR_MAX_PER_SESSION:
        return []
    if session["msg_count"] - meta.get("flavor_last_msg", -99) < FLAVOR_MIN_GAP_MSGS:
        return []
    n = meta.get("flavor_shown", 0)
    hs, used = meta.get("highlights") or [], meta.get("highlights_used", 0)
    if used < len(hs):
        kind, line = "highlight", hs[used]
        meta["highlights_used"] = used + 1
    else:
        picked = flavor.pick(sid, meta.get("flavor_used") or [])
        if picked is None:
            return []
        kind, key, line = picked
        meta.setdefault("flavor_used", []).append(key)
    meta["flavor_shown"] = n + 1
    meta["flavor_last_msg"] = session["msg_count"]
    _save_meta(sid, meta)
    return [_add_msg(sid, "bot", "text", flavor.lead(kind, sid, n) + line,
                     {"flavor": kind})]


# ------------------------------------------------------------------- issue loop --

def _issue_loop(session, text: str) -> list[dict]:
    sid = session["id"]
    meta = _meta(session)

    # 1. message budget (SPEC-08 §3.6)
    if session["msg_count"] > config.CHAT_MESSAGES_PER_SESSION:
        return _escalate(session, question=text, reason="message budget reached",
                         end_reason="msg_budget")

    # 2. pending CSAT answer
    if meta.pop("csat_pending", None):
        last_q = meta.pop("last_question", "")
        _save_meta(sid, meta)
        if _is_yes(text):
            # solved -> ask for a star rating before closing (RESOLVED on answer)
            return _ask_rating(sid, meta, close_state="RESOLVED", end_reason="resolved")
        if _is_no(text):
            meta["escalate_offer"] = True
            meta["last_question"] = last_q
            _save_meta(sid, meta)
            return [_add_msg(sid, "bot", "chips", ESCALATE_OFFER, {"chips": ["Yes", "No"]})]
        # anything else = a new message; fall through and process it normally

    # 3. pending escalation offer
    if meta.pop("escalate_offer", None):
        last_q = meta.pop("last_question", "")
        _save_meta(sid, meta)
        if _is_yes(text):
            return _escalate(session, question=last_q or text,
                             reason="answer didn't resolve the issue")
        if _is_no(text):
            return [_add_msg(sid, "bot", "text", ESCALATE_DECLINED)]
        # fall through: treat as a new question

    # 4. cross-player SID guard (hard, SPEC-08 §3.2) -- raw-text scan, uppercase only
    foreign = [t for t in SID_TOKEN_RE.findall(text or "") if t != (session["sid"] or "")]
    if foreign:
        return [_add_msg(sid, "bot", "text", CROSS_SID_REFUSAL,
                         {"guard": "cross_sid"})]

    # 5. deterministic data intents BEFORE the gate (2026-07-09 regression fix:
    #    a verified player asking about their own purchases/ban is in scope by
    #    definition -- the gate must never eat these, however degenerate its
    #    centroids get). Typo-tolerant matching via app/intents.py, with the
    #    original regexes kept as the fast path. One thing still outranks them:
    #    an EXPLICIT human ask ("refund me, get me a human") always escalates.
    wants_purchases = bool(_PURCHASE_RE.search(text)) or intents.has_purchase_intent(text)
    wants_ban = bool(_BAN_RE.search(text)) or intents.has_ban_intent(text)
    if (wants_purchases or wants_ban) and scope_gate.is_human_request(text):
        return _escalate(session, question=text, reason="player asked for a human")
    ctx = None
    if session["sid"] and (wants_purchases or wants_ban):
        ctx = player_context.get_player_context(session["sid"])
    if wants_purchases and ctx and ctx.transactions is not None:
        return _flavor_msgs(session, meta) + _purchase_reply(session, meta, ctx)
    if wants_ban and ctx and (ctx.is_banned or ctx.chat_banned):
        return _ban_reply(session, ctx, text)

    # 6. scope gate (SPEC-08 §3.1)
    label, score = scope_gate.classify(text)
    if label in ("out_of_scope", "abuse"):
        strikes = session["strikes"] + 1
        _update(sid, strikes=strikes)
        if strikes >= config.SCOPE_GATE_STRIKE_LIMIT:
            _update(sid, state="ENDED", ended_at=_now(), end_reason="strikes")
            return [_add_msg(sid, "bot", "text", STRIKES_GOODBYE,
                             {"gate": label, "strikes": strikes})]
        deflection = ABUSE_DEFLECTION if label == "abuse" else OOS_DEFLECTION
        return [_add_msg(sid, "bot", "text", deflection,
                         {"gate": label, "strikes": strikes})]
    if label == "smalltalk":
        return [_add_msg(sid, "bot", "text", SMALLTALK_REPLY, {"gate": label})]
    if label == "human_request":
        return _escalate(session, question=text, reason="player asked for a human")

    # 7. clarify round in flight? (one round max)
    question = text
    if meta.get("clarify"):
        original = meta.get("clarify_question") or ""
        question = f"{original} — {text}" if original else text
        meta.pop("clarify", None)
        meta.pop("clarify_question", None)
        meta["clarify_used"] = True
        _save_meta(sid, meta)
        return _route(session, meta, question)

    if ctx is None and session["sid"]:
        ctx = player_context.get_player_context(session["sid"])

    # 8. gate-label backstops for the data intents (the gate can still route a
    #    purchase/ban phrasing the lexicons missed)
    if label == "Payments & Purchases" and ctx and ctx.transactions is not None:
        return _flavor_msgs(session, meta) + _purchase_reply(session, meta, ctx)
    if (ctx and (ctx.is_banned or ctx.chat_banned) and label == "Bans & Fair Play"):
        return _ban_reply(session, ctx, text)

    # 9. tiered router (SPEC-08 §3.4)
    return _route(session, meta, question)


def _purchase_reply(session, meta: dict, ctx) -> list[dict]:
    """Summaries only, never raw records (SPEC-08 §3.3)."""
    t = ctx.transactions
    if not t["real_money_count"] and not t.get("refunded_count"):
        text = ("I checked your account and I don't see any real-money purchases on it. "
                "If you were charged, it may be under a different account or store login "
                "— happy to flag it for the team.")
    else:
        # user.transaction records COMPLETED purchases only (failed payments are
        # not written to Mongo today; they arrive from a separate system in a
        # future version) — so frame the list as confirmed-delivered and route
        # "charged but missing" to escalation. Refunded purchases stay listed,
        # flagged, and excluded from the completed count (PLAYER_DATA_MAP §2).
        lines = [f"Here's what I can see on your account ({ctx.sid}) — "
                 f"these all completed successfully:",
                 f"• {t['real_money_count']} purchase(s) via "
                 f"{', '.join(t['payment_systems']) or 'unknown store'}"]
        if t.get("first_purchase"):
            lines.append(f"• First purchase {t['first_purchase']}, "
                         f"most recent {t['last_purchase']}")
        if t.get("refunded_count"):
            lines.append(f"• {t['refunded_count']} purchase(s) show as refunded — "
                         "refunds are issued by the store (Apple/Google/XSolla), "
                         "not in-game")
        recent = [r for r in t["recent"] if r.get("date")]
        if recent:
            lines.append("Most recent:")
            for r in recent:
                what = _clip(r.get("description")) or _clip(r.get("product")) or "purchase"
                if r.get("qty"):
                    what = f"{what} ×{r['qty']}"
                bits = [r["date"], what]
                if r.get("amount"):
                    bits.append(_clip(r.get("amount")))
                if r.get("payment_system"):
                    bits.append(_clip(r.get("payment_system"), 24))
                if r.get("status") == "refunded":
                    bits.append("refunded")
                lines.append("• " + " — ".join(str(b) for b in bits if b))
        lines.append("If you were charged for something that isn't listed here, it "
                     "didn't reach your account — tell me which purchase and I'll "
                     "flag it for the team to verify and restore.")
        text = "\n".join(lines)
    msg = _add_msg(session["id"], "bot", "text", text,
                   {"intent": "purchases", "summary": {k: v for k, v in t.items()
                                                       if k != "recent"}})
    return [msg] + _offer_csat(session, meta, "purchases")


def _pick_ban_response(conn, text: str, ctx) -> tuple[int | None, str]:
    """Reply drawn ONLY from the approved 'ban_response:' canned set (SPEC-08 §3.3,
    guardrail §8.3). Deterministic sub-intent match on the trigger suffix."""
    rows = conn.execute(
        "SELECT id, trigger_text, answer FROM canned "
        "WHERE trigger_text LIKE 'ban_response:%' ORDER BY id ASC"
    ).fetchall()
    if not rows:  # migration seeds these; belt-and-braces static fallback
        return None, ("I've logged your appeal for the Fair Play team to review — "
                      "they look at every case individually and will follow up.")
    t = (text or "").lower()

    def find(suffix):
        return next((r for r in rows if r["trigger_text"].endswith(suffix)), rows[0])

    if ctx.chat_banned and not ctx.is_banned:
        row = find("chat restriction")
    elif re.search(r"\b(wasn'?t me|not me|didn'?t|hacked|stolen|someone else|my brother|my friend)\b", t):
        row = find("says it wasn't them")
    elif re.search(r"\b(why|reason|what did i do)\b", t):
        row = find("why was I banned")
    else:
        row = find("appeal received")
    return row["id"], row["answer"]


def _ban_reply(session, ctx, text: str) -> list[dict]:
    conn = db.get_conn()
    canned_id, answer = _pick_ban_response(conn, text, ctx)
    # Staff-facing assessment card (the human tester evaluates genuineness; the
    # "player" never sees a promise). Facts only, all server-computed.
    card_meta = {
        "state": ctx.state,
        "chat_banned": ctx.chat_banned,
        "report_count_90d": ctx.report_count_90d,
        "banned_device_overlap": ctx.banned_device_overlap,
        "payer_tier": ctx.payer_tier,
        "sid": ctx.sid,
    }
    card = _add_msg(session["id"], "bot", "ban_card",
                    f"Ban assessment — state: {ctx.state or 'Active'}"
                    f"{' + chatBanned' if ctx.chat_banned else ''}, "
                    f"reports (90d): {ctx.report_count_90d if ctx.report_count_90d is not None else 'n/a'}, "
                    f"banned-device overlap: {'yes' if ctx.banned_device_overlap else 'no'}, "
                    f"payer tier: {ctx.payer_tier}",
                    card_meta)
    reply = _add_msg(session["id"], "bot", "text", answer,
                     {"intent": "ban", "canned_id": canned_id})
    return [card, reply]


def _offer_csat(session, meta: dict, last_question: str) -> list[dict]:
    meta["csat_pending"] = True
    meta["last_question"] = last_question
    _save_meta(session["id"], meta)
    return [_add_msg(session["id"], "bot", "csat", CSAT_QUESTION,
                     {"chips": ["Yes", "No"]})]


def _route(session, meta: dict, question: str) -> list[dict]:
    sid = session["id"]

    # Budgets first (SPEC-08 §3.6): once Tier-2 is exhausted (per-session or the
    # daily global cap) we may only serve the free tiers or escalate -- so don't
    # call suggest() (its cascade would happily spend a Haiku call).
    exhausted = (session["tier2_used"] >= config.CHAT_TIER2_PER_SESSION
                 or _daily_tier2_calls() >= config.CHAT_DAILY_TIER2_CALLS)
    if exhausted:
        q_vec = embeddings.embed(question)
        answer = router._tier0_canned(q_vec)
        if answer is None:
            cached = router._answer_cache_lookup(q_vec)
            answer = cached[1] if cached else None
        if answer is not None:
            msg = _add_msg(sid, "bot", "text", answer, {"tier": 0, "budget_exhausted": True})
            return [msg] + _offer_csat(session, meta, question)
        return _escalate(session, question=question, reason="tier-2 budget exhausted")

    res = router.suggest(question)  # pure -- no messages/metrics/cache side effects

    if res["tier"] in (0, 1, 2):
        pre = []
        if res["tier"] == 2:
            _update(sid, tier2_used=session["tier2_used"] + 1)
            _bump_usage("tier2_calls")
            # Tier-2 is the turn that actually took work -- the natural moment
            # for a highlight compliment or a PrimeRush fact/joke.
            pre = _flavor_msgs(session, meta)
        msg = _add_msg(sid, "bot", "text", res["text"],
                       {"tier": res["tier"], "n_chunks": len(res.get("chunks") or [])})
        return pre + [msg] + _offer_csat(session, meta, question)

    # Tier 3. Clarify-or-answer band (SPEC-08 §3.4): retrieval landed between
    # tau_clarify and tau_retrieval -> one round of chips from the top-2 titles.
    if not meta.get("clarify_used") and not router._is_sensitive(question):
        hits = vectorstore.search("kb_articles", embeddings.embed(question),
                                  top_k=2, where="status = 'published'")
        if hits and config.TAU_CLARIFY <= hits[0][1] < config.TAU_RETRIEVAL_CONFIDENCE:
            conn = db.get_conn()
            titles = []
            for row_id, _sim in hits:
                row = conn.execute("SELECT title FROM kb_articles WHERE id = ?",
                                   (row_id,)).fetchone()
                if row:
                    titles.append(row["title"])
            if titles:
                meta["clarify"] = titles
                meta["clarify_question"] = question
                _save_meta(sid, meta)
                return [_add_msg(sid, "bot", "chips",
                                 "I want to make sure I get this right — is it one "
                                 "of these?", {"chips": titles, "clarify": True})]

    return _escalate(session, question=question, reason="no confident KB answer (tier 3)")


# ------------------------------------------------------------------- escalation --

def _new_public_id(conn) -> str:
    while True:
        pid = "PR-" + "".join(secrets.choice(_BASE32) for _ in range(5))
        if not conn.execute("SELECT 1 FROM conversations WHERE public_id = ?",
                            (pid,)).fetchone():
            return pid


def _escalate(session, question: str, reason: str, end_reason: str = "escalated") -> list[dict]:
    """SPEC-08 §3.5: a real ticket -- conversations row (origin='live', public_id)
    + the chat transcript as messages + a tier-3 suggestions row with source='chat'
    carrying issue summary + SID + ban/purchase context. Mirrors the backfill
    scripts' conversation+suggestion shape exactly."""
    sid = session["id"]
    ctx = player_context.get_player_context(session["sid"]) if session["sid"] else None

    context = {
        "source": "chat",
        "chat_session_id": sid,
        "game_choice": session["game_choice"],
        "from": session["player_name"] or "unverified player",
        "reason": reason,
    }
    summary_bits = [f"SID: {session['sid'] or 'UNVERIFIED'}",
                    f"player: {session['player_name'] or 'unknown'}"]
    if ctx:
        context.update({
            "payer_tier": ctx.payer_tier,
            "account_state": ctx.state,
            "report_count_90d": ctx.report_count_90d,
            "banned_device_overlap": ctx.banned_device_overlap,
        })
        summary_bits.append(f"payer tier: {ctx.payer_tier}")
        if ctx.is_banned or ctx.chat_banned:
            summary_bits.append(
                f"ban state: {ctx.state}{' + chatBanned' if ctx.chat_banned else ''} | "
                f"reports 90d: {ctx.report_count_90d} | "
                f"banned-device overlap: {'yes' if ctx.banned_device_overlap else 'no'}")
        if ctx.transactions and ctx.transactions.get("real_money_count"):
            t = ctx.transactions
            summary_bits.append(
                f"purchases: {t['real_money_count']} real-money via "
                f"{', '.join(t['payment_systems'])}, last {t['last_purchase']}")

    transcript = db.get_conn().execute(
        "SELECT role, content FROM chat_messages WHERE session_id = ? "
        "AND role IN ('user','bot','agent') ORDER BY id ASC", (sid,)
    ).fetchall()

    full_question = (f"[shadow chat escalation — {reason}]\n"
                     + " | ".join(summary_bits) + f"\n\nIssue: {question}")

    with db.tx() as c:
        public_id = _new_public_id(c)
        cur = c.execute(
            "INSERT INTO conversations (channel, external_id, status, context, player_id, "
            "origin, public_id) VALUES ('chat', ?, 'escalated', ?, ?, 'live', ?)",
            (f"shadow-chat-{sid}", json.dumps(context, ensure_ascii=False),
             session["sid"], public_id),
        )
        conversation_id = cur.lastrowid
        role_map = {"user": "user", "agent": "human"}  # agent replies ARE staff replies
        for m in transcript:
            c.execute(
                "INSERT INTO messages (conversation_id, role, tier_used, text) "
                "VALUES (?, ?, NULL, ?)",
                (conversation_id, role_map.get(m["role"], "bot"), m["content"]),
            )
        c.execute(
            "INSERT INTO suggestions (conversation_id, source, question, suggested_answer, "
            "tier, retrieved_chunks, status) VALUES (?, 'chat', ?, ?, 3, '[]', 'pending')",
            (conversation_id, full_question, router.HOLDING_REPLY),
        )
        # SPEC-09 §1: chat escalations are first-class tickets -- write the
        # created (priority + SLA due_at) and escalated audit events with the
        # chat context. Paying customers auto-P1 (verified payer_tier != NONE);
        # else priority inherits P2 when verified purchase/ban context is
        # present, else the keyword/default rules (§3).
        payer_tier = ctx.payer_tier if ctx else None
        priority = ticketing.default_priority(
            question,
            has_purchase_context=bool(ctx and ctx.transactions
                                      and ctx.transactions.get("real_money_count")),
            has_ban_context=bool(ctx and (ctx.is_banned or ctx.chat_banned)),
            payer_tier=payer_tier,
        )
        created_detail = {"source": "chat", "chat_session_id": sid,
                          "public_id": public_id}
        if ticketing.is_payer(payer_tier):
            created_detail["reason"] = ticketing.PAYER_AUTO_P1_REASON
            created_detail["payer_tier"] = payer_tier
        ticketing.stamp_created(c, conversation_id, actor="bot", priority=priority,
                                detail=created_detail)
        ticketing.add_event(c, conversation_id, "bot", "escalated",
                            {"reason": reason, "chat_session_id": sid,
                             "sid": session["sid"], "public_id": public_id,
                             "summary": " | ".join(summary_bits)})
    _bump_usage("escalations")
    _update(sid, escalated_conversation_id=conversation_id)

    card = _add_msg(sid, "bot", "escalation_card",
                    f"I've raised this with the team — ticket {public_id}. A human "
                    "will pick it up from here; thanks for your patience!",
                    {"conversation_id": conversation_id, "public_id": public_id,
                     "reason": reason})
    # Star rating right after the escalation card; the session closes to
    # ESCALATED (with the original end_reason) once the player answers/passes.
    return [card] + _ask_rating(sid, _meta(_get(sid)), close_state="ESCALATED",
                                end_reason=end_reason)
