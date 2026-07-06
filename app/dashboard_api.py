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

from app import db, embeddings, vectorstore, config, llm

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


@router.post("/conversations/{conversation_id}/resolve", dependencies=[Depends(require_service_key)])
def resolve_conversation(conversation_id: int):
    with db.tx() as conn:
        conn.execute(
            "UPDATE conversations SET status='resolved', updated_at=datetime('now') WHERE id = ?",
            (conversation_id,),
        )
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


# -------------------------------------------------------------------- suggestions --
# Ticket Review grid backend (SHADOW_BACKFILL_SPEC Phase 4). Serves backfill +
# (later) live-shadow suggestions across sources. Constraint 6: suggested_answer
# is immutable -- PATCH here only ever writes edited_answer; regeneration happens
# in the replay script as a new row with supersedes_id, never via this API.

def _admin_url(player_id: str | None) -> str | None:
    """Consistent player SID -> game-admin deep link, same convention used
    everywhere a SID is known regardless of source (Discord/Freshdesk/email)."""
    return f"https://admin.brx.indusgame.com/player/{player_id}" if player_id else None


@router.get("/suggestions", dependencies=[Depends(require_service_key)])
def list_suggestions(source: str | None = None, origin: str | None = None,
                     tier: int | None = None, status: str | None = None, limit: int = 200):
    """Joined conversations + suggestions rows for the Ticket Review grid.
    Filters: source (discord|freshdesk|email), origin (backfill|live), tier, status."""
    conn = db.get_conn()
    where, params = [], []
    if source:
        where.append("s.source = ?"); params.append(source)
    if origin:
        where.append("c.origin = ?"); params.append(origin)
    if tier is not None:
        where.append("s.tier = ?"); params.append(tier)
    if status:
        where.append("s.status = ?"); params.append(status)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT s.id, s.conversation_id, s.source, s.question, s.suggested_answer,
               s.edited_answer, s.tier, s.staff_answer, s.status, s.approved_at,
               s.sent_at, s.created_at, s.supersedes_id,
               c.channel, c.external_id, c.origin, c.player_id, c.context
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
def approve_suggestion(suggestion_id: int):
    """Marks 'this is the answer I'd have wanted'. Does NOT send (constraint 5) --
    for backfill rows it just feeds Phase 5 KB enrichment + Phase 7 tone training;
    sending is a separate, Phase-6, live-only, per-message action."""
    with db.tx() as conn:
        cur = conn.execute(
            "UPDATE suggestions SET status='approved', approved_at=datetime('now') WHERE id = ?",
            (suggestion_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "suggestion not found")
    return {"ok": True}


@router.post("/suggestions/{suggestion_id}/reject", dependencies=[Depends(require_service_key)])
def reject_suggestion(suggestion_id: int):
    with db.tx() as conn:
        cur = conn.execute("UPDATE suggestions SET status='rejected' WHERE id = ?", (suggestion_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "suggestion not found")
    return {"ok": True}


@router.get("/suggestions/summary", dependencies=[Depends(require_service_key)])
def suggestions_summary():
    """Counts by source x status x tier for the review grid's section headers/filters."""
    conn = db.get_conn()
    by_source = [dict(r) for r in conn.execute(
        "SELECT source, status, COUNT(*) n FROM suggestions GROUP BY source, status").fetchall()]
    by_tier = [dict(r) for r in conn.execute(
        "SELECT tier, COUNT(*) n FROM suggestions GROUP BY tier ORDER BY tier").fetchall()]
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
    return {"daily": rows, "totals": totals}


# ----------------------------------------------------------------------- settings --

@router.get("/settings", dependencies=[Depends(require_service_key)])
def get_settings():
    return config.get_thresholds_dict()


@router.post("/settings", dependencies=[Depends(require_service_key)])
def post_settings(payload: dict):
    thresholds = payload.get("thresholds")
    sensitive_keywords = payload.get("sensitive_keywords")
    shadow_mode = payload.get("shadow_mode")
    return config.write_settings(
        thresholds=thresholds, sensitive_keywords=sensitive_keywords, shadow_mode=shadow_mode
    )
