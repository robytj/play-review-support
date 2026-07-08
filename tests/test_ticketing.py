"""SPEC-09 ticketing system: migration idempotency, audit events (actor from
X-Staff-Email), status workflow (closed staff-only, closed_at), priority/SLA
(due_at recompute rules, overdue + one sla_breach event, queue ordering),
notes, recommendations (rule table + embeddings degradation), inert outreach,
chat-escalation created/escalated events, and the approve->first_human_response
stamping. Everything offline, on the conftest temp DB."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import AUTH
from app import config, db, embeddings, ticketing

STAFF = {**AUTH, "X-Staff-Email": "roby@taptolearn.com"}


@pytest.fixture
def dash():
    from app import dashboard_api
    test_app = FastAPI()
    test_app.include_router(dashboard_api.router)
    return TestClient(test_app)


def _mk_convo(status="open", channel="discord", player_id=None, priority=None,
              due_at_offset_hours=None, context="", question=None, origin="live"):
    """Raw insert (like pre-SPEC-09 rows): no events, no priority unless given."""
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO conversations (channel, external_id, status, context, player_id, origin) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (channel, f"ext-{status}", status, context, player_id, origin))
        cid = cur.lastrowid
        if priority:
            c.execute("UPDATE conversations SET priority = ? WHERE id = ?", (priority, cid))
        if due_at_offset_hours is not None:
            c.execute("UPDATE conversations SET due_at = datetime('now', ?) WHERE id = ?",
                      (f"{due_at_offset_hours:+d} hours", cid))
        if question is not None:
            c.execute(
                "INSERT INTO suggestions (conversation_id, source, question, suggested_answer) "
                "VALUES (?, 'discord', ?, 'suggested')", (cid, question))
    return cid


def _events(cid):
    return [dict(r) for r in db.get_conn().execute(
        "SELECT * FROM ticket_events WHERE conversation_id = ? ORDER BY id", (cid,)).fetchall()]


# ------------------------------------------------------------------- migration --

def test_migration_idempotent_and_null_priority_renders_p3(dash):
    db.init_db()
    db.init_db()  # second run must be a clean no-op
    cols = {r["name"] for r in db.get_conn().execute(
        "PRAGMA table_info(conversations)").fetchall()}
    assert {"priority", "assignee", "due_at", "first_human_response_at", "closed_at"} <= cols
    assert db.get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ticket_events'").fetchone()

    cid = _mk_convo()  # legacy-style row: NULL priority, no events
    r = dash.get("/api/dashboard/tickets", headers=AUTH)
    assert r.status_code == 200
    t = next(t for t in r.json()["tickets"] if t["id"] == cid)
    assert t["priority"] == "P3" and t["ticket_status"] == "open"
    assert t["due_at"] is None and t["overdue"] is False
    assert _events(cid) == []  # nothing backfilled (acceptance #1)


def test_legacy_status_display_mapping(dash):
    esc = _mk_convo(status="escalated")
    paused = _mk_convo(status="paused")
    tickets = {t["id"]: t for t in dash.get("/api/dashboard/tickets", headers=AUTH).json()["tickets"]}
    assert tickets[esc]["ticket_status"] == "open"
    assert tickets[paused]["ticket_status"] == "waiting_player"
    # display-status filter matches the legacy raw value too
    ids = [t["id"] for t in dash.get("/api/dashboard/tickets?status=open",
                                     headers=AUTH).json()["tickets"]]
    assert esc in ids and paused not in ids


# ------------------------------------------------------------ PATCH + audit log --

def test_patch_logs_one_event_per_mutation_with_actor(dash):
    cid = _mk_convo()
    r = dash.patch(f"/api/dashboard/conversations/{cid}",
                   json={"status": "in_progress", "priority": "P1",
                         "assignee": "roby@taptolearn.com"}, headers=STAFF)
    assert r.status_code == 200, r.text
    evs = _events(cid)
    assert [e["event"] for e in evs] == ["status", "priority", "assignee"]
    assert all(e["actor"] == "roby@taptolearn.com" for e in evs)
    detail = json.loads(evs[1]["detail_json"])
    assert detail == {"from": "P3", "to": "P1", "due_at_recomputed": True}
    t = r.json()["ticket"]
    assert t["priority"] == "P1" and t["assignee"] == "roby@taptolearn.com"
    assert t["ticket_status"] == "in_progress"

    # no-op PATCH (same values) writes no events
    dash.patch(f"/api/dashboard/conversations/{cid}",
               json={"status": "in_progress"}, headers=STAFF)
    assert len(_events(cid)) == 3


def test_closed_is_staff_only_and_sets_closed_at(dash):
    cid = _mk_convo()
    r = dash.patch(f"/api/dashboard/conversations/{cid}", json={"status": "closed"},
                   headers=AUTH)  # no X-Staff-Email -> actor 'system'
    assert r.status_code == 403
    r = dash.patch(f"/api/dashboard/conversations/{cid}", json={"status": "closed"},
                   headers=STAFF)
    assert r.status_code == 200
    row = db.get_conn().execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["status"] == "closed" and row["closed_at"]
    # reopening clears closed_at
    dash.patch(f"/api/dashboard/conversations/{cid}", json={"status": "open"}, headers=STAFF)
    row = db.get_conn().execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["closed_at"] is None


def test_patch_validation(dash):
    cid = _mk_convo()
    assert dash.patch(f"/api/dashboard/conversations/{cid}", json={"status": "nope"},
                      headers=STAFF).status_code == 400
    assert dash.patch(f"/api/dashboard/conversations/{cid}", json={"priority": "P9"},
                      headers=STAFF).status_code == 400
    assert dash.patch(f"/api/dashboard/conversations/{cid}", json={"bogus": 1},
                      headers=STAFF).status_code == 400
    assert dash.patch("/api/dashboard/conversations/999999", json={"priority": "P1"},
                      headers=STAFF).status_code == 404


# -------------------------------------------------------------------- SLA rules --

def test_priority_change_recomputes_due_at_only_before_first_response(dash):
    cid = _mk_convo()
    dash.patch(f"/api/dashboard/conversations/{cid}", json={"priority": "P1"}, headers=STAFF)
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    due_p1 = row["due_at"]
    assert due_p1 is not None
    # P1 due = created_at + 4h (config.yaml sla block)
    expect = conn.execute("SELECT datetime(?, '+4 hours') AS t", (row["created_at"],)).fetchone()["t"]
    assert due_p1 == expect

    # after a first human response, priority changes must NOT move due_at
    with db.tx() as c:
        ticketing.stamp_first_human_response(c, cid)
    dash.patch(f"/api/dashboard/conversations/{cid}", json={"priority": "P4"}, headers=STAFF)
    row = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["due_at"] == due_p1
    detail = json.loads(_events(cid)[-1]["detail_json"])
    assert "due_at_recomputed" not in detail


def test_overdue_sweep_writes_one_sla_breach_event_ever(dash):
    over = _mk_convo(due_at_offset_hours=-2)          # past due, no response
    fine = _mk_convo(due_at_offset_hours=+2)          # still in SLA
    resolved = _mk_convo(status="resolved", due_at_offset_hours=-2)
    responded = _mk_convo(due_at_offset_hours=-2)
    with db.tx() as c:
        ticketing.stamp_first_human_response(c, responded)

    tickets = {t["id"]: t for t in dash.get("/api/dashboard/tickets", headers=AUTH).json()["tickets"]}
    assert tickets[over]["overdue"] is True and tickets[over]["due_in_seconds"] < 0
    assert tickets[fine]["overdue"] is False
    assert tickets[resolved]["overdue"] is False
    assert tickets[responded]["overdue"] is False

    assert [e["event"] for e in _events(over)] == ["sla_breach"]
    assert _events(fine) == [] and _events(resolved) == [] and _events(responded) == []
    dash.get("/api/dashboard/tickets", headers=AUTH)  # re-sweep
    assert len([e for e in _events(over) if e["event"] == "sla_breach"]) == 1


def test_queue_ordering_overdue_then_priority_then_due(dash):
    p3_late = _mk_convo(priority="P3", due_at_offset_hours=-1)    # overdue
    p1_soon = _mk_convo(priority="P1", due_at_offset_hours=1)
    p2_soon = _mk_convo(priority="P2", due_at_offset_hours=1)
    p1_later = _mk_convo(priority="P1", due_at_offset_hours=5)
    ids = [t["id"] for t in dash.get("/api/dashboard/tickets", headers=AUTH).json()["tickets"]]
    assert ids.index(p3_late) < ids.index(p1_soon)                 # overdue first
    assert ids.index(p1_soon) < ids.index(p1_later)                # then due_at
    assert ids.index(p1_later) < ids.index(p2_soon)                # then priority


def test_tickets_filters(dash):
    a = _mk_convo(channel="chat", priority="P1", player_id="EDFXPT5G")
    b = _mk_convo(channel="discord", priority="P2")
    dash.patch(f"/api/dashboard/conversations/{a}", json={"assignee": "roby@taptolearn.com"},
               headers=STAFF)
    r = dash.get("/api/dashboard/tickets?priority=P1&channel=chat&assignee=roby@taptolearn.com",
                 headers=AUTH).json()
    assert [t["id"] for t in r["tickets"]] == [a]
    r = dash.get("/api/dashboard/tickets?assignee=unassigned", headers=AUTH).json()
    assert b in [t["id"] for t in r["tickets"]] and a not in [t["id"] for t in r["tickets"]]
    r = dash.get("/api/dashboard/tickets?q=EDFXPT5G", headers=AUTH).json()
    assert [t["id"] for t in r["tickets"]] == [a]


# ----------------------------------------------------------------- notes/events --

def test_note_is_an_event_and_notify_stamps_first_response(dash):
    cid = _mk_convo()
    assert dash.post(f"/api/dashboard/conversations/{cid}/notes", json={"text": "  "},
                     headers=STAFF).status_code == 400
    dash.post(f"/api/dashboard/conversations/{cid}/notes",
              json={"text": "checked admin, purchases fine"}, headers=STAFF)
    row = db.get_conn().execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["first_human_response_at"] is None      # plain note: no stamp

    dash.post(f"/api/dashboard/conversations/{cid}/notes",
              json={"text": "replied to the player", "notify": True}, headers=STAFF)
    row = db.get_conn().execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["first_human_response_at"] is not None

    r = dash.get(f"/api/dashboard/conversations/{cid}/events", headers=AUTH).json()
    assert [e["event"] for e in r["events"]] == ["note", "note"]
    assert r["events"][0]["actor"] == "roby@taptolearn.com"
    assert r["events"][0]["detail"] == {"text": "checked admin, purchases fine", "notify": False}


def test_approve_stamps_first_response_and_reply_sent_event(dash):
    cid = _mk_convo(question="where are my gems")
    sug = db.get_conn().execute(
        "SELECT id FROM suggestions WHERE conversation_id = ?", (cid,)).fetchone()["id"]
    r = dash.post(f"/api/dashboard/suggestions/{sug}/approve", headers=STAFF)
    assert r.status_code == 200
    row = db.get_conn().execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["first_human_response_at"] is not None
    evs = _events(cid)
    assert [e["event"] for e in evs] == ["reply_sent"]
    assert evs[0]["actor"] == "roby@taptolearn.com"
    assert json.loads(evs[0]["detail_json"])["via"] == "approve"


# ------------------------------------------------------------- recommendations --

def test_recommendations_rule_actions_degrade_without_embeddings(dash):
    # conftest pins embeddings to the fallback -> KB matches must be [] (never 500)
    pay = _mk_convo(player_id="EDFXPT5G",
                    question="I was charged for a gem purchase but got nothing, refund?")
    r = dash.get(f"/api/dashboard/conversations/{pay}/recommendations", headers=AUTH)
    assert r.status_code == 200
    j = r.json()
    assert j["kb_matches"] == [] and j["playbook"] is None
    assert j["embeddings_available"] is False
    keys = [a["key"] for a in j["actions"]]
    assert "payments" in keys and "unresolved_sid" not in keys
    payments = next(a for a in j["actions"] if a["key"] == "payments")
    assert "EDFXPT5G" in payments["text"]
    assert payments["link"] == "https://admin.brx.indusgame.com/player/EDFXPT5G"

    ban = _mk_convo(question="why was I banned? I want to appeal",
                    context=json.dumps({"account_state": "Locked"}))
    j = dash.get(f"/api/dashboard/conversations/{ban}/recommendations", headers=AUTH).json()
    keys = [a["key"] for a in j["actions"]]
    assert "ban" in keys and "unresolved_sid" in keys    # no SID resolved

    item = _mk_convo(player_id="CS9DNY34", question="my weapon skin disappeared yesterday")
    j = dash.get(f"/api/dashboard/conversations/{item}/recommendations", headers=AUTH).json()
    assert "missing_item" in [a["key"] for a in j["actions"]]

    guest = _mk_convo(question="I lost my account when I changed phone, it was a guest account")
    j = dash.get(f"/api/dashboard/conversations/{guest}/recommendations", headers=AUTH).json()
    assert "account_loss" in [a["key"] for a in j["actions"]]


def test_recommendations_kb_matches_with_embeddings(dash, monkeypatch):
    from app import vectorstore
    monkeypatch.setattr(embeddings, "is_using_fallback", lambda: False)
    monkeypatch.setattr(embeddings, "embed", embeddings._hash_embed)
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO kb_articles (title, symptom, answer, tags, status) "
            "VALUES ('Missing purchase', 'charged but item missing', 'Check admin.', "
            "'payments,playbook', 'published')")
        art = cur.lastrowid
    vectorstore.upsert("kb_articles", art, embeddings._hash_embed("charged but item missing"))
    cid = _mk_convo(player_id="EDFXPT5G", question="charged but item missing")
    j = dash.get(f"/api/dashboard/conversations/{cid}/recommendations", headers=AUTH).json()
    assert j["embeddings_available"] is True
    assert [m["id"] for m in j["kb_matches"]] == [art]
    assert j["playbook"] and j["playbook"]["id"] == art and "answer" in j["playbook"]


# ------------------------------------------------------------------- outreach --

def test_outreach_refuses_and_logs_event(dash):
    cid = _mk_convo(player_id="EDFXPT5G")
    body = "Hi! We restored your missing crate — check your in-game inbox. " * 4
    r = dash.post(f"/api/dashboard/conversations/{cid}/outreach/inbox",
                  json={"title": "Purchase restored", "body": body}, headers=STAFF)
    assert r.status_code == 403
    assert "outreach_enabled is OFF" in r.json()["detail"]
    evs = _events(cid)
    assert [e["event"] for e in evs] == ["outreach_inbox"]
    d = json.loads(evs[0]["detail_json"])
    assert d["sent"] is False and d["sid"] == "EDFXPT5G"
    assert len(d["body_preview"]) <= 80 and body.startswith(d["body_preview"])
    assert evs[0]["actor"] == "roby@taptolearn.com"


def test_outreach_still_refuses_with_toggle_on_but_no_env(dash, monkeypatch):
    monkeypatch.setattr(config, "OUTREACH_ENABLED", True)
    cid = _mk_convo(player_id="EDFXPT5G")
    r = dash.post(f"/api/dashboard/conversations/{cid}/outreach/inbox",
                  json={"title": "t", "body": "b"}, headers=STAFF)
    assert r.status_code == 403 and "INDUS_API" in r.json()["detail"]
    # attempt still audited
    assert [e["event"] for e in _events(cid)] == ["outreach_inbox"]


def test_outreach_status_and_guards(dash):
    st = dash.get("/api/dashboard/outreach/status", headers=AUTH).json()
    assert st["inbox_available"] is False and st["push_available"] is False
    assert st["enabled"] is False and st["reason"]
    cid = _mk_convo()   # no SID
    r = dash.post(f"/api/dashboard/conversations/{cid}/outreach/inbox",
                  json={"title": "t", "body": "b"}, headers=STAFF)
    assert r.status_code == 428
    r = dash.post(f"/api/dashboard/conversations/{cid}/outreach/inbox",
                  json={"title": "", "body": ""}, headers=STAFF)
    assert r.status_code == 400


# ------------------------------------------------- chat escalation audit events --

def test_chat_escalation_writes_created_and_escalated_events(issue_session, say, known_player):
    sid = issue_session()
    out = say(sid, "I want to talk to a real person")
    assert out["state"] == "RATING"       # star-rating ask follows the card
    card = next(m for m in out["messages"] if m["type"] == "escalation_card")
    cid = card["meta"]["conversation_id"]

    evs = _events(cid)
    assert [e["event"] for e in evs] == ["created", "escalated"]
    assert all(e["actor"] == "bot" for e in evs)
    created = json.loads(evs[0]["detail_json"])
    escalated = json.loads(evs[1]["detail_json"])
    assert created["chat_session_id"] == sid and created["public_id"] == card["meta"]["public_id"]
    assert escalated["reason"] == "player asked for a human"

    # ACTIVE payer -> auto-P1 (overrides the purchase-context P2 default) with a
    # 4h SLA from creation, and the created event logs the reason
    assert created["reason"] == "payer auto-P1" and created["payer_tier"] == "ACTIVE"
    row = db.get_conn().execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["priority"] == "P1"
    expect = db.get_conn().execute(
        "SELECT datetime(?, '+4 hours') AS t", (row["created_at"],)).fetchone()["t"]
    assert row["due_at"] == expect


def test_resolve_endpoint_logs_status_event(dash):
    cid = _mk_convo()
    dash.post(f"/api/dashboard/conversations/{cid}/resolve", headers=STAFF)
    evs = _events(cid)
    assert [e["event"] for e in evs] == ["status"]
    assert json.loads(evs[0]["detail_json"]) == {"from": "open", "to": "resolved"}


def test_suggestions_list_carries_ticketing_fields(dash):
    cid = _mk_convo(priority="P2", question="refund please", due_at_offset_hours=5)
    r = dash.get("/api/dashboard/suggestions", headers=AUTH).json()
    row = next(x for x in r if x["conversation_id"] == cid)
    assert row["priority"] == "P2" and row["ticket_status"] == "open"
    assert row["overdue"] is False and row["due_in_seconds"] > 0
    assert row["status"] == "pending"        # suggestion status untouched (existing shape)


def test_settings_expose_sla_and_outreach(dash):
    j = dash.get("/api/dashboard/settings", headers=AUTH).json()
    assert j["sla_hours"] == {"P1": 4, "P2": 12, "P3": 24, "P4": 72}
    assert j["outreach_enabled"] is False


# --------------------------------------------------------------- payer auto-P1 --

def test_default_priority_payer_override_rules():
    # payer overrides everything, any non-NONE tier counts
    for tier in ("ACTIVE", "DORMANT", "LAPSED", "active"):
        assert ticketing.default_priority("hello", payer_tier=tier) == "P1"
    assert ticketing.default_priority("refund please", payer_tier="ACTIVE") == "P1"
    assert ticketing.default_priority("x", has_ban_context=True, payer_tier="LAPSED") == "P1"
    # non-payers keep the SPEC-09 defaults
    assert ticketing.default_priority("refund please", payer_tier="NONE") == "P2"
    assert ticketing.default_priority("hello", payer_tier=None) == "P3"
    assert ticketing.default_priority("hello", payer_tier="") == "P3"


def test_get_or_create_conversation_payer_auto_p1(monkeypatch):
    from app import player_context, router
    from conftest import make_ctx

    monkeypatch.setattr(player_context, "get_player_context",
                        lambda s: make_ctx() if (s or "").upper() == "EDFXPT5G" else None)
    cid = router.get_or_create_conversation("discord", "chan-payer", player_id="EDFXPT5G")
    row = db.get_conn().execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["priority"] == "P1"
    created = json.loads(_events(cid)[0]["detail_json"])
    assert created["priority"] == "P1" and created["reason"] == "payer auto-P1"
    assert created["payer_tier"] == "ACTIVE"

    # unknown SID -> normal default, no reason logged
    cid2 = router.get_or_create_conversation("discord", "chan-nopayer", player_id="ZZZZ9999")
    row2 = db.get_conn().execute("SELECT * FROM conversations WHERE id = ?", (cid2,)).fetchone()
    assert row2["priority"] == "P3"
    assert "reason" not in json.loads(_events(cid2)[0]["detail_json"])

    # no SID at all -> lookup skipped entirely
    calls = []
    monkeypatch.setattr(player_context, "get_player_context",
                        lambda s: calls.append(s) or None)
    cid3 = router.get_or_create_conversation("discord", "chan-nosid")
    assert calls == []
    assert db.get_conn().execute("SELECT priority FROM conversations WHERE id = ?",
                                 (cid3,)).fetchone()["priority"] == "P3"


def test_get_or_create_conversation_degrades_when_mongo_down(monkeypatch):
    from app import player_context, router
    monkeypatch.setattr(player_context, "get_player_context",
                        lambda s: (_ for _ in ()).throw(RuntimeError("mongo down")))
    cid = router.get_or_create_conversation("discord", "chan-down", player_id="EDFXPT5G")
    row = db.get_conn().execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["priority"] == "P3"          # degraded: no override, no crash


def test_non_payer_chat_escalation_keeps_p2_default(issue_session, say, monkeypatch):
    from app import player_context
    from conftest import make_ctx
    ctx = make_ctx(payer_tier="NONE", supporter_band="NONE",
                   transactions={"real_money_count": 0, "refunded_count": 0,
                                 "first_purchase": None, "last_purchase": None,
                                 "payment_systems": [], "recent": [], "scanned": 0})
    monkeypatch.setattr(player_context, "get_player_context",
                        lambda s: ctx if (s or "").strip().upper() == ctx.sid else None)
    sid = issue_session()
    out = say(sid, "I need a refund, please get me a human")
    card = next(m for m in out["messages"] if m["type"] == "escalation_card")
    cid = card["meta"]["conversation_id"]
    row = db.get_conn().execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
    assert row["priority"] == "P2"          # keyword P2, no payer override
    assert "reason" not in json.loads(_events(cid)[0]["detail_json"])


# ------------------------------------------------- recommendations >= 80% only --

def test_recommendations_filter_below_min_similarity(dash, monkeypatch):
    from app import vectorstore
    monkeypatch.setattr(embeddings, "is_using_fallback", lambda: False)
    monkeypatch.setattr(embeddings, "embed", lambda t: [0.0])
    with db.tx() as c:
        hi = c.execute("INSERT INTO kb_articles (title, symptom, answer, tags, status) "
                       "VALUES ('Strong match', 's', 'a', '', 'published')").lastrowid
        lo = c.execute("INSERT INTO kb_articles (title, symptom, answer, tags, status) "
                       "VALUES ('Weak match', 's', 'a', '', 'published')").lastrowid
    monkeypatch.setattr(vectorstore, "search",
                        lambda table, vec, top_k=3, where=None: [(hi, 0.91), (lo, 0.62)])
    cid = _mk_convo(player_id="EDFXPT5G", question="anything")
    j = dash.get(f"/api/dashboard/conversations/{cid}/recommendations", headers=AUTH).json()
    assert j["min_similarity"] == 0.8
    assert [m["id"] for m in j["kb_matches"]] == [hi]      # 0.62 filtered out
    assert j["kb_matches"][0]["similarity"] == 0.91        # raw similarity for the UI %
    assert "payments" not in [a["key"] for a in j["actions"]]  # rule actions untouched

    # hot-readable: config change applies without restart
    monkeypatch.setattr(config, "RECOMMENDATIONS_MIN_SIMILARITY", 0.5)
    j = dash.get(f"/api/dashboard/conversations/{cid}/recommendations", headers=AUTH).json()
    assert [m["id"] for m in j["kb_matches"]] == [hi, lo]
