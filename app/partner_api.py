"""SPEC-10 §2 -- partner API: player-visible tickets for the SuperX webstore.

Server-to-server namespace `/api/partner/*` with its OWN bearer key
(PARTNER_API_KEY -- never the dashboard key; 503 when unset). Scope is read-only
and SID-bound: every route is keyed to the {sid} in the path and a ticket only
resolves when its conversation.player_id == sid (cross-player reads 404, same
guarantee as the chat engine's cross-SID guard).

Player-safe serialization rules (SPEC-10 §2):
- statuses map player-safe: open/in_progress -> "In progress",
  waiting_player -> "Waiting for you", resolved/closed -> "Resolved"
  (legacy escalated/paused go through ticketing.display_status first);
- the thread carries player messages + APPROVED/SENT staff replies only --
  pending/rejected suggestions, internal notes and raw events never serialize;
- internal fields (assignee, priority, SLA/due_at, actor emails, suggestion
  ids/drafts) are NEVER in any response.

Only conversations that carry a public_id are listed -- that's the id players
see (escalation cards / support site); rows without one predate the public-id
scheme and have no player-facing handle to open them by.
"""
import json
import secrets as _secrets

from fastapi import APIRouter, Depends, Header, HTTPException

from app import config, db, ticketing

router = APIRouter(prefix="/api/partner")

# display status (ticketing.display_status output) -> player-safe label
PLAYER_STATUS = {
    "open": "In progress",
    "in_progress": "In progress",
    "waiting_player": "Waiting for you",
    "resolved": "Resolved",
    "closed": "Resolved",
}
SUBJECT_MAX_CHARS = 80


def require_partner_key(authorization: str = Header(default="")):
    key = getattr(config, "PARTNER_API_KEY", "")
    if not key:
        raise HTTPException(503, "partner API not configured (PARTNER_API_KEY unset)")
    provided = authorization[7:] if authorization.startswith("Bearer ") else authorization
    # constant-time compare against the PARTNER key only -- the dashboard key is
    # structurally never valid here (key separation, SPEC-10 §5)
    if not provided or not _secrets.compare_digest(provided, key):
        raise HTTPException(401, "invalid or missing API key")
    return True


def _player_status(raw: str | None) -> str:
    return PLAYER_STATUS.get(ticketing.display_status(raw), "In progress")


def _subject(question: str | None) -> str | None:
    """First SUBJECT_MAX_CHARS of the ticket question, blob-clipped to one line.
    Chat escalations prefix the question with an internal summary block
    ('[shadow chat escalation — ...] SID: ... \\n\\nIssue: <text>') -- only the
    Issue text is player-safe, so prefer that segment when present."""
    q = question or ""
    if "\n\nIssue: " in q:
        q = q.split("\n\nIssue: ", 1)[1]
    q = " ".join(q.split())
    if not q:
        return None
    return q if len(q) <= SUBJECT_MAX_CHARS else q[: SUBJECT_MAX_CHARS - 1] + "…"


def _resolved_at(row) -> str | None:
    if row["closed_at"]:
        return row["closed_at"]
    if ticketing.display_status(row["status"]) in ("resolved", "closed"):
        return row["updated_at"]
    return None


def _norm_sid(sid: str) -> str:
    return (sid or "").strip().upper()


@router.get("/players/{sid}/tickets", dependencies=[Depends(require_partner_key)])
def list_player_tickets(sid: str, limit: int = 50, offset: int = 0):
    sid = _norm_sid(sid)
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT c.id, c.public_id, c.created_at, c.updated_at, c.status, c.channel,
               c.closed_at,
               (SELECT s.question FROM suggestions s WHERE s.conversation_id = c.id
                ORDER BY s.id DESC LIMIT 1) AS question,
               (EXISTS (SELECT 1 FROM suggestions s WHERE s.conversation_id = c.id
                        AND s.status IN ('approved','sent'))
                OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id
                           AND m.role = 'human')) AS has_staff_reply
        FROM conversations c
        WHERE c.player_id = ? AND c.public_id IS NOT NULL
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT ? OFFSET ?
        """,
        (sid, min(max(limit, 1), 200), max(offset, 0)),
    ).fetchall()
    return [
        {
            "public_id": r["public_id"],
            "created_at": r["created_at"],
            "status": _player_status(r["status"]),
            "channel": r["channel"],
            "subject": _subject(r["question"]),
            "resolved_at": _resolved_at(r),
            "has_staff_reply": bool(r["has_staff_reply"]),
        }
        for r in rows
    ]


@router.get("/players/{sid}/tickets/{public_id}", dependencies=[Depends(require_partner_key)])
def player_ticket_detail(sid: str, public_id: str):
    sid = _norm_sid(sid)
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM conversations WHERE public_id = ? AND player_id = ?",
        (public_id, sid),
    ).fetchone()
    if not row:
        # unknown ticket OR someone else's ticket -- indistinguishable on purpose
        raise HTTPException(404, "ticket not found")
    cid = row["id"]

    # Thread: player messages + approved/sent staff replies ONLY. Staff replies
    # come from (a) 'human'-role messages (takeover agent replies, historical
    # staff replies) and (b) approved/sent suggestion final answers. Bot-role
    # transcript copies and pending/rejected drafts never serialize.
    thread = []
    for m in conn.execute(
        "SELECT role, text, created_at FROM messages "
        "WHERE conversation_id = ? AND role IN ('user','human') ORDER BY id ASC",
        (cid,),
    ).fetchall():
        thread.append({
            "role": "player" if m["role"] == "user" else "staff",
            "text": m["text"],
            "at": m["created_at"],
        })
    for s in conn.execute(
        "SELECT suggested_answer, edited_answer, status, approved_at, sent_at, created_at "
        "FROM suggestions WHERE conversation_id = ? AND status IN ('approved','sent') "
        "ORDER BY id ASC",
        (cid,),
    ).fetchall():
        thread.append({
            "role": "staff",
            "text": s["edited_answer"] or s["suggested_answer"],
            "at": s["sent_at"] or s["approved_at"] or s["created_at"],
        })
    thread.sort(key=lambda m: (m["at"] or ""))

    # Status timeline (created -> in progress -> resolved), player-safe labels
    # only -- no actors, no internal event detail.
    timeline = [{"status": "Created", "at": row["created_at"]}]
    for e in conn.execute(
        "SELECT event, detail_json, created_at FROM ticket_events "
        "WHERE conversation_id = ? AND event = 'status' ORDER BY id ASC",
        (cid,),
    ).fetchall():
        try:
            to = (json.loads(e["detail_json"] or "{}") or {}).get("to")
        except (ValueError, TypeError):
            to = None
        if not to:
            continue
        label = PLAYER_STATUS.get(ticketing.display_status(to), "In progress")
        if timeline[-1].get("status") != label:
            timeline.append({"status": label, "at": e["created_at"]})

    srow = conn.execute(
        "SELECT question FROM suggestions WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
        (cid,),
    ).fetchone()

    return {
        "public_id": row["public_id"],
        "created_at": row["created_at"],
        "status": _player_status(row["status"]),
        "channel": row["channel"],
        "subject": _subject(srow["question"] if srow else None),
        "resolved_at": _resolved_at(row),
        "thread": thread,
        "timeline": timeline,
    }
