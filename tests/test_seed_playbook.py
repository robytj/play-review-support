"""Package B: SupportKB playbook seeding (scripts/seed_support_playbook.py).
Runs against the isolated test DB from conftest; embeddings are on the forced
fallback there, which also exercises the no-junk-vectors rule."""
from app import config, db
from scripts import seed_support_playbook as seed


def _playbook_rows():
    return db.get_conn().execute(
        "SELECT * FROM kb_articles WHERE tags = ?", (seed.PLAYBOOK_TAG,)).fetchall()


def test_seed_creates_14_published_playbook_articles():
    seed.main()
    rows = _playbook_rows()
    assert len(rows) == 14
    assert {r["status"] for r in rows} == {"published"}
    assert all(r["category"] in config.KB_CATEGORIES for r in rows)
    assert all(r["source"] == seed.PLAYBOOK_SOURCE for r in rows)
    titles = [r["title"] for r in rows]
    assert len(set(titles)) == 14                       # no duplicate titles
    # symptom carries several player phrasings (the "/" separated quotes)
    assert all(r["symptom"].count("/") >= 1 for r in rows)


def test_seed_is_idempotent():
    seed.main()
    seed.main()
    assert len(_playbook_rows()) == 14                  # second run adds nothing


def test_seed_skips_colliding_titles_and_preserves_team_edits():
    title = seed.PLAYBOOK[0]["title"]
    with db.tx() as c:
        c.execute("INSERT INTO kb_articles (title, symptom, answer, status) "
                  "VALUES (?, 's', 'TEAM EDIT', 'published')", (title,))
    seed.main()
    rows = db.get_conn().execute(
        "SELECT * FROM kb_articles WHERE title = ?", (title,)).fetchall()
    assert len(rows) == 1                               # never duplicated
    assert rows[0]["answer"] == "TEAM EDIT"             # never overwritten
    assert len(_playbook_rows()) == 13                  # the other 13 still seeded


def test_seed_leaves_embedding_null_on_fallback_embeddings():
    # conftest forces the hash-fallback; a non-semantic vector must never be
    # written -- NULL keeps the row out of both retrieval paths until the
    # script is re-run on a machine with real fastembed.
    seed.main()
    n = db.get_conn().execute(
        "SELECT COUNT(*) AS n FROM kb_articles WHERE tags = ? AND embedding IS NOT NULL",
        (seed.PLAYBOOK_TAG,)).fetchone()["n"]
    assert n == 0


def test_playbook_answers_stay_inside_known_capabilities():
    # grounding spot-checks (PLAYER_DATA_MAP): refunds are store-side, guests
    # without a link are unrecoverable, appeals go to Fair Play review
    by_title = {a["title"]: a for a in seed.PLAYBOOK}
    refund = by_title["How to request a refund"]["answer"].lower()
    assert "not inside the game" in refund and "can't promise" in refund
    guest = by_title["Lost a guest account or moved to a new device"]["answer"].lower()
    assert "can't recover" in guest and "link" in guest
    ban = by_title["Account banned — why it happens and how to appeal"]["answer"].lower()
    assert "fair play" in ban and "can't reverse" in ban


# ------------------------------------------------- boot-time self-provisioning --

def test_bootstrap_seeds_playbook_when_kb_degenerate(monkeypatch):
    """app.main._bootstrap_chat_content(): empty/uncategorized KB -> playbook
    seeded at boot (the 2026-07-09 degenerate-gate state self-heals). Railway
    one-offs can't touch the volume's SQLite, so boot is the only safe place."""
    from app import main as app_main
    assert len(_playbook_rows()) == 0
    app_main._bootstrap_chat_content()
    assert len(_playbook_rows()) == 14
    # healthy KB -> second boot does nothing (no duplicates)
    app_main._bootstrap_chat_content()
    assert len(_playbook_rows()) == 14


def test_bootstrap_skips_baselines_without_mongo(monkeypatch):
    import threading
    from app import main as app_main
    started = []
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setattr(threading, "Thread",
                        lambda *a, **k: started.append(k) or type("T", (), {"start": lambda s: None})())
    app_main._bootstrap_chat_content()
    assert started == []          # no Mongo -> no baseline thread
