"""Route-level contract tests for /api/dashboard/chat/* (SPEC-08 §4): auth, the
chat_enabled kill switch, response shapes, image validation, and lifecycle."""
import pytest

from conftest import AUTH
from app import config, db, llm

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def _upload(client, session_id, body=PNG, name="shot.png", mime="image/png"):
    return client.post(f"/api/dashboard/chat/sessions/{session_id}/image",
                       files={"file": (name, body, mime)}, headers=AUTH)


def test_requires_service_key(client):
    assert client.post("/api/dashboard/chat/sessions").status_code == 401
    assert client.post("/api/dashboard/chat/sessions",
                       headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/dashboard/chat/sessions").status_code == 401


def test_chat_disabled_returns_503(client, monkeypatch):
    monkeypatch.setattr(config, "CHAT_ENABLED", False)
    r = client.post("/api/dashboard/chat/sessions", headers=AUTH)
    assert r.status_code == 503
    assert r.json() == {"error": "chat_disabled"}


def test_create_session_shape(start):
    s = start()
    assert set(s) == {"session_id", "state", "messages", "budget"}
    assert s["state"] == "ASK_GAME"
    assert s["budget"] == {"tier2_used": 0, "tier2_limit": config.CHAT_TIER2_PER_SESSION,
                           "messages_used": 0,
                           "messages_limit": config.CHAT_MESSAGES_PER_SESSION}
    m = s["messages"][0]
    assert set(m) == {"id", "role", "type", "content", "meta", "created_at"}
    assert m["role"] == "bot" and m["type"] == "chips"
    assert m["meta"]["chips"] == ["PrimeRush.gg (LatAm)", "PrimeRushGame (Global)",
                                  "Prime Rush MENA"]


def test_unknown_session_is_404(client):
    assert client.get("/api/dashboard/chat/sessions/9999", headers=AUTH).status_code == 404
    assert client.post("/api/dashboard/chat/sessions/9999/messages",
                       json={"text": "hi"}, headers=AUTH).status_code == 404
    assert client.post("/api/dashboard/chat/sessions/9999/end",
                       json={"reason": "manual"}, headers=AUTH).status_code == 404
    assert _upload(client, 9999).status_code == 404


def test_empty_message_is_400(client, start):
    sid = start()["session_id"]
    r = client.post(f"/api/dashboard/chat/sessions/{sid}/messages",
                    json={"text": "   "}, headers=AUTH)
    assert r.status_code == 400


def test_message_response_echoes_user_message(start, say):
    sid = start()["session_id"]
    out = say(sid, "PrimeRush.gg (LatAm)")
    assert out["messages"][0]["role"] == "user"
    assert out["messages"][0]["content"] == "PrimeRush.gg (LatAm)"
    assert out["budget"]["messages_used"] == 1


def test_end_session_manual_and_idempotent(client, start):
    sid = start()["session_id"]
    r = client.post(f"/api/dashboard/chat/sessions/{sid}/end",
                    json={"reason": "manual"}, headers=AUTH)
    data = r.json()
    assert data["state"] == "ENDED"
    assert any("New Chat" in m["content"] for m in data["messages"])
    # idempotent second end: 200, no new goodbye
    r2 = client.post(f"/api/dashboard/chat/sessions/{sid}/end",
                     json={"reason": "manual"}, headers=AUTH)
    assert r2.status_code == 200 and r2.json()["messages"] == []
    # further messages refused with the session_ended shape
    r3 = client.post(f"/api/dashboard/chat/sessions/{sid}/messages",
                     json={"text": "hello"}, headers=AUTH)
    assert r3.status_code == 409
    assert r3.json() == {"error": "session_ended", "state": "ENDED"}
    row = db.get_conn().execute("SELECT * FROM chat_sessions WHERE id=?", (sid,)).fetchone()
    assert row["end_reason"] == "manual" and row["ended_at"]


def test_end_reason_validated(client, start):
    sid = start()["session_id"]
    r = client.post(f"/api/dashboard/chat/sessions/{sid}/end",
                    json={"reason": "rage_quit"}, headers=AUTH)
    assert r.status_code == 400


def test_get_session_transcript_shape(client, start, say, known_player):
    sid = start()["session_id"]
    say(sid, "PrimeRush.gg (LatAm)")
    say(sid, "EDFXPT5G")
    r = client.get(f"/api/dashboard/chat/sessions/{sid}", headers=AUTH)
    data = r.json()
    s = data["session"]
    assert s["id"] == sid and s["state"] == "CONFIRM_NAME"
    assert s["sid"] == "EDFXPT5G" and s["player_name"] == "RastaBlasta"
    assert s["shadow"] == 1 and "budget" in s
    assert "meta_json" not in s                      # internal flags stay internal
    ids = [m["id"] for m in data["messages"]]
    assert ids == sorted(ids) and len(ids) >= 5      # greeting + 2 user + bot replies


def test_list_sessions_shape_and_paging(client, start):
    a, b = start()["session_id"], start()["session_id"]
    r = client.get("/api/dashboard/chat/sessions?limit=1&offset=0", headers=AUTH)
    data = r.json()
    assert data["total"] == 2 and len(data["sessions"]) == 1
    assert data["sessions"][0]["id"] == b            # newest first
    r2 = client.get("/api/dashboard/chat/sessions?limit=1&offset=1", headers=AUTH)
    assert r2.json()["sessions"][0]["id"] == a


def test_image_rejected_outside_ask_sid(client, start):
    sid = start()["session_id"]                      # state ASK_GAME
    assert _upload(client, sid).status_code == 409


def test_image_type_and_size_validation(client, start, say, known_player):
    sid = start()["session_id"]
    say(sid, "PrimeRush.gg (LatAm)")                 # -> ASK_SID
    assert _upload(client, sid, body=b"GIF89a", name="x.gif",
                   mime="image/gif").status_code == 415
    too_big = b"0" * (4 * 1024 * 1024 + 1)
    assert _upload(client, sid, body=too_big).status_code == 413


def test_image_cap_two_per_session(client, start, say, monkeypatch):
    from app import player_context
    monkeypatch.setattr(player_context, "get_player_context", lambda s: None)
    monkeypatch.setattr(llm, "extract_sid_from_image", lambda b64, mt: None)
    sid = start()["session_id"]
    say(sid, "PrimeRush.gg (LatAm)")
    assert _upload(client, sid).status_code == 200   # attempt 1
    r = _upload(client, sid)                         # attempt 2 -> degraded mode
    assert r.json()["state"] == "ISSUE_LOOP"
    row = db.get_conn().execute("SELECT image_attempts FROM chat_sessions WHERE id=?",
                                (sid,)).fetchone()
    assert row["image_attempts"] == 2
