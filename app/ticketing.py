"""SPEC-09 ticketing core -- priorities, SLA, status workflow, ticket_events audit log.

Shared helpers used by app/dashboard_api.py (ticket list / PATCH / notes / events /
recommendations / outreach endpoints), app/chat_engine.py (created + escalated events
on escalation) and app/router.py (created event on live conversation creation).

Design rules (SPEC-09):
- Every mutation writes exactly ONE ticket_events row, with the acting staff email
  (X-Staff-Email via the responder proxy) or 'system'/'bot' as actor.
- Priority defaults: payments/refund or ban categories -> P2, everything else P3;
  chat escalations inherit P2 when purchase/ban context is present.
- due_at = created_at + sla[priority] hours (config.yaml `sla:` block); recomputed on
  a priority change ONLY while first_human_response_at is still NULL.
- Overdue = now > due_at AND first_human_response_at IS NULL AND status not in
  (resolved, closed). The lazy sweep writes one sla_breach event per ticket, ever.
- Legacy status values in existing rows are never rewritten; they map for display:
  escalated -> open, paused -> waiting_player. NULL priority renders P3.
"""
import json
import re

from app import config

PRIORITIES = ("P1", "P2", "P3", "P4")
DEFAULT_PRIORITY = "P3"
STATUSES = ("open", "in_progress", "waiting_player", "resolved", "closed")
LEGACY_STATUS_MAP = {"escalated": "open", "paused": "waiting_player"}
EVENTS = ("created", "status", "priority", "assignee", "note", "escalated",
          "reply_sent", "outreach_inbox", "sla_breach",
          "takeover", "release", "rating")  # live chat takeover + end-of-chat stars

# Category cues for default priority + the recommendations rule table (SPEC-09 §3/§4).
# Kept keyword-based on purpose: deterministic, $0, and they keep working when
# fastembed is unavailable (acceptance #4 "degrade cleanly without embeddings").
PAYMENT_RE = re.compile(
    r"\b(purchase[sd]?|payment|paid|pay|bought|buy|charge[ds]?|charged|refund(ed)?|"
    r"chargeback|transaction|receipt|billing|invoice|gems?|coins?|credits?|top.?up|order)\b",
    re.IGNORECASE)
BAN_RE = re.compile(
    r"\b(ban(ned)?|unban|suspend(ed)?|locked|appeal|restriction|muted|chat.?ban|fair.?play)\b",
    re.IGNORECASE)
MISSING_ITEM_RE = re.compile(
    r"\b(missing|disappeared|vanished|lost|gone|didn'?t (get|receive)|not receive[d]?|"
    r"sumiu|desapareceu)\b.{0,80}\b(item|skin|weapon|avatar|frame|crate|reward|"
    r"cosmetic|bundle|pass)\b"
    r"|\b(item|skin|weapon|avatar|frame|crate|reward|cosmetic|bundle|pass)\b.{0,80}"
    r"\b(missing|disappeared|vanished|lost|gone|expired|sumiu|desapareceu)\b",
    re.IGNORECASE | re.DOTALL)
ACCOUNT_LOSS_RE = re.compile(
    r"\b(lost|recover|restore|access|deleted?|reset|stolen|hacked)\b.{0,60}\b(account|progress)\b"
    r"|\b(account|progress)\b.{0,60}\b(lost|recover(y)?|restore|access|deleted?|stolen|hacked)\b"
    r"|\bguest account\b|\b(new|changed) (phone|device)\b",
    re.IGNORECASE | re.DOTALL)

_BANNED_STATES = {"locked", "suspended", "banned"}


def sla_hours(priority: str) -> int:
    hours = getattr(config, "SLA_HOURS", {}) or {}
    return int(hours.get(priority, hours.get(DEFAULT_PRIORITY, 24)))


def display_status(raw: str | None) -> str:
    """Legacy DB statuses map for display (SPEC-09 §2); rows are never rewritten."""
    return LEGACY_STATUS_MAP.get(raw or "open", raw or "open")


def add_event(conn, conversation_id: int, actor: str, event: str, detail: dict | None = None):
    """The single audit-log write path. `conn` is an open transaction connection
    (db.tx()) so an event always commits/rolls back with the mutation it records."""
    conn.execute(
        "INSERT INTO ticket_events (conversation_id, actor, event, detail_json) "
        "VALUES (?, ?, ?, ?)",
        (conversation_id, (actor or "system").strip() or "system", event,
         json.dumps(detail or {}, ensure_ascii=False)),
    )


def default_priority(text: str = "", has_purchase_context: bool = False,
                     has_ban_context: bool = False) -> str:
    """SPEC-09 §3 creation defaults: payments/refund or ban -> P2, else P3.
    Context flags let the chat escalation path inherit P2 from verified
    purchase/ban context even when the issue text itself is vague."""
    if has_purchase_context or has_ban_context:
        return "P2"
    t = text or ""
    if PAYMENT_RE.search(t) or BAN_RE.search(t):
        return "P2"
    return DEFAULT_PRIORITY


def stamp_created(conn, conversation_id: int, actor: str = "system",
                  priority: str | None = None, detail: dict | None = None):
    """Sets priority + due_at (= created_at + sla[priority]) on a freshly inserted
    conversation and writes its `created` event. Call inside the same db.tx()."""
    priority = priority if priority in PRIORITIES else DEFAULT_PRIORITY
    conn.execute(
        "UPDATE conversations SET priority = ?, "
        "due_at = datetime(created_at, ?) WHERE id = ?",
        (priority, f"+{sla_hours(priority)} hours", conversation_id),
    )
    add_event(conn, conversation_id, actor, "created",
              {"priority": priority, **(detail or {})})


def recompute_due_at(conn, conversation_id: int, priority: str):
    """due_at = created_at + sla[new priority] -- caller must have checked that
    first_human_response_at is still NULL (SPEC-09 §3)."""
    conn.execute(
        "UPDATE conversations SET due_at = datetime(created_at, ?) WHERE id = ?",
        (f"+{sla_hours(priority)} hours", conversation_id),
    )


def sweep_sla_breaches(conn) -> int:
    """Lazy overdue sweep (SPEC-09 §3), run on list queries: one sla_breach event
    per ticket, ever (the NOT EXISTS makes re-sweeps no-ops)."""
    rows = conn.execute(
        """
        SELECT c.id, c.due_at, COALESCE(c.priority, 'P3') AS priority
        FROM conversations c
        WHERE c.due_at IS NOT NULL
          AND c.due_at < datetime('now')
          AND c.first_human_response_at IS NULL
          AND c.status NOT IN ('resolved', 'closed')
          AND NOT EXISTS (SELECT 1 FROM ticket_events e
                          WHERE e.conversation_id = c.id AND e.event = 'sla_breach')
        """
    ).fetchall()
    for r in rows:
        add_event(conn, r["id"], "system", "sla_breach",
                  {"due_at": r["due_at"], "priority": r["priority"]})
    return len(rows)


def stamp_first_human_response(conn, conversation_id: int):
    """Idempotent: sets first_human_response_at the FIRST time only (SPEC-09 §1)."""
    conn.execute(
        "UPDATE conversations SET first_human_response_at = datetime('now') "
        "WHERE id = ? AND first_human_response_at IS NULL",
        (conversation_id,),
    )


# SQL fragments shared by the list endpoints so 'overdue' has exactly one
# definition (SPEC-09 §3): now > due_at, no first human response yet, not
# resolved/closed. due_in_seconds is negative once overdue.
OVERDUE_SQL = ("(c.due_at IS NOT NULL AND c.due_at < datetime('now') "
               "AND c.first_human_response_at IS NULL "
               "AND c.status NOT IN ('resolved','closed'))")
DUE_IN_SQL = ("CAST(ROUND((julianday(c.due_at) - julianday('now')) * 86400) AS INTEGER)")
# Queue ordering (SPEC-09 §3): overdue first, then priority, then due_at.
QUEUE_ORDER_SQL = (f"ORDER BY {OVERDUE_SQL} DESC, COALESCE(c.priority,'P3') ASC, "
                   "(c.due_at IS NULL) ASC, c.due_at ASC, c.updated_at DESC")


def is_banned_state(state) -> bool:
    return str(state or "").strip().lower() in _BANNED_STATES


def build_recommendations(question: str, player_id: str | None, context: dict,
                          admin_url: str | None) -> list[dict]:
    """SPEC-09 §4.2 rule table -- staff to-dos keyed on category/context, phrased
    from PLAYER_DATA_MAP §5 with admin deep links. Deterministic, $0."""
    q = question or ""
    sid_label = player_id or "<SID>"
    actions = []
    if PAYMENT_RE.search(q):
        actions.append({
            "key": "payments",
            "text": (f"Verify transactions for {sid_label} (admin → player → Purchases); "
                     "completed-only — if charged-but-missing, restore via grant/giftables."),
            "link": admin_url,
        })
    if (BAN_RE.search(q) or is_banned_state(context.get("account_state"))):
        actions.append({
            "key": "ban",
            "text": ("Read ban remarks in the player's audit log (admin) before replying; "
                     "check report count + device-ban overlap in the ticket context."),
            "link": admin_url,
        })
    if MISSING_ITEM_RE.search(q):
        actions.append({
            "key": "missing_item",
            "text": "Check `owned[]` and `timeLimitedItems` expiry in admin.",
            "link": admin_url,
        })
    if ACCOUNT_LOSS_RE.search(q):
        actions.append({
            "key": "account_loss",
            "text": ("Confirm linked socials; unlinked guests can't be recovered — "
                     "see playbook article."),
            "link": admin_url,
        })
    if not (player_id or "").strip():
        actions.append({
            "key": "unresolved_sid",
            "text": "Ask for SID (helper text available) or run email match.",
            "link": None,
        })
    return actions
