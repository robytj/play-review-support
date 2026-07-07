"""SPEC-01 SID-first intake: sid_source migration idempotency, ingestion-time
resolution priority (claimed beats email beats scan), Mongo-validated body
scanning with the candidate cap, the degraded (Mongo-down) path, and the
dashboard's sid_coverage metric shape. Mongo is faked at the sid_lookup._coll
seam -- only the two indexed equality queries resolve_sid actually issues."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import AUTH
from app import db, player_context, sid_lookup

VALID_SIDS = {"EDFXPT5G", "CS9DNY34"}
EMAIL_TO_SID = {"rasta@example.com": "EDFXPT5G"}


class FakeColl:
    """Stand-in for the Mongo account collection."""

    def __init__(self):
        self.queries = []

    def find_one(self, q, proj=None):
        self.queries.append(q)
        if sid_lookup.MONGO_SID_FIELD in q:
            return {"_id": 1} if q[sid_lookup.MONGO_SID_FIELD] in VALID_SIDS else None
        if sid_lookup.MONGO_EMAIL_FIELD in q:
            sid = EMAIL_TO_SID.get(q[sid_lookup.MONGO_EMAIL_FIELD])
            return {sid_lookup.MONGO_SID_FIELD: sid} if sid else None
        return None


@pytest.fixture
def mongo(monkeypatch):
    coll = FakeColl()
    monkeypatch.setattr(sid_lookup, "_coll", lambda: coll)
    return coll


@pytest.fixture
def mongo_down(monkeypatch):
    monkeypatch.setattr(sid_lookup, "_coll", lambda: None)


@pytest.fixture
def dash_client():
    from app import dashboard_api
    test_app = FastAPI()
    test_app.include_router(dashboard_api.router)
    return TestClient(test_app)


# ------------------------------------------------------------------ migration --

def test_sid_source_migration_is_idempotent():
    db.init_db()
    db.init_db()  # re-running migrations must not duplicate the column or crash
    cols = [r["name"] for r in db.get_conn().execute(
        "PRAGMA table_info(conversations)").fetchall()]
    assert cols.count("sid_source") == 1


def test_sid_helper_template_seed_is_idempotent_and_inert():
    conn = db.get_conn()
    db._seed_sid_helper(conn)
    db._seed_sid_helper(conn)
    rows = conn.execute(
        "SELECT answer, embedding FROM canned WHERE trigger_text LIKE 'sid_helper:%'"
    ).fetchall()
    assert len(rows) == 1
    assert "Não sabe seu ID?" in rows[0]["answer"] and "Don't know your SID?" in rows[0]["answer"]
    assert rows[0]["embedding"] is None  # never retrievable as a Tier-0 canned match


def test_single_shared_sid_regex():
    # SPEC-01 §2: ONE regex object, defined in sid_lookup and reused everywhere.
    assert player_context.SID_RE is sid_lookup.SID_RE


# ----------------------------------------------------------- resolution priority --

def test_claimed_beats_email_beats_scan(mongo):
    # everything present and valid -> the claimed SID wins (normalized to upper)
    sid, source = sid_lookup.resolve_from_ticket(
        claimed_sid=" cs9dny34 ", email="rasta@example.com",
        body_text="my other id is EDFXPT5G")
    assert (sid, source) == ("CS9DNY34", "claimed")

    # claimed doesn't validate against Mongo -> email match wins over the scan
    sid, source = sid_lookup.resolve_from_ticket(
        claimed_sid="ZZ99ZZ99", email="rasta@example.com",
        body_text="also see CS9DNY34")
    assert (sid, source) == ("EDFXPT5G", "email_match")

    # nothing claimed, unknown email -> Mongo-validated body scan is last resort
    sid, source = sid_lookup.resolve_from_ticket(
        claimed_sid=None, email="unknown@example.com",
        body_text="hello my id CS9DNY34 please help")
    assert (sid, source) == ("CS9DNY34", "scan")


def test_claimed_with_bad_shape_falls_through(mongo):
    # not 8 chars / not upper-alnum -> never even queried as a claimed SID
    sid, source = sid_lookup.resolve_from_ticket(
        claimed_sid="my id is somewhere", email="rasta@example.com")
    assert (sid, source) == ("EDFXPT5G", "email_match")
    assert not any(
        q.get(sid_lookup.MONGO_SID_FIELD) == "MY ID IS SOMEWHERE" for q in mongo.queries)


# --------------------------------------------------------------------- body scan --

def test_scan_candidates_shape_boundaries_and_ordering():
    text = "in SETTINGS I saw AB12ZZ99 and XCS9DNY34X and AB12ZZ99 again"
    cands = sid_lookup.scan_sid_candidates(text)
    # word boundaries: the embedded XCS9DNY34X token never matches; dedupe holds;
    # digit-bearing tokens outrank all-letter words like SETTINGS
    assert cands == ["AB12ZZ99", "SETTINGS"]


def test_scan_validates_each_candidate_against_mongo(mongo):
    sid, source = sid_lookup.resolve_from_ticket(
        body_text="from SETTINGS menu, tried AB12ZZ99 but my real id is CS9DNY34")
    assert (sid, source) == ("CS9DNY34", "scan")
    # the invalid-but-SID-shaped token was checked (and rejected) before the hit
    checked = [q[sid_lookup.MONGO_SID_FIELD] for q in mongo.queries
               if sid_lookup.MONGO_SID_FIELD in q]
    assert "AB12ZZ99" in checked and "CS9DNY34" in checked


def test_scan_caps_mongo_lookups_at_three_candidates(mongo):
    sid, source = sid_lookup.resolve_from_ticket(
        body_text="logs: AA11AA11 BB22BB22 CC33CC33 CS9DNY34")
    assert (sid, source) == (None, None)  # the valid token is 4th -> beyond the cap
    assert len(mongo.queries) == sid_lookup.SCAN_CANDIDATE_CAP


# ----------------------------------------------------------------- degraded path --

def test_mongo_down_yields_nulls_and_never_raises(mongo_down):
    sid, source = sid_lookup.resolve_from_ticket(
        claimed_sid="CS9DNY34", email="rasta@example.com",
        body_text="EDFXPT5G")
    assert (sid, source) == (None, None)
    assert sid_lookup.resolve_sid(email="rasta@example.com", claimed_sid="CS9DNY34") is None


# ---------------------------------------------------------------- coverage metric --

def _seed_conversation(conn, channel, player_id, sid_source):
    conn.execute(
        "INSERT INTO conversations (channel, external_id, player_id, sid_source) "
        "VALUES (?, ?, ?, ?)",
        (channel, f"ext-{channel}-{player_id}-{sid_source}", player_id, sid_source))


def test_metrics_sid_coverage_shape(dash_client):
    with db.tx() as conn:
        _seed_conversation(conn, "discord", "CS9DNY34", "claimed")
        _seed_conversation(conn, "email", "EDFXPT5G", "email_match")
        _seed_conversation(conn, "email", "CS9DNY34", "scan")
        _seed_conversation(conn, "discord", "AB12CD3E", None)   # legacy backfill row
        _seed_conversation(conn, "web", None, None)             # never resolved

    r = dash_client.get("/api/dashboard/metrics", headers=AUTH)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"daily", "totals", "sid_coverage"}
    assert body["sid_coverage"] == {
        "window_days": 30,
        "total_conversations": 5,
        "with_player_id": 4,
        "pct": 0.8,
        "by_source": {"claimed": 1, "email_match": 1, "scan": 1,
                      "deeplink": 0, "manual": 0, "null": 2},
    }


def test_metrics_sid_coverage_empty_window(dash_client):
    body = dash_client.get("/api/dashboard/metrics", headers=AUTH).json()
    cov = body["sid_coverage"]
    assert cov["total_conversations"] == 0 and cov["with_player_id"] == 0
    assert cov["pct"] is None
    assert cov["by_source"] == {"claimed": 0, "email_match": 0, "scan": 0,
                                "deeplink": 0, "manual": 0, "null": 0}
