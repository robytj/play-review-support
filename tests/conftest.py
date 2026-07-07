"""Shared fixtures for the shadow chat agent test suite (SPEC-08).

Env is pinned BEFORE any app import: an isolated temp SQLite file (never the real
data/supportbot.db), a known service key, and a dummy Anthropic key. Every test
runs fully offline: fastembed is forced onto its documented fallback (which flips
the scope gate onto its keyword classifier -- a real production resilience path),
Mongo is mocked at the get_player_context seam, and every llm call site is
monkeypatched.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("SUPPORT_SERVICE_API_KEY", "test-key")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-real")
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="supportbot-test-"), "test.db")

from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db, embeddings, llm, player_context, scope_gate  # noqa: E402
from app.player_context import PlayerContext  # noqa: E402

AUTH = {"Authorization": "Bearer test-key"}

_TABLES = ("chat_messages", "chat_sessions", "chat_usage", "suggestion_actions",
           "suggestions", "feedback", "messages", "conversations", "metrics_daily",
           "kb_translations", "ticket_translations", "kb_articles", "answer_cache",
           "canned", "tone_cache")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    db.init_db()
    with db.tx() as c:
        for t in _TABLES:
            c.execute(f"DELETE FROM {t}")
    db._seed_ban_responses(db.get_conn())  # migrations would re-seed on next boot anyway
    player_context.clear_cache()
    scope_gate.reset()

    # Fully offline + deterministic: hash-fallback embeddings (=> keyword scope
    # gate) and no real Anthropic calls anywhere.
    monkeypatch.setattr(embeddings, "is_using_fallback", lambda: True)
    monkeypatch.setattr(
        llm, "phrase_recognition",
        lambda facts: (f"Thanks for playing with us since {facts.get('playing_since')} — "
                       f"{facts.get('matches_played')} matches. Legend!"))
    monkeypatch.setattr(
        llm, "answer_with_rag",
        lambda q, chunks: ("mock rag answer", {"input_tokens": 0, "output_tokens": 0}))
    yield


@pytest.fixture
def client():
    from app import chat_api
    test_app = FastAPI()
    test_app.include_router(chat_api.router)
    return TestClient(test_app)


@pytest.fixture
def start(client):
    def _start():
        r = client.post("/api/dashboard/chat/sessions", headers=AUTH)
        assert r.status_code == 200, r.text
        return r.json()
    return _start


@pytest.fixture
def say(client):
    def _say(session_id, text, expect=200):
        r = client.post(f"/api/dashboard/chat/sessions/{session_id}/messages",
                        json={"text": text}, headers=AUTH)
        assert r.status_code == expect, r.text
        return r.json()
    return _say


def make_ctx(**over) -> PlayerContext:
    """The canonical mocked player (SID EDFXPT5G from the SPEC-08 §6 sample set)."""
    ctx = PlayerContext(
        sid="EDFXPT5G",
        user_id=987654321,
        nickname="RastaBlasta",
        state="Active",
        level=42,
        matches_played=1543,
        create_time=datetime(2023, 3, 15, tzinfo=timezone.utc),
        location="BR",
        build_version="2.1.0",
        chat_banned=False,
        email="rasta@example.com",
        device_ids=["dev-1", "dev-2"],
        stats={"totalKills": 12000, "totalWins": 640, "totalLosses": 900,
               "totalDamage": 5000000, "totalHeadshotKills": 800,
               "matchMvpCount": 87, "longestKillStreak": 21,
               "totalTimeSpent": 1200000, "rows": 6},
        transactions={"real_money_count": 3, "first_purchase": "2024-01-05",
                      "last_purchase": "2026-06-20", "payment_systems": ["GooglePlay"],
                      "recent": [{"date": "2026-06-20", "payment_system": "GooglePlay",
                                  "product": "gems_500", "status": "succeeded"}],
                      "scanned": 12},
        payer_tier="ACTIVE",
        agg_purchases=None,
        supporter_band="SUPPORTER",   # 3 real-money purchases -> light thanks band
        report_count_90d=1,
        banned_device_overlap=False,
        is_banned=False,
    )
    for k, v in over.items():
        setattr(ctx, k, v)
    return ctx


@pytest.fixture
def known_player(monkeypatch):
    """Mongo mocked at the SPEC-08 seam: get_player_context resolves exactly one SID."""
    ctx = make_ctx()
    monkeypatch.setattr(
        player_context, "get_player_context",
        lambda s: ctx if (s or "").strip().upper() == ctx.sid else None)
    return ctx


@pytest.fixture
def banned_player(monkeypatch):
    ctx = make_ctx(state="Locked", is_banned=True, report_count_90d=5,
                   banned_device_overlap=True)
    monkeypatch.setattr(
        player_context, "get_player_context",
        lambda s: ctx if (s or "").strip().upper() == ctx.sid else None)
    return ctx


@pytest.fixture
def issue_session(start, say):
    """Factory: a session advanced to ISSUE_LOOP with the verified mocked player.
    Requires known_player/banned_player (or equivalent monkeypatch) to be active."""
    def _mk():
        s = start()
        sid = s["session_id"]
        say(sid, "PrimeRush.gg (LatAm)")
        say(sid, "EDFXPT5G")
        out = say(sid, "Yes")
        assert out["state"] == "ISSUE_LOOP", out
        return sid
    return _mk


def bot_messages(resp: dict) -> list[dict]:
    return [m for m in resp["messages"] if m["role"] in ("bot", "system")]


def bot_text(resp: dict) -> str:
    return "\n".join(m["content"] for m in bot_messages(resp))
