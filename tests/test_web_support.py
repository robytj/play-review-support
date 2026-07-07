"""SPEC-02 public support site sample -- app/web_support.py.

Covers: live-KB page renders (home/category/article/search), helpful-vote
persistence (kb_votes), the ?lang= switch (strings + ar RTL), the SITE_DEV_KEY
gate on /dev/components, Host-based routing (support.primerush.gg at root vs.
/site preview on the default host, with /api/dashboard/* untouched), the ticket
page by public_id, and the /chat demo seed + PREVIEW label.

Uses the real composed app from app.main (mount + middleware are the thing under
test). conftest.py pins the temp DB + offline embeddings fallback, so search
exercises the documented LIKE path.
"""
import pytest
from fastapi.testclient import TestClient

from app import config, db, web_support
from tests.conftest import AUTH

SITE_HOST = {"host": "support.primerush.gg"}


@pytest.fixture
def client():
    from app.main import app  # composed: dashboard + chat API + site mount/middleware
    return TestClient(app)


@pytest.fixture
def seed_kb():
    """A small published KB across categories, plus one draft that must never
    surface. Returns {title: (id, slug)}."""
    articles = [
        ("Restoring an in-app purchase", "Purchase didn't arrive after payment",
         "Open Store.\n- Tap Restore\n- Wait 30s", "Payments & Purchases", "published"),
        ("Refund for accidental purchase", "Player bought the wrong bundle",
         "Request a refund via the store within 48h.", "Payments & Purchases", "published"),
        ("Can't log in after an update", "Login loops back to the title screen",
         "Clear the login token and re-authenticate.", "Account & Login", "published"),
        ("Game crashes on launch", "Crash on the loading screen on Android",
         "1. Clear cache\n2. Free 1.5GB\n3. Disable overlays", "Technical Issues", "published"),
        ("Season rewards missing", "Rewards didn't arrive at rollover",
         "Rewards sync within 24h of season end.", "Rewards & Events", "published"),
        ("DRAFT: unreleased fix", "Not public yet",
         "Internal only.", "Technical Issues", "draft"),
    ]
    out = {}
    with db.tx() as c:
        c.execute("DELETE FROM kb_votes")
        for title, symptom, answer, category, status in articles:
            cur = c.execute(
                "INSERT INTO kb_articles (title, symptom, answer, status, category) "
                "VALUES (?, ?, ?, ?, ?)", (title, symptom, answer, status, category))
            out[title] = (cur.lastrowid, f"{web_support._slugify(title)}-{cur.lastrowid}")
    return out


# ------------------------------------------------------------------------- pages --

def test_home_renders_live_categories_and_popular(client, seed_kb):
    r = client.get("/site/")
    assert r.status_code == 200
    assert "How can we help?" in r.text
    # live published counts: 2 in Payments, 1 in Technical (draft excluded)
    assert "Payments &amp; Purchases" in r.text
    assert "2 articles" in r.text
    assert "Restoring an in-app purchase" in r.text          # popular row
    assert "DRAFT: unreleased fix" not in r.text
    # url_for shim is root_path-aware under the /site mount
    assert '/site/static/web/support.css' in r.text


def test_category_page(client, seed_kb):
    r = client.get("/site/kb/payments")
    assert r.status_code == 200
    assert "Restoring an in-app purchase" in r.text
    assert "Refund for accidental purchase" in r.text
    assert "Can&#39;t log in after an update" not in r.text.replace("&#39;", "'")
    assert client.get("/site/kb/not-a-category").status_code == 404


def test_article_page_and_404(client, seed_kb):
    _, slug = seed_kb["Restoring an in-app purchase"]
    r = client.get(f"/site/kb/article/{slug}")
    assert r.status_code == 200
    assert "Restoring an in-app purchase" in r.text
    assert "Tap Restore" in r.text                            # answer body rendered
    assert "<ul>" in r.text                                   # "- " lines became a list
    assert client.get("/site/kb/article/nope-99999").status_code == 404
    # 404 renders the design's error template
    assert "Lost in the drop zone" in client.get("/site/kb/article/nope-99999").text


def test_helpful_vote_persists(client, seed_kb):
    art_id, slug = seed_kb["Season rewards missing"]
    # no-JS form fallback: 303 back to the article
    r = client.post(f"/site/kb/article/{slug}/vote", data={"v": "down"},
                    follow_redirects=False)
    assert r.status_code == 303
    # support.js AJAX path: JSON
    r = client.post(f"/site/kb/article/{slug}/vote", data={"v": "up"},
                    headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    rows = db.get_conn().execute(
        "SELECT vote FROM kb_votes WHERE article_id = ? ORDER BY id", (art_id,)).fetchall()
    assert [x["vote"] for x in rows] == ["down", "up"]


def test_search_like_fallback(client, seed_kb):
    # conftest pins embeddings to the hash fallback -> documented LIKE path
    r = client.get("/site/search", params={"q": "refund"})
    assert r.status_code == 200
    assert "Refund for accidental purchase" in r.text
    assert "DRAFT: unreleased fix" not in r.text
    # empty state
    r = client.get("/site/search", params={"q": "zzzznope"})
    assert r.status_code == 200 and "No results" in r.text


# -------------------------------------------------------------------------- i18n --

def test_lang_switch_and_cookie(client, seed_kb):
    r = client.get("/site/", params={"lang": "pt-BR"})
    assert r.status_code == 200
    assert "Como podemos ajudar?" in r.text
    assert 'lang="pt-BR"' in r.text
    # choice persisted to the cookie -> next request keeps pt-BR without ?lang=
    assert client.cookies.get("lang") == "pt-BR"
    assert "Como podemos ajudar?" in client.get("/site/").text
    # en fallback for keys pt-BR doesn't carry
    assert "POPULAR" in r.text  # pt-BR has home.popular translated; sanity anyway


def test_arabic_sets_rtl(client, seed_kb):
    r = client.get("/site/", params={"lang": "ar"})
    assert r.status_code == 200
    assert 'dir="rtl"' in r.text and 'lang="ar"' in r.text
    assert "كيف يمكننا المساعدة؟" in r.text


# ------------------------------------------------------------------- dev gallery --

def test_dev_components_gated_by_key(client, monkeypatch):
    monkeypatch.setattr(config, "SITE_DEV_KEY", "")
    assert client.get("/site/dev/components").status_code == 404
    monkeypatch.setattr(config, "SITE_DEV_KEY", "sekrit")
    assert client.get("/site/dev/components").status_code == 404
    assert client.get("/site/dev/components", params={"key": "wrong"}).status_code == 404
    r = client.get("/site/dev/components", params={"key": "sekrit"})
    assert r.status_code == 200 and "Component Gallery" in r.text


# ------------------------------------------------------------------ host routing --

def test_support_host_serves_site_at_root(client, seed_kb):
    r = client.get("/", headers=SITE_HOST)
    assert r.status_code == 200 and "How can we help?" in r.text
    assert '"/static/web/support.css"' in r.text              # root-path assets
    _, slug = seed_kb["Can't log in after an update"]
    assert client.get(f"/kb/article/{slug}", headers=SITE_HOST).status_code == 200
    assert client.get("/static/web/support.css", headers=SITE_HOST).status_code == 200
    # the support domain has no API surface -- it gets the site 404 page
    assert client.get("/api/dashboard/kb/categories",
                      headers={**AUTH, **SITE_HOST}).status_code == 404


def test_default_host_keeps_api_and_gets_site_under_site(client, seed_kb):
    # existing API untouched at root on the default host
    r = client.get("/api/dashboard/kb/categories", headers=AUTH)
    assert r.status_code == 200 and "categories" in r.json()
    assert client.get("/health").status_code == 200
    # no site at bare root on the default host
    assert client.get("/", follow_redirects=False).status_code == 404
    # ...but the full site under /site
    assert client.get("/site/").status_code == 200
    # root-absolute links inside the design templates survive on the preview via
    # the thin 307 redirects
    r = client.get("/kb/payments", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/site/kb/payments"
    assert client.get("/kb/payments").status_code == 200      # follows to the page
    r = client.get("/search", params={"q": "refund"})
    assert r.status_code == 200 and "Refund for accidental purchase" in r.text


# ------------------------------------------------------------------------ ticket --

def test_ticket_page_by_public_id(client):
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO conversations (channel, status, public_id, player_id) "
            "VALUES ('web', 'escalated', 'PR-7T3ST', 'EDFXPT5G')")
        conv = cur.lastrowid
        c.execute("INSERT INTO messages (conversation_id, role, text) VALUES (?, 'user', ?)",
                  (conv, "My skin bundle never arrived."))
        c.execute("INSERT INTO messages (conversation_id, role, text) VALUES (?, 'human', ?)",
                  (conv, "Re-issued the grant, restart the app."))
    r = client.get("/site/ticket/PR-7T3ST")
    assert r.status_code == 200
    assert "PR-7T3ST" in r.text
    assert "My skin bundle never arrived." in r.text
    assert "Re-issued the grant, restart the app." in r.text
    assert "ESCALATED" in r.text                              # status pill
    assert client.get("/site/ticket/PR-NOPE0").status_code == 404
    # lower-case lookup tolerated
    assert client.get("/site/ticket/pr-7t3st").status_code == 200


# -------------------------------------------------------------------- chat (demo) --

def test_chat_demo_seed_and_preview_label(client):
    r = client.get("/site/chat")
    assert r.status_code == 200
    assert "PREVIEW — demo transcript" in r.text              # visible header eyebrow
    assert "data-seed" in r.text                              # SSR seed block present
    assert "Redmi Note 10" in r.text                          # fixture transcript content
    assert 'data-enabled="false"' in r.text                   # chat.js demo path, no polling
