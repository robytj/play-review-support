"""Dashboard API -- backs the 'Support' and 'Support Settings' tabs that live in
play_reviewer.py (the existing PrimeRush admin app), not here. This service has no
UI of its own for Phase 3 by design: play_reviewer.py already has Google-OAuth
login, an admin/user role system, and a dashboard shell we want to reuse rather
than duplicate. play_reviewer.py's Flask backend calls these endpoints
server-to-server with a bearer key, then renders the result -- the browser never
talks to this service directly, and never sees SUPPORT_SERVICE_API_KEY.

Auth mirrors play-review-responder's own require_service_key() pattern exactly
(Authorization: Bearer <key>, constant-time compare, 503 if unconfigured).
"""
import json
import secrets as _secrets
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Header

from app import db, embeddings, vectorstore, config, llm, tone, discord_send, outreach, ticketing

router = APIRouter(prefix="/api/dashboard")


def require_service_key(authorization: str = Header(default="")):
    if not config.SUPPORT_SERVICE_API_KEY:
        raise HTTPException(503, "dashboard API not configured (SUPPORT_SERVICE_API_KEY unset)")
    provided = authorization[7:] if authorization.startswith("Bearer ") else authorization
    if not provided or not _secrets.compare_digest(provided, config.SUPPORT_SERVICE_API_KEY):
        raise HTTPException(401, "invalid or missing API key")
    return True


# ------------------------------------------------------------------ feed / queue --

def _discord_url(channel: str, external_id: str) -> str | None:
    """Deep link back to the live Discord ticket channel/thread, e.g.
    https://discord.com/channels/<guild>/<channel-or-thread-id> -- works for
    both because Discord resolves thread ids the same way. None if this isn't
    a Discord conversation or the guild id isn't configured."""
    if channel != "discord" or not external_id or not config.DISCORD_GUILD_ID:
        return None
    return f"https://discord.com/channels/{config.DISCORD_GUILD_ID}/{external_id}"


def _enrich(row: dict) -> dict:
    row["discord_url"] = _discord_url(row.get("channel"), row.get("external_id"))
    return row


@router.get("/feed", dependencies=[Depends(require_service_key)])
def feed(limit: int = 50, channel: str | None = None, status: str | None = None):
    """Unified ticket feed across all sources. Pass `channel` (email | freshdesk |
    discord | web) to render a single source section, or omit it for everything.
    `status` optionally narrows to e.g. resolved/open/escalated."""
    conn = db.get_conn()
    where, params = [], []
    if channel:
        where.append("c.channel = ?")
        params.append(channel)
    if status:
        where.append("c.status = ?")
        params.append(status)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT c.id, c.channel, c.external_id, c.status, c.context, c.player_id, c.updated_at,
               (SELECT text FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_text,
               (SELECT tier_used FROM messages WHERE conversation_id = c.id AND role='bot' ORDER BY id DESC LIMIT 1) AS last_tier
        FROM conversations c
        {where_sql}
        ORDER BY c.updated_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_enrich(dict(r)) for r in rows]


@router.get("/channels", dependencies=[Depends(require_service_key)])
def channels():
    """Per-source ticket counts -- powers the unified feed's section headers
    (Email / Freshdesk / Discord / Web), each with total + open/resolved split."""
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT channel,
               COUNT(*) AS total,
               SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) AS resolved,
               SUM(CASE WHEN status!='resolved' THEN 1 ELSE 0 END) AS open,
               MAX(updated_at) AS latest
        FROM conversations
        GROUP BY channel
        ORDER BY total DESC
        """
    ).fetchall()
    sections = [dict(r) for r in rows]
    return {"sections": sections, "total": sum(s["total"] for s in sections)}


@router.get("/conversations/{conversation_id}", dependencies=[Depends(require_service_key)])
def conversation_detail(conversation_id: int):
    conn = db.get_conn()
    convo = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not convo:
        raise HTTPException(404, "conversation not found")
    messages = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,)
    ).fetchall()
    return {"conversation": _enrich(dict(convo)), "messages": [dict(m) for m in messages]}


def _staff_actor(x_staff_email: str = Header(default="", alias="X-Staff-Email")) -> str:
    """SPEC-09 §6 staff identity: the responder proxy forwards the logged-in
    user's Google email as X-Staff-Email on every ticketing call; SupportBot
    records it as the audit-log actor. Absent header -> 'system'."""
    return (x_staff_email or "").strip().lower() or "system"


@router.post("/conversations/{conversation_id}/resolve", dependencies=[Depends(require_service_key)])
def resolve_conversation(conversation_id: int, actor: str = Depends(_staff_actor)):
    with db.tx() as conn:
        row = conn.execute("SELECT status FROM conversations WHERE id = ?",
                           (conversation_id,)).fetchone()
        cur = conn.execute(
            "UPDATE conversations SET status='resolved', updated_at=datetime('now') WHERE id = ?",
            (conversation_id,),
        )
        if cur.rowcount and row and row["status"] != "resolved":
            ticketing.add_event(conn, conversation_id, actor, "status",
                                {"from": row["status"], "to": "resolved"})
    return {"ok": True}


@router.get("/queue", dependencies=[Depends(require_service_key)])
def queue():
    """Tier-3 escalations still open, plus staff-paused threads -- what a human
    needs to look at, per spec section 6.1's 'Escalation queue' panel."""
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT DISTINCT c.id, c.channel, c.external_id, c.status, c.player_id, c.updated_at,
               (SELECT text FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_text
        FROM conversations c
        WHERE c.status = 'paused'
           OR (c.status != 'resolved' AND EXISTS (
                 SELECT 1 FROM messages m WHERE m.conversation_id = c.id AND m.tier_used = 3
           ))
        ORDER BY c.updated_at DESC
        """
    ).fetchall()
    return [_enrich(dict(r)) for r in rows]


# ---------------------------------------------------------------- ticketing (SPEC-09) --
# Ticket Review as a full ticketing system: priorities, assignees, SLA, status
# workflow, audit events, recommendations, (inert) outreach. Storage lives on
# the conversations table + ticket_events; helpers in app/ticketing.py.

_TICKET_COLS = """
    c.id, c.public_id, c.channel, c.external_id, c.origin, c.status, c.context,
    c.player_id, c.sid_source, c.created_at, c.updated_at,
    COALESCE(c.priority, 'P3') AS priority, c.assignee, c.due_at,
    c.first_human_response_at, c.closed_at
"""


def _ticket_row(d: dict) -> dict:
    """Shared per-row enrichment: display status (legacy escalated/paused map),
    overdue/due seconds from the SQL fragments, deep links."""
    d["ticket_status"] = ticketing.display_status(d.get("status"))
    d["overdue"] = bool(d.get("overdue"))
    d["admin_url"] = _admin_url(d.get("player_id"))
    d["discord_url"] = _discord_url(d.get("channel"), d.get("external_id"))
    return d


@router.get("/tickets", dependencies=[Depends(require_service_key)])
def list_tickets(status: str | None = None, priority: str | None = None,
                 assignee: str | None = None, channel: str | None = None,
                 overdue: bool | None = None, q: str | None = None,
                 limit: int = 100, offset: int = 0):
    """SPEC-09 §6 rich ticket list, queue-ordered (overdue first, then priority,
    then due_at) with per-row SLA state. Runs the lazy sla_breach sweep first.
    `status` filters on the DISPLAY workflow value (open matches legacy
    'escalated' rows, waiting_player matches legacy 'paused')."""
    with db.tx() as c:
        ticketing.sweep_sla_breaches(c)
    conn = db.get_conn()
    where, params = [], []
    if status:
        raws = [status] + [k for k, v in ticketing.LEGACY_STATUS_MAP.items() if v == status]
        where.append(f"c.status IN ({','.join('?' * len(raws))})")
        params.extend(raws)
    if priority:
        if priority not in ticketing.PRIORITIES:
            raise HTTPException(400, f"priority must be one of {list(ticketing.PRIORITIES)}")
        where.append("COALESCE(c.priority, 'P3') = ?")
        params.append(priority)
    if assignee is not None:
        if assignee in ("", "unassigned"):
            where.append("(c.assignee IS NULL OR c.assignee = '')")
        else:
            where.append("c.assignee = ?")
            params.append(assignee)
    if channel:
        where.append("c.channel = ?")
        params.append(channel)
    if overdue:
        where.append(ticketing.OVERDUE_SQL)
    if q:
        like = f"%{q}%"
        where.append("(c.public_id LIKE ? OR c.player_id LIKE ? OR c.assignee LIKE ? OR EXISTS "
                     "(SELECT 1 FROM suggestions s WHERE s.conversation_id = c.id AND s.question LIKE ?))")
        params.extend([like, like, like, like])
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    total = conn.execute(
        f"SELECT COUNT(*) AS n FROM conversations c {where_sql}", params
    ).fetchone()["n"]
    rows = conn.execute(
        f"""
        SELECT {_TICKET_COLS},
               {ticketing.OVERDUE_SQL} AS overdue,
               {ticketing.DUE_IN_SQL} AS due_in_seconds,
               (SELECT text FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_text,
               (SELECT s.question FROM suggestions s WHERE s.conversation_id = c.id
                ORDER BY s.id DESC LIMIT 1) AS question,
               (SELECT s.id FROM suggestions s WHERE s.conversation_id = c.id
                ORDER BY s.id DESC LIMIT 1) AS suggestion_id
        FROM conversations c
        {where_sql}
        {ticketing.QUEUE_ORDER_SQL}
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    return {"tickets": [_ticket_row(dict(r)) for r in rows], "total": total,
            "limit": limit, "offset": offset}


@router.patch("/conversations/{conversation_id}", dependencies=[Depends(require_service_key)])
def patch_conversation(conversation_id: int, payload: dict, actor: str = Depends(_staff_actor)):
    """SPEC-09 §6: {status?, priority?, assignee?}. Transitions are unrestricted
    (small team) except `closed`, which is staff-only; every change is logged
    with actor. Priority changes recompute due_at only while no first human
    response has been recorded."""
    allowed = {"status", "priority", "assignee"}
    unknown = set(payload) - allowed
    if unknown:
        raise HTTPException(400, f"unknown fields {sorted(unknown)}; allowed: {sorted(allowed)}")
    if not payload:
        raise HTTPException(400, "nothing to update (status/priority/assignee)")
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not row:
        raise HTTPException(404, "conversation not found")
    old = dict(row)

    if "status" in payload:
        new_status = payload["status"]
        if new_status not in ticketing.STATUSES:
            raise HTTPException(400, f"status must be one of {list(ticketing.STATUSES)}")
        if new_status == "closed" and actor in ("system", "bot"):
            raise HTTPException(403, "closed is staff-only (X-Staff-Email required)")
    if "priority" in payload and payload["priority"] not in ticketing.PRIORITIES:
        raise HTTPException(400, f"priority must be one of {list(ticketing.PRIORITIES)}")

    with db.tx() as c:
        if "status" in payload and payload["status"] != old["status"]:
            new_status = payload["status"]
            c.execute("UPDATE conversations SET status = ? WHERE id = ?",
                      (new_status, conversation_id))
            if new_status == "closed":
                c.execute("UPDATE conversations SET closed_at = datetime('now') WHERE id = ?",
                          (conversation_id,))
            elif old["closed_at"]:
                # reopened -- a stale closed_at would misreport the ticket
                c.execute("UPDATE conversations SET closed_at = NULL WHERE id = ?",
                          (conversation_id,))
            ticketing.add_event(c, conversation_id, actor, "status",
                                {"from": old["status"], "to": new_status})
        if "priority" in payload and payload["priority"] != (old["priority"] or "P3"):
            new_priority = payload["priority"]
            c.execute("UPDATE conversations SET priority = ? WHERE id = ?",
                      (new_priority, conversation_id))
            detail = {"from": old["priority"] or "P3", "to": new_priority}
            if not old["first_human_response_at"]:
                # SPEC-09 §3: due_at recomputed on priority change only pre-first-response
                ticketing.recompute_due_at(c, conversation_id, new_priority)
                detail["due_at_recomputed"] = True
            ticketing.add_event(c, conversation_id, actor, "priority", detail)
        if "assignee" in payload and (payload["assignee"] or None) != (old["assignee"] or None):
            new_assignee = (payload["assignee"] or "").strip().lower() or None
            c.execute("UPDATE conversations SET assignee = ? WHERE id = ?",
                      (new_assignee, conversation_id))
            ticketing.add_event(c, conversation_id, actor, "assignee",
                                {"from": old["assignee"], "to": new_assignee})
        c.execute("UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
                  (conversation_id,))

    fresh = db.get_conn().execute(
        f"SELECT {_TICKET_COLS}, {ticketing.OVERDUE_SQL} AS overdue, "
        f"{ticketing.DUE_IN_SQL} AS due_in_seconds FROM conversations c WHERE c.id = ?",
        (conversation_id,),
    ).fetchone()
    return {"ok": True, "ticket": _ticket_row(dict(fresh))}


@router.post("/conversations/{conversation_id}/notes", dependencies=[Depends(require_service_key)])
def add_note(conversation_id: int, payload: dict, actor: str = Depends(_staff_actor)):
    """Notes ARE events (SPEC-09 §1): one ticket_events row with event='note',
    text in detail_json. Optional {notify: true} marks it as a player-visible
    response and stamps first_human_response_at (first time only)."""
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    notify = bool(payload.get("notify"))
    conn = db.get_conn()
    if not conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone():
        raise HTTPException(404, "conversation not found")
    with db.tx() as c:
        ticketing.add_event(c, conversation_id, actor, "note",
                            {"text": text, "notify": notify})
        if notify:
            ticketing.stamp_first_human_response(c, conversation_id)
        c.execute("UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
                  (conversation_id,))
    return {"ok": True}


@router.get("/conversations/{conversation_id}/events", dependencies=[Depends(require_service_key)])
def list_events(conversation_id: int):
    """The audit timeline (SPEC-09 §6), oldest first. detail_json is parsed for
    the client; no events are backfilled for pre-SPEC-09 rows."""
    conn = db.get_conn()
    if not conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone():
        raise HTTPException(404, "conversation not found")
    rows = conn.execute(
        "SELECT id, actor, event, detail_json, created_at FROM ticket_events "
        "WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,)
    ).fetchall()
    events = []
    for r in rows:
        d = dict(r)
        try:
            d["detail"] = json.loads(d.pop("detail_json") or "{}")
        except (ValueError, TypeError):
            d["detail"] = {}
        events.append(d)
    return {"conversation_id": conversation_id, "events": events}


@router.get("/conversations/{conversation_id}/recommendations", dependencies=[Depends(require_service_key)])
def recommendations(conversation_id: int):
    """SPEC-09 §4 -- deterministic, $0 staff guidance:
    1. kb_matches: top-3 published articles by embedding similarity (skipped ->
       [] when embeddings are on the non-semantic fallback);
    2. actions: keyword/context rule table from PLAYER_DATA_MAP §5;
    3. playbook: highest-similarity playbook-tagged article ('suggested reply
       basis'), None when embeddings are unavailable."""
    conn = db.get_conn()
    convo = conn.execute("SELECT * FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
    if not convo:
        raise HTTPException(404, "conversation not found")
    srow = conn.execute(
        "SELECT question FROM suggestions WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
        (conversation_id,),
    ).fetchone()
    question = srow["question"] if srow else None
    if not question:
        mrow = conn.execute(
            "SELECT text FROM messages WHERE conversation_id = ? AND role = 'user' "
            "ORDER BY id DESC LIMIT 1", (conversation_id,)).fetchone()
        question = mrow["text"] if mrow else ""
    try:
        context = json.loads(convo["context"] or "{}")
    except (ValueError, TypeError):
        context = {}

    admin_url = _admin_url(convo["player_id"])
    actions = ticketing.build_recommendations(question, convo["player_id"], context, admin_url)

    kb_matches, playbook = [], None
    # Only confident matches are worth staff attention (config
    # recommendations.min_similarity, default 0.8 -- hot-reloadable). Each item
    # carries its raw similarity so the UI can render the %.
    min_sim = float(getattr(config, "RECOMMENDATIONS_MIN_SIMILARITY", 0.8))
    if question and not embeddings.is_using_fallback():
        try:
            q_vec = embeddings.embed(question)
            for row_id, sim in vectorstore.search("kb_articles", q_vec, top_k=3,
                                                  where="status = 'published'"):
                if float(sim) < min_sim:
                    continue
                art = conn.execute(
                    "SELECT id, title, category, tags FROM kb_articles WHERE id = ?",
                    (row_id,)).fetchone()
                if art:
                    kb_matches.append({**dict(art), "similarity": round(float(sim), 3)})
            hits = vectorstore.search("kb_articles", q_vec, top_k=1,
                                      where="status = 'published' AND tags LIKE '%playbook%'")
            if hits:
                art = conn.execute(
                    "SELECT id, title, answer, category FROM kb_articles WHERE id = ?",
                    (hits[0][0],)).fetchone()
                if art:
                    playbook = {**dict(art), "similarity": round(float(hits[0][1]), 3)}
        except Exception as e:
            # degrade, never 500 -- recommendations are advisory (acceptance #4)
            print(f"[warn] recommendations: KB match failed ({e!r})")
            kb_matches, playbook = [], None

    return {"conversation_id": conversation_id, "question": question,
            "kb_matches": kb_matches, "actions": actions, "playbook": playbook,
            "min_similarity": min_sim,
            "embeddings_available": not embeddings.is_using_fallback()}


@router.get("/outreach/status", dependencies=[Depends(require_service_key)])
def outreach_status():
    """Why the outreach buttons are disabled (SPEC-09 §5) -- toggle + env state."""
    return outreach.status()


@router.post("/conversations/{conversation_id}/outreach/inbox", dependencies=[Depends(require_service_key)])
def outreach_inbox(conversation_id: int, payload: dict, actor: str = Depends(_staff_actor)):
    """SPEC-09 §5 in-game inbox outreach -- wired but inert: refuses (403) until
    the outreach_enabled toggle AND the INDUS_* env AND the confirmed IndusAPI
    contract all exist. Every attempt, refused or not, logs one outreach_inbox
    event (title + first 80 chars of the body only, never the full text)."""
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    if not title or not body:
        raise HTTPException(400, "title and body required")
    conn = db.get_conn()
    convo = conn.execute("SELECT player_id FROM conversations WHERE id = ?",
                         (conversation_id,)).fetchone()
    if not convo:
        raise HTTPException(404, "conversation not found")
    sid = (convo["player_id"] or "").strip()
    if not sid:
        raise HTTPException(428, "no resolved SID on this ticket -- outreach needs a player")

    result = outreach.send_inbox_message(sid, title, body, actor)
    with db.tx() as c:
        ticketing.add_event(c, conversation_id, actor, "outreach_inbox", {
            "sid": sid, "sent": bool(result.get("sent")),
            "refused_reason": result.get("reason"),
            "title": title[:120], "body_preview": body[:80],
        })
    if not result.get("sent"):
        raise HTTPException(403, f"outreach refused: {result.get('reason')}")
    return {"ok": True, "sent": True}


# -------------------------------------------------------------------- suggestions --
# Ticket Review grid backend (SHADOW_BACKFILL_SPEC Phase 4). Serves backfill +
# (later) live-shadow suggestions across sources. Constraint 6: suggested_answer
# is immutable -- PATCH here only ever writes edited_answer; regeneration happens
# in the replay script as a new row with supersedes_id, never via this API.

def _admin_url(player_id: str | None) -> str | None:
    """Consistent player SID -> game-admin deep link, same convention used
    everywhere a SID is known regardless of source (Discord/Freshdesk/email)."""
    return f"https://admin.brx.indusgame.com/player/{player_id}" if player_id else None


def _ticket_meta(source: str, context: str | None, external_id: str | None,
                 created_at: str | None) -> dict:
    """Derives the Ticket Review grid's To / From / Date columns (PROJECT_HANDOFF
    §4A #1, #2, #4) from a conversation, source-aware and with graceful fallbacks.

    The heavy lifting (recipient address, Discord submitter username, the real
    reported date) is done once, offline, by scripts/enrich_ticket_metadata.py,
    which persists the values into context -- so this stays a cheap per-row read
    with no CSV/raw-file access at request time. `date_is_estimated` tells the UI
    when to show the date under a softer "reported" label vs. an exact one."""
    try:
        ctx = json.loads(context) if context else {}
    except (ValueError, TypeError):
        ctx = {}

    # To -- who the ticket was addressed to.
    to_display = ctx.get("to")
    if not to_display and source == "discord":
        cname = ctx.get("channel_name") or "ticket"
        to_display = f"{cname} / {external_id}" if external_id else cname

    # From -- the player identity. Discord's real player is the first non-bot
    # author (stored as context.submitter by the enrichment pass); email/freshdesk
    # use the sender address.
    from_display = ctx.get("submitter") if source == "discord" else ctx.get("from")

    # Date -- the ORIGINAL message date, not the import/replay date. Prefer the
    # enrichment-persisted reported_date; fall back to the conversation's own
    # created_at (real for email, an import stamp for freshdesk -- hence estimated).
    reported_date = ctx.get("reported_date")
    date_is_estimated = False
    if not reported_date:
        reported_date = (created_at or "")[:10] or None
        date_is_estimated = source != "email"

    return {
        "to_display": to_display or None,
        "from_display": from_display or None,
        "reported_date": reported_date,
        "date_is_estimated": date_is_estimated,
    }


@router.get("/suggestions", dependencies=[Depends(require_service_key)])
def list_suggestions(source: str | None = None, origin: str | None = None,
                     tier: int | None = None, status: str | None = None, limit: int = 200):
    """Joined conversations + suggestions rows for the Ticket Review grid.
    Filters: source (discord|freshdesk|email), origin (backfill|live), tier, status.
    Shows only the LATEST suggestion per ticket (superseded re-run rows stay in the
    DB as training data but are hidden here, so the grid is one row per ticket).

    SPEC-09: rows additionally carry the conversation's ticketing state (priority /
    assignee / ticket_status / due_at / overdue / due_in_seconds / public_id) so the
    Ticket Review grid can render pills + SLA cells without a second request. All
    additive -- existing consumers keep their shape. Listing also runs the lazy
    sla_breach sweep (SPEC-09 §3 'on list queries')."""
    with db.tx() as c:
        ticketing.sweep_sla_breaches(c)
    conn = db.get_conn()
    # restrict to the newest suggestion per conversation
    where = ["s.id = (SELECT MAX(s2.id) FROM suggestions s2 WHERE s2.conversation_id = s.conversation_id)"]
    params = []
    if source:
        where.append("s.source = ?"); params.append(source)
    if origin:
        where.append("c.origin = ?"); params.append(origin)
    if tier is not None:
        where.append("s.tier = ?"); params.append(tier)
    if status:
        where.append("s.status = ?"); params.append(status)
    where_sql = "WHERE " + " AND ".join(where)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT s.id, s.conversation_id, s.source, s.question, s.suggested_answer,
               s.edited_answer, s.tier, s.staff_answer, s.status, s.approved_at,
               s.sent_at, s.created_at, s.supersedes_id,
               c.channel, c.external_id, c.origin, c.player_id, c.context,
               c.created_at AS convo_created_at,
               c.status AS convo_status, COALESCE(c.priority, 'P3') AS priority,
               c.assignee, c.due_at, c.first_human_response_at, c.closed_at,
               c.public_id,
               {ticketing.OVERDUE_SQL} AS overdue,
               {ticketing.DUE_IN_SQL} AS due_in_seconds
        FROM suggestions s JOIN conversations c ON c.id = s.conversation_id
        {where_sql}
        ORDER BY s.created_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["admin_url"] = _admin_url(d.get("player_id"))
        d["discord_url"] = _discord_url(d.get("channel"), d.get("external_id"))
        d["final_answer"] = d.get("edited_answer") or d.get("suggested_answer")
        d["ticket_status"] = ticketing.display_status(d.get("convo_status"))
        d["overdue"] = bool(d.get("overdue"))
        # To / From / Date columns (§4A #1, #2, #4)
        d.update(_ticket_meta(d.get("source"), d.get("context"),
                              d.get("external_id"), d.get("convo_created_at")))
        d["actions"] = []  # future action buttons (§4) -- empty for now
        out.append(d)
    return out


@router.patch("/suggestions/{suggestion_id}", dependencies=[Depends(require_service_key)])
def edit_suggestion(suggestion_id: int, payload: dict):
    """ONLY edits edited_answer. suggested_answer is immutable training data
    (constraint 6) -- any attempt to set it is rejected."""
    if "suggested_answer" in payload:
        raise HTTPException(400, "suggested_answer is immutable; edits go in edited_answer")
    if "edited_answer" not in payload:
        raise HTTPException(400, "only edited_answer is editable")
    conn = db.get_conn()
    row = conn.execute("SELECT id FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if not row:
        raise HTTPException(404, "suggestion not found")
    with db.tx() as c:
        c.execute("UPDATE suggestions SET edited_answer = ? WHERE id = ?",
                  (payload["edited_answer"], suggestion_id))
    return {"ok": True}


@router.post("/suggestions/{suggestion_id}/approve", dependencies=[Depends(require_service_key)])
def approve_suggestion(suggestion_id: int, actor: str = Depends(_staff_actor)):
    """Marks 'this is the answer I'd have wanted'. Does NOT send (constraint 5) --
    for backfill rows it just feeds Phase 5 KB enrichment + Phase 7 tone training;
    sending is a separate, Phase-6, live-only, per-message action.

    SPEC-09 §6: approving counts as the first staff response on the ticket --
    stamps first_human_response_at (first time only) and logs a reply_sent event."""
    with db.tx() as conn:
        cur = conn.execute(
            "UPDATE suggestions SET status='approved', approved_at=datetime('now') WHERE id = ?",
            (suggestion_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "suggestion not found")
        convo_id = conn.execute(
            "SELECT conversation_id FROM suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()["conversation_id"]
        ticketing.stamp_first_human_response(conn, convo_id)
        ticketing.add_event(conn, convo_id, actor, "reply_sent",
                            {"suggestion_id": suggestion_id, "via": "approve"})
    return {"ok": True}


@router.post("/suggestions/{suggestion_id}/reject", dependencies=[Depends(require_service_key)])
def reject_suggestion(suggestion_id: int):
    with db.tx() as conn:
        cur = conn.execute("UPDATE suggestions SET status='rejected' WHERE id = ?", (suggestion_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "suggestion not found")
    return {"ok": True}


@router.get("/suggestions/{suggestion_id}/translate", dependencies=[Depends(require_service_key)])
def translate_suggestion(suggestion_id: int, target: str = "en"):
    """Translate a ticket's reviewer-facing text (player question + historical staff
    reply + bot's final answer) into `target` (default English) for the Ticket Review
    detail pane (§4C). Returns a cached translation if one exists; otherwise detects
    the source language, SKIPS (no API cost) if it's already the target language,
    else translates once with Haiku and caches in ticket_translations.

    Response: {suggestion_id, target_lang, source_lang, skipped, cached,
               question, staff_answer, final_answer}. When skipped/same-language the
    original text is echoed back so the client can render uniformly."""
    conn = db.get_conn()
    row = conn.execute(
        """SELECT s.id, s.question, s.staff_answer, s.edited_answer, s.suggested_answer
           FROM suggestions s WHERE s.id = ?""", (suggestion_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "suggestion not found")
    d = dict(row)
    final_answer = d.get("edited_answer") or d.get("suggested_answer") or ""
    originals = {
        "question": d.get("question") or "",
        "staff_answer": d.get("staff_answer") or "",
        "final_answer": final_answer,
    }

    cached = conn.execute(
        "SELECT source_lang, question, staff_answer, final_answer FROM ticket_translations "
        "WHERE suggestion_id = ? AND target_lang = ?", (suggestion_id, target),
    ).fetchone()
    if cached:
        c = dict(cached)
        return {"suggestion_id": suggestion_id, "target_lang": target,
                "source_lang": c["source_lang"], "skipped": False, "cached": True,
                "question": c["question"], "staff_answer": c["staff_answer"],
                "final_answer": c["final_answer"]}

    # Detect on the player's question (the field most likely to be non-English).
    source_lang = llm.detect_language(originals["question"])
    if source_lang == target:
        # Already in the target language -- cache the originals so the button is a
        # one-time no-op and we never pay to "translate" English->English.
        with db.tx() as cx:
            cx.execute(
                "INSERT OR REPLACE INTO ticket_translations "
                "(suggestion_id, target_lang, source_lang, question, staff_answer, final_answer) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (suggestion_id, target, source_lang, originals["question"],
                 originals["staff_answer"], originals["final_answer"]),
            )
        return {"suggestion_id": suggestion_id, "target_lang": target,
                "source_lang": source_lang, "skipped": True, "cached": False, **originals}

    translated = llm.translate_text_fields(originals, target_lang=target)
    with db.tx() as cx:
        cx.execute(
            "INSERT OR REPLACE INTO ticket_translations "
            "(suggestion_id, target_lang, source_lang, question, staff_answer, final_answer) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (suggestion_id, target, source_lang, translated["question"],
             translated["staff_answer"], translated["final_answer"]),
        )
    return {"suggestion_id": suggestion_id, "target_lang": target,
            "source_lang": source_lang, "skipped": False, "cached": False, **translated}


@router.post("/suggestions/{suggestion_id}/send", dependencies=[Depends(require_service_key)])
def send_suggestion(suggestion_id: int, actor: str = Depends(_staff_actor)):
    """Phase 6 — the ONLY Discord-write path. Posts the approved reply to the live ticket
    channel. Every guard below must pass or it refuses (4xx); nothing auto-sends and it's
    idempotent (a completed send is recorded in suggestion_actions with a unique index, so
    a retry is a no-op). Requires a two-click flow upstream: Approve, then Send.

    Guards (PHASE_6_7_SPEC): shadow_mode ON · status='approved' · conversation origin='live'
    · channel='discord' · SID-first gate (player_id set) · not already sent · token set."""
    # Guard 1: shadow mode must be ON. shadow_mode OFF would be auto-reply territory,
    # which is explicitly out of scope — refuse to send in that mode.
    config.reload()
    if not config.DISCORD_SHADOW_MODE:
        raise HTTPException(409, "shadow_mode is OFF — sending is disabled in this mode")

    conn = db.get_conn()
    row = conn.execute(
        """SELECT s.id, s.status, s.suggested_answer, s.edited_answer, s.sent_at,
                  c.origin, c.channel, c.external_id, c.player_id, c.id AS conversation_id
           FROM suggestions s JOIN conversations c ON c.id = s.conversation_id
           WHERE s.id = ?""",
        (suggestion_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "suggestion not found")
    d = dict(row)

    if d["status"] == "sent" or d["sent_at"]:
        return {"ok": True, "already_sent": True, "discord_message_id": None}
    if d["status"] != "approved":
        raise HTTPException(409, "only an approved suggestion can be sent (approve it first)")
    if d["origin"] != "live":
        raise HTTPException(403, "refusing to send a backfill row — sending is live-only")
    if d["channel"] != "discord":
        raise HTTPException(400, "sending is only implemented for Discord tickets")
    if not (d["player_id"] or "").strip():
        raise HTTPException(428, "SID-first gate: resolve the player's SID before sending")
    if not d["external_id"]:
        raise HTTPException(409, "conversation has no Discord channel id")

    content = d["edited_answer"] or d["suggested_answer"]

    # Idempotency reservation: claim the send BEFORE posting. The partial unique index
    # (uq_send_once) makes a concurrent/duplicate click fail here instead of double-posting.
    try:
        with db.tx() as c:
            c.execute(
                "INSERT INTO suggestion_actions (suggestion_id, action_type, payload_json, status) "
                "VALUES (?, 'send', ?, 'done')",
                (suggestion_id, json.dumps({"channel_id": d["external_id"]})),
            )
    except Exception:
        return {"ok": True, "already_sent": True, "discord_message_id": None}

    try:
        message_id = discord_send.post_message(d["external_id"], content)
    except discord_send.NotConfigured:
        # roll back the reservation so a real send can happen once the token is set
        with db.tx() as c:
            c.execute("DELETE FROM suggestion_actions WHERE suggestion_id=? AND action_type='send'",
                      (suggestion_id,))
        raise HTTPException(503, "DISCORD_BOT_TOKEN unset — go-live not enabled yet")
    except discord_send.SendFailed as e:
        with db.tx() as c:
            c.execute("DELETE FROM suggestion_actions WHERE suggestion_id=? AND action_type='send'",
                      (suggestion_id,))
        raise HTTPException(502, f"Discord rejected the send: {e.detail}")

    with db.tx() as c:
        c.execute(
            "UPDATE suggestions SET status='sent', sent_at=datetime('now'), discord_message_id=? WHERE id=?",
            (message_id, suggestion_id))
        c.execute(
            "INSERT INTO messages (conversation_id, role, tier_used, text) VALUES (?, 'bot', NULL, ?)",
            (d["conversation_id"], content))
        c.execute(
            "UPDATE suggestion_actions SET payload_json=?, executed_at=datetime('now') "
            "WHERE suggestion_id=? AND action_type='send'",
            (json.dumps({"channel_id": d["external_id"], "discord_message_id": message_id}), suggestion_id))
        # SPEC-09 §6: the first staff reply via the approve/send path stamps
        # first_human_response_at and logs a reply_sent audit event.
        ticketing.stamp_first_human_response(c, d["conversation_id"])
        ticketing.add_event(c, d["conversation_id"], actor, "reply_sent",
                            {"suggestion_id": suggestion_id, "via": "send",
                             "discord_message_id": message_id})
    return {"ok": True, "sent": True, "discord_message_id": message_id}


@router.get("/suggestions/summary", dependencies=[Depends(require_service_key)])
def suggestions_summary():
    """Counts by source x status x tier for the review grid's section headers/filters.
    Counts only the LATEST suggestion per ticket (matches what the grid shows) so
    superseded re-run rows don't inflate the tab badges."""
    conn = db.get_conn()
    latest = ("FROM suggestions s WHERE s.id = "
              "(SELECT MAX(s2.id) FROM suggestions s2 WHERE s2.conversation_id = s.conversation_id)")
    by_source = [dict(r) for r in conn.execute(
        f"SELECT s.source AS source, s.status AS status, COUNT(*) n {latest} GROUP BY s.source, s.status").fetchall()]
    by_tier = [dict(r) for r in conn.execute(
        f"SELECT s.tier AS tier, COUNT(*) n {latest} GROUP BY s.tier ORDER BY s.tier").fetchall()]
    return {"by_source": by_source, "by_tier": by_tier}


# ---------------------------------------------------------------------------- kb --

_KB_LIST_COLUMNS = "id, title, symptom, answer, tags, status, category, source, created_at, updated_at"


@router.get("/kb/categories", dependencies=[Depends(require_service_key)])
def kb_categories():
    """Fixed ≤8-item category list the SupportKB tab groups articles by --
    single source of truth so the dropdown/filter UI never drifts from what
    app/llm.py can actually assign."""
    return {"categories": config.KB_CATEGORIES, "default": config.KB_DEFAULT_CATEGORY}


def _backfill_categories(conn, rows: list[dict]) -> None:
    """Self-healing: any row created before the `category` column existed (or
    whose category is blank for some other reason) gets a cheap offline keyword
    guess persisted in place, no Claude call and no separate migration script
    for the user to remember to run. Runs at most once per row, ever."""
    missing = [r for r in rows if not r.get("category")]
    if not missing:
        return
    with db.tx() as c:
        for r in missing:
            guess = llm.categorize_keywords(f"{r['title']} {r['symptom']} {r['tags']}")
            c.execute("UPDATE kb_articles SET category = ? WHERE id = ?", (guess, r["id"]))
            r["category"] = guess


@router.get("/kb", dependencies=[Depends(require_service_key)])
def list_kb(status: str = "all"):
    # Deliberately excludes `embedding` -- it's a raw packed-float32 BLOB (see
    # app/vectorstore.py), and FastAPI's jsonable_encoder tries to UTF-8 decode
    # any `bytes` value it finds, which crashes with UnicodeDecodeError on binary
    # data. list_canned() below already excludes it the same way; this endpoint
    # just never had rows with a real embedding until the KB was actually built,
    # so the bug stayed latent.
    conn = db.get_conn()
    if status == "all":
        rows = conn.execute(
            f"SELECT {_KB_LIST_COLUMNS} FROM kb_articles ORDER BY updated_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_KB_LIST_COLUMNS} FROM kb_articles WHERE status = ? ORDER BY updated_at DESC",
            (status,),
        ).fetchall()
    rows = [dict(r) for r in rows]
    _backfill_categories(conn, rows)
    return rows


@router.patch("/kb/{article_id}", dependencies=[Depends(require_service_key)])
def update_kb(article_id: int, payload: dict):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM kb_articles WHERE id = ?", (article_id,)).fetchone()
    if not row:
        raise HTTPException(404, "article not found")
    fields = {k: payload[k] for k in ("title", "symptom", "answer", "tags", "status", "category") if k in payload}
    if not fields:
        raise HTTPException(400, "no valid fields")
    if "category" in fields and fields["category"] not in config.KB_CATEGORIES:
        raise HTTPException(400, f"category must be one of {config.KB_CATEGORIES}")
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    content_changed = any(k in fields for k in ("title", "symptom", "answer"))
    with db.tx() as c:
        c.execute(
            f"UPDATE kb_articles SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            (*fields.values(), article_id),
        )
        if content_changed:
            # Cached translations (see /kb/{id}/translate/{lang} below) are now
            # stale -- drop them so the next view regenerates from the edited text
            # rather than silently showing an out-of-date translation forever.
            c.execute("DELETE FROM kb_translations WHERE article_id = ?", (article_id,))
    if "title" in fields or "symptom" in fields:
        new_title = fields.get("title", row["title"])
        new_symptom = fields.get("symptom", row["symptom"])
        vectorstore.upsert("kb_articles", article_id, embeddings.embed(f"{new_title}\n{new_symptom}"))
    return {"ok": True}


@router.get("/kb/{article_id}/translate/{lang}", dependencies=[Depends(require_service_key)])
def translate_kb(article_id: int, lang: str):
    """Returns a cached translation if one exists, otherwise generates it via
    Claude, caches it in kb_translations, and returns it. Cache is invalidated
    by update_kb() above whenever the source article's content changes."""
    if lang not in config.KB_TRANSLATION_LANGS:
        raise HTTPException(400, f"unsupported lang {lang!r}, must be one of {list(config.KB_TRANSLATION_LANGS)}")
    conn = db.get_conn()
    article = conn.execute("SELECT * FROM kb_articles WHERE id = ?", (article_id,)).fetchone()
    if not article:
        raise HTTPException(404, "article not found")
    cached = conn.execute(
        "SELECT title, symptom, answer FROM kb_translations WHERE article_id = ? AND lang = ?",
        (article_id, lang),
    ).fetchone()
    if cached:
        return {"lang": lang, "cached": True, **dict(cached)}
    translated = llm.translate_article(article["title"], article["symptom"], article["answer"], lang)
    with db.tx() as c:
        c.execute(
            "INSERT INTO kb_translations (article_id, lang, title, symptom, answer) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(article_id, lang) DO UPDATE SET title=excluded.title, symptom=excluded.symptom, answer=excluded.answer",
            (article_id, lang, translated["title"], translated["symptom"], translated["answer"]),
        )
    return {"lang": lang, "cached": False, **translated}


@router.delete("/kb/{article_id}", dependencies=[Depends(require_service_key)])
def delete_kb(article_id: int):
    with db.tx() as conn:
        conn.execute("DELETE FROM kb_articles WHERE id = ?", (article_id,))
    return {"ok": True}


@router.post("/kb/{article_id}/promote_canned", dependencies=[Depends(require_service_key)])
def promote_to_canned(article_id: int, payload: dict):
    trigger_text = payload.get("trigger_text")
    if not trigger_text:
        raise HTTPException(400, "trigger_text required")
    conn = db.get_conn()
    article = conn.execute("SELECT * FROM kb_articles WHERE id = ?", (article_id,)).fetchone()
    if not article:
        raise HTTPException(404, "article not found")
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO canned (trigger_text, answer, source_article_id) VALUES (?, ?, ?)",
            (trigger_text, article["answer"], article_id),
        )
        canned_id = cur.lastrowid
    vectorstore.upsert("canned", canned_id, embeddings.embed(trigger_text))
    return {"ok": True, "canned_id": canned_id}


# ------------------------------------------------------------------------ canned --

@router.get("/canned", dependencies=[Depends(require_service_key)])
def list_canned():
    conn = db.get_conn()
    rows = conn.execute("SELECT id, trigger_text, answer, source_article_id, created_at FROM canned ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


@router.post("/canned", dependencies=[Depends(require_service_key)])
def create_canned(payload: dict):
    trigger_text = payload.get("trigger_text")
    answer = payload.get("answer")
    if not trigger_text or not answer:
        raise HTTPException(400, "trigger_text and answer required")
    with db.tx() as c:
        cur = c.execute("INSERT INTO canned (trigger_text, answer) VALUES (?, ?)", (trigger_text, answer))
        canned_id = cur.lastrowid
    vectorstore.upsert("canned", canned_id, embeddings.embed(trigger_text))
    return {"ok": True, "id": canned_id}


@router.patch("/canned/{canned_id}", dependencies=[Depends(require_service_key)])
def update_canned(canned_id: int, payload: dict):
    fields = {k: payload[k] for k in ("trigger_text", "answer") if k in payload}
    if not fields:
        raise HTTPException(400, "no valid fields")
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with db.tx() as c:
        c.execute(f"UPDATE canned SET {set_clause} WHERE id = ?", (*fields.values(), canned_id))
    if "trigger_text" in fields:
        vectorstore.upsert("canned", canned_id, embeddings.embed(fields["trigger_text"]))
    return {"ok": True}


@router.delete("/canned/{canned_id}", dependencies=[Depends(require_service_key)])
def delete_canned(canned_id: int):
    with db.tx() as conn:
        conn.execute("DELETE FROM canned WHERE id = ?", (canned_id,))
    return {"ok": True}


# ----------------------------------------------------------------------- metrics --

@router.get("/metrics", dependencies=[Depends(require_service_key)])
def metrics(days: int = 7):
    conn = db.get_conn()
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT * FROM metrics_daily WHERE date >= ? ORDER BY date ASC", (since,)
    ).fetchall()
    rows = [dict(r) for r in rows]
    totals = {
        "tier0": sum(r["tier0_count"] for r in rows),
        "tier1": sum(r["tier1_count"] for r in rows),
        "tier2": sum(r["tier2_count"] for r in rows),
        "tier3": sum(r["tier3_count"] for r in rows),
        "thumbs_up": sum(r["thumbs_up"] for r in rows),
        "thumbs_down": sum(r["thumbs_down"] for r in rows),
    }
    total_msgs = totals["tier0"] + totals["tier1"] + totals["tier2"] + totals["tier3"]
    totals["deflection_rate"] = (
        round((totals["tier0"] + totals["tier1"] + totals["tier2"]) / total_msgs, 3)
        if total_msgs else None
    )
    return {"daily": rows, "totals": totals, "sid_coverage": _sid_coverage(conn)}


_SID_SOURCES = ("claimed", "email_match", "scan", "deeplink", "manual")


def _sid_coverage(conn, window_days: int = 30) -> dict:
    """SID coverage (SPEC-01 §4): of the conversations created in the window, how
    many carry a resolved player_id, and via which intake method (sid_source).
    'null' counts rows with no recorded source -- pre-SPEC-01 history plus tickets
    that never resolved. Baseline for the intake changes; shown in Support Settings."""
    rows = conn.execute(
        """
        SELECT sid_source,
               COUNT(*) AS n,
               SUM(CASE WHEN player_id IS NOT NULL AND player_id != '' THEN 1 ELSE 0 END) AS with_pid
        FROM conversations
        WHERE created_at >= datetime('now', ?)
        GROUP BY sid_source
        """,
        (f"-{int(window_days)} days",),
    ).fetchall()
    by_source = {s: 0 for s in (*_SID_SOURCES, "null")}
    total = with_player_id = 0
    for r in rows:
        key = r["sid_source"] if r["sid_source"] in _SID_SOURCES else "null"
        by_source[key] += r["n"]
        total += r["n"]
        with_player_id += r["with_pid"] or 0
    return {
        "window_days": window_days,
        "total_conversations": total,
        "with_player_id": with_player_id,
        "pct": round(with_player_id / total, 3) if total else None,
        "by_source": by_source,
    }


# -------------------------------------------------------------- tone (Phase 7) --

@router.get("/tone", dependencies=[Depends(require_service_key)])
def tone_stats():
    """Current cached tone style block stats (counts, size, when built) + a preview.
    Powers the 'Refresh tone examples' card in Support Settings."""
    stats = tone.get_stats()
    block = tone.get_style_block()
    stats["preview"] = block[:1200]
    stats["active"] = bool(block)
    return stats


@router.post("/tone/refresh", dependencies=[Depends(require_service_key)])
def tone_refresh(payload: dict | None = None):
    """Rebuild the tone style block from the current suggestions corpus (correction
    pairs + staff replies) and cache it. Bounded selection, not a per-call query.
    Optional payload: {n_pairs, m_staff} to override the defaults."""
    payload = payload or {}
    n_pairs = int(payload.get("n_pairs", tone.DEFAULT_N_PAIRS))
    m_staff = int(payload.get("m_staff", tone.DEFAULT_M_STAFF))
    return tone.build_style_block(n_pairs=n_pairs, m_staff=m_staff)


# ----------------------------------------------------------------------- settings --

@router.get("/diagnostics", dependencies=[Depends(require_service_key)])
def get_diagnostics():
    """Full System Test (SPEC-08 shadow readiness): SQLite/KB/scope gate/game Mongo/
    player context, each step with sanitized error detail. Read-only."""
    from app import diagnostics
    return diagnostics.run_full_test()


@router.get("/settings", dependencies=[Depends(require_service_key)])
def get_settings():
    return config.get_thresholds_dict()


@router.post("/settings", dependencies=[Depends(require_service_key)])
def post_settings(payload: dict):
    thresholds = payload.get("thresholds")
    sensitive_keywords = payload.get("sensitive_keywords")
    shadow_mode = payload.get("shadow_mode")
    chat_enabled = payload.get("chat_enabled")  # shadow chat kill switch (SPEC-08 §8)
    outreach_enabled = payload.get("outreach_enabled")  # SPEC-09 §5 outreach toggle
    return config.write_settings(
        thresholds=thresholds, sensitive_keywords=sensitive_keywords, shadow_mode=shadow_mode,
        chat_enabled=chat_enabled, outreach_enabled=outreach_enabled,
    )
