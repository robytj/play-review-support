"""Live human takeover + end-of-conversation star rating (chat).

Covers: takeover flow (409 on terminal, system note, ticket event), player
message while human-controlled (stored, NO bot reply, no budgets), the polling
endpoint, release, agent-message -> staff reply on the linked conversation
(role='human', tone-visible), idle-expiry hold while human-controlled, session
list live/controller fields, and every rating parse/skip path.
"""
import json

from conftest import AUTH
from app import chat_engine, db, router, tone

STAFF = {**AUTH, "X-Staff-Email": "roby@taptolearn.com"}


def _row(sid):
    return db.get_conn().execute("SELECT * FROM chat_sessions WHERE id=?", (sid,)).fetchone()


def _chat_msgs(sid):
    return [dict(r) for r in db.get_conn().execute(
        "SELECT * FROM chat_messages WHERE session_id=? ORDER BY id", (sid,)).fetchall()]


def _events(cid):
    return [dict(r) for r in db.get_conn().execute(
        "SELECT * FROM ticket_events WHERE conversation_id=? ORDER BY id", (cid,)).fetchall()]


def _takeover(client, sid, headers=STAFF):
    return client.post(f"/api/dashboard/chat/sessions/{sid}/takeover", headers=headers)


# ------------------------------------------------------------------- takeover --

def test_takeover_flow_and_player_message_stored_without_reply(client, start, say, known_player):
    sid = start()["session_id"]
    say(sid, "PrimeRush.gg (LatAm)")

    r = _takeover(client, sid)
    assert r.status_code == 200, r.text
    data = r.json()
    s = data["session"]
    assert s["controller"] == "human"
    assert s["taken_over_by"] == "roby@taptolearn.com" and s["taken_over_at"]
    assert "meta_json" not in s
    # player-visible system note is the last message of the returned tail
    note = data["messages"][-1]
    assert note["role"] == "system"
    assert note["content"] == chat_engine.HUMAN_TAKEOVER_NOTE

    # player message while human-controlled: stored, no pipeline, no bot reply
    before = _row(sid)["msg_count"]
    out = say(sid, "hello?? my SID is EDFXPT5G")
    assert out["controller"] == "human"
    assert out["messages"] == []                       # nothing echoed, no bot reply
    msgs = _chat_msgs(sid)
    assert msgs[-1]["role"] == "user" and "EDFXPT5G" in msgs[-1]["content"]
    row = _row(sid)
    assert row["msg_count"] == before                  # budget NOT consumed
    assert row["state"] == "ASK_SID"                   # state machine untouched


def test_takeover_terminal_session_is_409(client, start):
    sid = start()["session_id"]
    client.post(f"/api/dashboard/chat/sessions/{sid}/end",
                json={"reason": "manual"}, headers=AUTH)
    r = _takeover(client, sid)
    assert r.status_code == 409
    assert r.json() == {"error": "session_ended", "state": "ENDED"}


def test_agent_message_and_release(client, start, say):
    sid = start()["session_id"]
    # agent message before takeover -> 409
    r = client.post(f"/api/dashboard/chat/sessions/{sid}/agent-message",
                    json={"text": "hi"}, headers=STAFF)
    assert r.status_code == 409
    _takeover(client, sid)

    r = client.post(f"/api/dashboard/chat/sessions/{sid}/agent-message",
                    json={"text": "Hi, this is Roby from support!"}, headers=STAFF)
    assert r.status_code == 200
    data = r.json()
    assert data["controller"] == "human"
    m = data["messages"][0]
    assert m["role"] == "agent" and m["meta"]["staff"] == "roby@taptolearn.com"
    assert m["content"] == "Hi, this is Roby from support!"

    # release hands back to the bot with a player-visible note
    r = client.post(f"/api/dashboard/chat/sessions/{sid}/release", headers=STAFF)
    assert r.status_code == 200
    assert r.json()["session"]["controller"] == "bot"
    assert r.json()["messages"][-1]["content"] == chat_engine.BOT_RELEASE_NOTE
    # double release -> 409
    assert client.post(f"/api/dashboard/chat/sessions/{sid}/release",
                       headers=STAFF).status_code == 409
    # bot pipeline resumes after release
    out = say(sid, "PrimeRush.gg (LatAm)")
    assert out["state"] == "ASK_SID" and out["controller"] == "bot"


def test_agent_message_empty_or_unknown_session(client, start):
    sid = start()["session_id"]
    _takeover(client, sid)
    assert client.post(f"/api/dashboard/chat/sessions/{sid}/agent-message",
                       json={"text": "  "}, headers=STAFF).status_code == 400
    assert client.post("/api/dashboard/chat/sessions/99999/agent-message",
                       json={"text": "x"}, headers=STAFF).status_code == 404
    assert client.post("/api/dashboard/chat/sessions/99999/takeover",
                       headers=STAFF).status_code == 404


def test_polling_endpoint_incremental(client, start, say):
    sid = start()["session_id"]
    r = client.get(f"/api/dashboard/chat/sessions/{sid}/messages", headers=AUTH)
    assert r.status_code == 200
    first = r.json()
    assert first["controller"] == "bot" and len(first["messages"]) == 1  # greeting
    last_id = first["messages"][-1]["id"]

    _takeover(client, sid)
    client.post(f"/api/dashboard/chat/sessions/{sid}/agent-message",
                json={"text": "hello from a human"}, headers=STAFF)
    r = client.get(f"/api/dashboard/chat/sessions/{sid}/messages?after_id={last_id}",
                   headers=AUTH)
    data = r.json()
    assert data["controller"] == "human"
    assert [m["role"] for m in data["messages"]] == ["system", "agent"]
    # nothing new after the newest id -> empty
    newest = data["messages"][-1]["id"]
    r = client.get(f"/api/dashboard/chat/sessions/{sid}/messages?after_id={newest}",
                   headers=AUTH)
    assert r.json()["messages"] == []


def test_takeover_and_events_on_escalated_conversation(client, issue_session, say, known_player):
    sid = issue_session()
    say(sid, "I want to talk to a real person")            # escalates -> RATING
    convo_id = _row(sid)["escalated_conversation_id"]
    assert convo_id

    _takeover(client, sid)
    r = client.post(f"/api/dashboard/chat/sessions/{sid}/agent-message",
                    json={"text": "Hey, real human here — checked your account."},
                    headers=STAFF)
    assert r.status_code == 200
    client.post(f"/api/dashboard/chat/sessions/{sid}/release", headers=STAFF)

    evs = [e["event"] for e in _events(convo_id)]
    assert "takeover" in evs and "release" in evs
    take = next(e for e in _events(convo_id) if e["event"] == "takeover")
    assert take["actor"] == "roby@taptolearn.com"
    assert json.loads(take["detail_json"])["chat_session_id"] == sid

    # the agent reply landed on the linked conversation as a staff reply
    staff_msgs = db.get_conn().execute(
        "SELECT * FROM messages WHERE conversation_id=? AND role='human'",
        (convo_id,)).fetchall()
    assert len(staff_msgs) == 1
    assert staff_msgs[0]["text"] == "Hey, real human here — checked your account."
    assert staff_msgs[0]["author_name"] == "roby@taptolearn.com"
    convo = db.get_conn().execute("SELECT * FROM conversations WHERE id=?",
                                  (convo_id,)).fetchone()
    assert convo["first_human_response_at"] is not None


def test_human_hold_skips_idle_expiry_then_expires_after_grace(client, start):
    sid = start()["session_id"]
    _takeover(client, sid)
    with db.tx() as c:
        c.execute("UPDATE chat_sessions SET last_activity_at=datetime('now','-11 minutes') "
                  "WHERE id=?", (sid,))
    r = client.get(f"/api/dashboard/chat/sessions/{sid}/messages", headers=AUTH)
    assert r.json()["state"] == "ASK_GAME"                 # held open by the human
    # list sweep also honors the hold
    client.get("/api/dashboard/chat/sessions", headers=AUTH)
    assert _row(sid)["state"] == "ASK_GAME"

    # takeover older than the 30-min grace -> normal expiry resumes
    with db.tx() as c:
        c.execute("UPDATE chat_sessions SET taken_over_at=datetime('now','-31 minutes') "
                  "WHERE id=?", (sid,))
    r = client.get(f"/api/dashboard/chat/sessions/{sid}/messages", headers=AUTH)
    assert r.json()["state"] == "EXPIRED"


def test_session_list_has_controller_and_live_fields(client, start):
    live_sid = start()["session_id"]
    stale_sid = start()["session_id"]
    with db.tx() as c:
        c.execute("UPDATE chat_sessions SET last_activity_at=datetime('now','-5 minutes') "
                  "WHERE id=?", (stale_sid,))
    _takeover(client, live_sid)
    rows = {r["id"]: r for r in
            client.get("/api/dashboard/chat/sessions", headers=AUTH).json()["sessions"]}
    assert rows[live_sid]["live"] is True
    assert rows[live_sid]["controller"] == "human"
    assert rows[live_sid]["taken_over_by"] == "roby@taptolearn.com"
    assert rows[stale_sid]["live"] is False                # idle > 120s
    assert rows[stale_sid]["controller"] == "bot" and rows[stale_sid]["rating"] is None


# ---------------------------------------------------------------- star rating --

def test_rating_after_csat_yes_paths(start, say, known_player, monkeypatch):
    monkeypatch.setattr(router, "suggest",
                        lambda q: {"tier": 2, "text": "Try reinstalling.", "chunks": []})

    def resolved_session():
        s = start()
        sid = s["session_id"]
        say(sid, "PrimeRush.gg (LatAm)")
        say(sid, "EDFXPT5G")
        say(sid, "Yes")
        say(sid, "my game crashes")
        out = say(sid, "Yes")                              # CSAT yes -> RATING
        assert out["state"] == "RATING"
        assert any(m["type"] == "rating" for m in out["messages"])
        return sid

    # "4 stars" parses
    sid = resolved_session()
    out = say(sid, "4 stars")
    assert out["state"] == "RESOLVED"
    assert _row(sid)["rating"] == 4 and _row(sid)["end_reason"] == "resolved"
    texts = [m["content"] for m in out["messages"]]
    assert chat_engine.RATING_THANKS in texts
    assert chat_engine.RESOLVED_GOODBYE in texts

    # non-rating answer -> close without rating, no nag
    sid = resolved_session()
    out = say(sid, "thanks, bye!")
    assert out["state"] == "RESOLVED"
    assert _row(sid)["rating"] is None
    assert chat_engine.RATING_THANKS not in [m["content"] for m in out["messages"]]

    # bare digit and "5/5" both parse; out-of-range does not
    assert chat_engine._parse_rating("5") == 5
    assert chat_engine._parse_rating(" 3/5 ") == 3
    assert chat_engine._parse_rating("1 star") == 1
    assert chat_engine._parse_rating("6") is None
    assert chat_engine._parse_rating("0") is None
    assert chat_engine._parse_rating("five") is None


def test_rating_after_escalation_writes_ticket_event(issue_session, say, known_player):
    sid = issue_session()
    out = say(sid, "I want to talk to a real person")
    assert out["state"] == "RATING"
    convo_id = _row(sid)["escalated_conversation_id"]

    out = say(sid, "2")
    assert out["state"] == "ESCALATED"
    row = _row(sid)
    assert row["rating"] == 2 and row["end_reason"] == "escalated" and row["ended_at"]

    rating_evs = [e for e in _events(convo_id) if e["event"] == "rating"]
    assert len(rating_evs) == 1
    assert rating_evs[0]["actor"] == "player"
    assert json.loads(rating_evs[0]["detail_json"]) == {"rating": 2, "chat_session_id": sid}


def test_manual_end_and_timeout_skip_rating(client, start, say, known_player):
    # manual end: straight to ENDED, no rating ask ever
    sid = start()["session_id"]
    r = client.post(f"/api/dashboard/chat/sessions/{sid}/end",
                    json={"reason": "manual"}, headers=AUTH)
    data = r.json()
    assert data["state"] == "ENDED"
    assert not any(m["type"] == "rating" for m in data["messages"])

    # idle timeout while RATING pending: expires without a stored rating
    sid2 = start()["session_id"]
    with db.tx() as c:
        c.execute("UPDATE chat_sessions SET last_activity_at=datetime('now','-11 minutes') "
                  "WHERE id=?", (sid2,))
    r = client.get(f"/api/dashboard/chat/sessions/{sid2}", headers=AUTH)
    assert r.json()["session"]["state"] == "EXPIRED"
    assert _row(sid2)["rating"] is None


def test_messages_response_always_includes_controller(start, say):
    s = start()
    sid = s["session_id"]
    out = say(sid, "PrimeRush.gg (LatAm)")
    assert out["controller"] == "bot"                      # frontend polling contract
