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

from app import db, embeddings, vectorstore, config

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
def feed(limit: int = 50):
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT c.id, c.channel, c.external_id, c.status, c.context, c.player_id, c.updated_at,
               (SELECT text FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_text,
               (SELECT tier_used FROM messages WHERE conversation_id = c.id AND role='bot' ORDER BY id DESC LIMIT 1) AS last_tier
        FROM conversations c
        ORDER BY c.updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_enrich(dict(r)) for r in rows]


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


# ---------------------------------------------------------------------------- kb --

@router.get("/kb", dependencies=[Depends(require_service_key)])
def list_kb(status: str = "all"):
    conn = db.get_conn()
    if status == "all":
        rows = conn.execute("SELECT * FROM kb_articles ORDER BY updated_at DESC").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM kb_articles WHERE status = ? ORDER BY updated_at DESC", (status,)
        ).fetchall()
    return [dict(r) for r in rows]


@router.patch("/kb/{article_id}", dependencies=[Depends(require_service_key)])
def update_kb(article_id: int, payload: dict):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM kb_articles WHERE id = ?", (article_id,)).fetchone()
    if not row:
        raise HTTPException(404, "article not found")
    fields = {k: payload[k] for k in ("title", "symptom", "answer", "tags", "status") if k in payload}
    if not fields:
        raise HTTPException(400, "no valid fields")
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    with db.tx() as c:
        c.execute(
            f"UPDATE kb_articles SET {set_clause}, updated_at = datetime('now') WHERE id = ?",
            (*fields.values(), article_id),
        )
    if "title" in fields or "symptom" in fields:
        new_title = fields.get("title", row["title"])
        new_symptom = fields.get("symptom", row["symptom"])
        vectorstore.upsert("kb_articles", article_id, embeddings.embed(f"{new_title}\n{new_symptom}"))
    return {"ok": True}


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
    return config.write_settings(thresholds=thresholds, sensitive_keywords=sensitive_keywords)
