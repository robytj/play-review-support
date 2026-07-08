"""SPEC-10 partner API acceptance (§5): key separation (dashboard key rejected on
partner routes and vice versa, 503 when PARTNER_API_KEY unset), SID-bound reads
only (cross-SID 404), player-safe serialization (fuzz over every response field:
no internal columns), suggestions/notes/events never leak, approved/sent staff
replies only, player-safe status mapping."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import AUTH
from app import config, db

PARTNER_KEY = "partner-test-key"
PAUTH = {"Authorization": f"Bearer {PARTNER_KEY}"}

# every internal column/field that must NEVER serialize on a partner response
INTERNAL_FIELDS = ("assignee", "priority", "due_at", "first_human_response_at",
                   "sla", "player_id", "external_id", "origin", "sid_source",
                   "suggestion", "suggested_answer", "edited_answer", "actor",
                   "detail_json", "context", "note")


@pytest.fixture
def partner(monkeypatch):
    monkeypatch.setattr(config, "PARTNER_API_KEY", PARTNER_KEY)
    from app import partner_api
    test_app = FastAPI()
    test_app.include_router(partner_api.router)
    return TestClient(test_app)


@pytest.fixture
def dash():
    from app import dashboard_api
    test_app = FastAPI()
    test_app.include_router(dashboard_api.router)
    return TestClient(test_app)


def _mk_ticket(sid="EDFXPT5G", public_id="PR-AAAAA", status="escalated",
               question="[shadow chat escalation — reason]\nSID: X | payer tier: ACTIVE"
                        "\n\nIssue: my gems purchase is missing",
               sugg_status="pending"):
    with db.tx() as c:
        cid = c.execute(
            "INSERT INTO conversations (channel, external_id, status, context, player_id, "
            "origin, public_id, priority, assignee) "
            "VALUES ('chat', ?, ?, '{\"internal\": true}', ?, 'live', ?, 'P1', "
            "'roby@taptolearn.com')",
            (f"ext-{public_id}", status, sid, public_id)).lastrowid
        c.execute("INSERT INTO messages (conversation_id, role, text) VALUES (?, 'user', "
                  "'my gems purchase is missing')", (cid,))
        c.execute("INSERT INTO messages (conversation_id, role, text) VALUES (?, 'bot', "
                  "'BOT-TRANSCRIPT holding reply')", (cid,))
        c.execute(
            "INSERT INTO suggestions (conversation_id, source, question, suggested_answer, "
            "edited_answer, status) VALUES (?, 'chat', ?, 'SECRET-DRAFT do not leak', ?, ?)",
            (cid, question,
             "STAFF-REPLY we restored your gems" if sugg_status in ("approved", "sent") else None,
             sugg_status))
    return cid


# -------------------------------------------------------------- key separation --

def test_partner_api_503_when_key_unset(partner, monkeypatch):
    monkeypatch.setattr(config, "PARTNER_API_KEY", "")
    r = partner.get("/api/partner/players/EDFXPT5G/tickets", headers=PAUTH)
    assert r.status_code == 503


def test_key_separation_both_directions(partner, dash, monkeypatch):
    _mk_ticket()
    # dashboard key rejected on partner routes
    assert partner.get("/api/partner/players/EDFXPT5G/tickets",
                       headers=AUTH).status_code == 401
    assert partner.get("/api/partner/players/EDFXPT5G/tickets").status_code == 401
    # partner key rejected on dashboard routes
    assert dash.get("/api/dashboard/tickets", headers=PAUTH).status_code == 401
    # partner key accepted on partner routes
    assert partner.get("/api/partner/players/EDFXPT5G/tickets",
                       headers=PAUTH).status_code == 200


# ------------------------------------------------------------- SID-bound reads --

def test_sid_bound_cross_player_404(partner):
    _mk_ticket(sid="EDFXPT5G", public_id="PR-MINE1")
    _mk_ticket(sid="2S6WGTSK", public_id="PR-OTHER")
    # list: only the caller's SID's tickets
    mine = partner.get("/api/partner/players/EDFXPT5G/tickets", headers=PAUTH).json()
    assert [t["public_id"] for t in mine] == ["PR-MINE1"]
    assert partner.get("/api/partner/players/UNKNOWN1/tickets", headers=PAUTH).json() == []
    # detail: another player's public_id is a 404, indistinguishable from unknown
    assert partner.get("/api/partner/players/EDFXPT5G/tickets/PR-OTHER",
                       headers=PAUTH).status_code == 404
    assert partner.get("/api/partner/players/EDFXPT5G/tickets/PR-NOPE9",
                       headers=PAUTH).status_code == 404
    assert partner.get("/api/partner/players/EDFXPT5G/tickets/PR-MINE1",
                       headers=PAUTH).status_code == 200


# ------------------------------------------------------ player-safe serialization --

def test_list_shape_status_mapping_and_subject(partner):
    _mk_ticket(public_id="PR-OPEN1", status="escalated")            # legacy -> open
    _mk_ticket(public_id="PR-WAIT1", status="waiting_player")
    _mk_ticket(public_id="PR-DONE1", status="resolved")
    rows = {t["public_id"]: t for t in
            partner.get("/api/partner/players/EDFXPT5G/tickets", headers=PAUTH).json()}
    assert set(rows["PR-OPEN1"]) == {"public_id", "created_at", "status", "channel",
                                     "subject", "resolved_at", "has_staff_reply"}
    assert rows["PR-OPEN1"]["status"] == "In progress"
    assert rows["PR-WAIT1"]["status"] == "Waiting for you"
    assert rows["PR-DONE1"]["status"] == "Resolved"
    assert rows["PR-DONE1"]["resolved_at"] is not None
    assert rows["PR-OPEN1"]["resolved_at"] is None
    # subject: the player's issue, not the internal escalation preamble; <= 80 chars
    subj = rows["PR-OPEN1"]["subject"]
    assert subj == "my gems purchase is missing"
    assert "escalation" not in subj and "payer tier" not in subj
    assert rows["PR-OPEN1"]["has_staff_reply"] is False


def test_fuzz_no_internal_fields_in_any_response(partner, dash):
    cid = _mk_ticket(public_id="PR-FUZZ1", sugg_status="approved")
    # add internal artifacts that must never leak
    staff = {**AUTH, "X-Staff-Email": "roby@taptolearn.com"}
    dash.post(f"/api/dashboard/conversations/{cid}/notes",
              json={"text": "INTERNAL-NOTE player is a whale, comp 500 gems"},
              headers=staff)
    dash.patch(f"/api/dashboard/conversations/{cid}", json={"status": "in_progress"},
               headers=staff)

    body = partner.get("/api/partner/players/EDFXPT5G/tickets", headers=PAUTH).text
    detail_r = partner.get("/api/partner/players/EDFXPT5G/tickets/PR-FUZZ1", headers=PAUTH)
    detail = detail_r.text
    for blob in (body, detail):
        for field in INTERNAL_FIELDS:
            assert f'"{field}"' not in blob, field
        assert "INTERNAL-NOTE" not in blob
        assert "SECRET-DRAFT" not in blob                 # unapproved draft text
        assert "roby@taptolearn.com" not in blob          # staff identity
        assert "P1" not in blob
    # keys of every serialized object are the player-safe set only
    d = detail_r.json()
    assert set(d) == {"public_id", "created_at", "status", "channel", "subject",
                      "resolved_at", "thread", "timeline"}
    for m in d["thread"]:
        assert set(m) == {"role", "text", "at"} and m["role"] in ("player", "staff")
    for t in d["timeline"]:
        assert set(t) == {"status", "at"}


def test_thread_approved_or_sent_staff_replies_only(partner):
    _mk_ticket(public_id="PR-PEND1", sugg_status="pending")
    _mk_ticket(public_id="PR-APPR1", sugg_status="approved")

    d = partner.get("/api/partner/players/EDFXPT5G/tickets/PR-PEND1", headers=PAUTH).json()
    roles = [m["role"] for m in d["thread"]]
    assert roles == ["player"]                            # pending draft never leaks

    d = partner.get("/api/partner/players/EDFXPT5G/tickets/PR-APPR1", headers=PAUTH).json()
    staff_msgs = [m for m in d["thread"] if m["role"] == "staff"]
    assert len(staff_msgs) == 1
    assert staff_msgs[0]["text"] == "STAFF-REPLY we restored your gems"
    # bot transcript copies don't serialize either
    assert not any("BOT-TRANSCRIPT" in m["text"] for m in d["thread"])
    # list flags the staff reply
    rows = {t["public_id"]: t for t in
            partner.get("/api/partner/players/EDFXPT5G/tickets", headers=PAUTH).json()}
    assert rows["PR-APPR1"]["has_staff_reply"] is True
    assert rows["PR-PEND1"]["has_staff_reply"] is False


def test_timeline_player_safe_statuses(partner, dash):
    cid = _mk_ticket(public_id="PR-TIME1", status="open")
    staff = {**AUTH, "X-Staff-Email": "roby@taptolearn.com"}
    dash.patch(f"/api/dashboard/conversations/{cid}", json={"status": "in_progress"},
               headers=staff)
    dash.patch(f"/api/dashboard/conversations/{cid}", json={"status": "resolved"},
               headers=staff)
    d = partner.get("/api/partner/players/EDFXPT5G/tickets/PR-TIME1", headers=PAUTH).json()
    assert [t["status"] for t in d["timeline"]] == ["Created", "In progress", "Resolved"]
    assert d["status"] == "Resolved"


def test_tickets_without_public_id_not_listed(partner):
    with db.tx() as c:
        c.execute("INSERT INTO conversations (channel, external_id, status, player_id) "
                  "VALUES ('discord', 'no-pid', 'open', 'EDFXPT5G')")
    assert partner.get("/api/partner/players/EDFXPT5G/tickets", headers=PAUTH).json() == []


def test_list_pagination(partner):
    for i in range(3):
        _mk_ticket(public_id=f"PR-PAGE{i}")
    rows = partner.get("/api/partner/players/EDFXPT5G/tickets?limit=2", headers=PAUTH).json()
    assert len(rows) == 2
    rows2 = partner.get("/api/partner/players/EDFXPT5G/tickets?limit=2&offset=2",
                        headers=PAUTH).json()
    assert len(rows2) == 1


def test_takeover_agent_reply_visible_as_staff_in_partner_thread(partner, client,
                                                                 issue_session, say,
                                                                 known_player):
    """End-to-end: chat escalation -> takeover -> agent reply -> the player sees it
    from the SuperX side as a staff message on their ticket."""
    sid = issue_session()
    out = say(sid, "I want to talk to a real person")
    card = next(m for m in out["messages"] if m["type"] == "escalation_card")
    public_id = card["meta"]["public_id"]

    staff = {**AUTH, "X-Staff-Email": "agent@taptolearn.com"}
    client.post(f"/api/dashboard/chat/sessions/{sid}/takeover", headers=staff)
    client.post(f"/api/dashboard/chat/sessions/{sid}/agent-message",
                json={"text": "Hi! I checked and your gems are back."}, headers=staff)

    d = partner.get(f"/api/partner/players/EDFXPT5G/tickets/{public_id}",
                    headers=PAUTH).json()
    staff_texts = [m["text"] for m in d["thread"] if m["role"] == "staff"]
    assert "Hi! I checked and your gems are back." in staff_texts
    assert "agent@taptolearn.com" not in json.dumps(d)     # identity stays internal
