"""support.primerush.gg -- public support site (SPEC-02, sample build for review).

Serves the Claude Design package (templates/web/* + static/web/*) from this same
FastAPI service. The templates are the design deliverable; this module adapts the
BACKEND to them (Jinja env with t() + a Flask-style url_for shim, base context per
DESIGN-NOTES.md §TODO(backend)) and only base.html needed a Jinja2 compatibility
edit (see the commit message).

Host routing (one Railway service, two faces):
  - Requests whose Host == config.SUPPORT_SITE_HOST get the site at ROOT paths
    (SupportSiteHostMiddleware dispatches the whole request straight to site_app,
    so /api/* etc. simply don't exist on the support domain).
  - Every other host gets the exact same app mounted under /site
    (https://primebot.up.railway.app/site -- the pre-DNS review URL) while all
    existing API routes stay untouched at root. Root-absolute links inside the
    design templates ("/kb/...", "/chat") are caught by thin preview redirects
    (see _attach_preview_redirects) so click-through works on the preview too.

Sample scope (explicitly NOT in this build -- SPEC-02 for the rest):
  - /chat is DEMO MODE: the transcript is seeded server-side from
    static/web/fixtures/chat_demo.json and chat.js runs its fixture path
    (data-enabled=false -> render seed, no polling). The real public chat API
    (/api/web/chat/message + /poll, web_sessions, rate limits) is SPEC-02 §5 +
    SPEC-03 work.  TODO(SPEC-02 §5, SPEC-03): wire the live chat runtime.
  - /ingame renders the invalid-token branch only (identity sheet).
    TODO(SPEC-02 §4): JWT verification + web_sessions + 302-to-/chat happy path.
  - /identity/link and /ticket/<id>/reply are no-op redirects so the design's
    forms don't dead-end.  TODO(SPEC-02 §4 / §5).
  - Article TRANSLATE action serves the kb_translations CACHE only; it never
    calls the LLM from this public route.  TODO(SPEC-02 §2 i18n): populate the
    cache via the existing dashboard flow on demand.
"""
import json
import re
from datetime import datetime, timezone

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, db, embeddings, vectorstore
from app.web_i18n import KB_TRANSLATION_LANG, RTL_LANGS, make_t, normalize_lang

# --------------------------------------------------------------------- categories --
# Site category slugs (the design's t('cat.<slug>') keys + icon names in
# _icons.html map 1:1 onto config.KB_CATEGORIES, in the same fixed order).
CATEGORY_SLUGS = ["account", "payments", "gameplay", "bans",
                  "technical", "updates", "rewards", "general"]
SLUG_TO_CATEGORY = dict(zip(CATEGORY_SLUGS, config.KB_CATEGORIES))
CATEGORY_TO_SLUG = {v: k for k, v in SLUG_TO_CATEGORY.items()}

_FIXTURES = config.ROOT / "static" / "web" / "fixtures"

# ------------------------------------------------------------------------ jinja env --
_env = Environment(
    loader=FileSystemLoader(str(config.ROOT / "templates")),
    autoescape=select_autoescape(("html", "xml")),
)


def _make_url_for(request: Request):
    """Flask-style url_for shim for the design templates. They only ever call
    url_for('static', filename=...); route names are handled defensively. The
    emitted path is root_path-aware so the SAME rendered HTML works both on the
    support host (root_path='') and on the /site preview mount (root_path='/site')."""
    root = request.scope.get("root_path", "") or ""

    def url_for(name: str, filename: str | None = None, **params) -> str:
        if name == "static":
            return f"{root}/static/{filename}"
        known = {"home": "/", "index": "/", "search": "/search", "chat": "/chat"}
        return root + known.get(name, "/")

    return url_for


def _resolve_lang(request: Request) -> tuple[str, bool]:
    """?lang= wins (and gets persisted to the cookie by _render), else cookie,
    else en. Returns (lang, came_from_query)."""
    q = normalize_lang(request.query_params.get("lang"))
    if q:
        return q, True
    c = normalize_lang(request.cookies.get("lang"))
    if c:
        return c, False
    return "en", False


def _base_context(request: Request, lang: str) -> dict:
    # Base context contract per DESIGN-NOTES.md §TODO(backend). identity is the
    # guest shape until SPEC-02 §4 web_sessions lands.
    return {
        "request": request,
        "lang": lang,
        "dir": "rtl" if lang in RTL_LANGS else "ltr",
        "t": make_t(lang),
        "url_for": _make_url_for(request),
        "identity": {"sid": None, "is_guest": True, "masked_sid": None},
        "web_chat_enabled": bool(config.CHAT_ENABLED),
    }


def _render(request: Request, template: str, ctx: dict | None = None,
            status_code: int = 200) -> HTMLResponse:
    lang, from_query = _resolve_lang(request)
    context = _base_context(request, lang)
    context.update(ctx or {})
    html = _env.get_template(template).render(context)
    resp = HTMLResponse(html, status_code=status_code)
    if from_query:  # inline ?lang= switch persists (session/cookie per DESIGN-NOTES 3)
        resp.set_cookie("lang", lang, max_age=180 * 24 * 3600, samesite="lax")
    return resp


# ------------------------------------------------------------------------ helpers --

def _slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")
    return s or "article"


def article_slug(row) -> str:
    """Stable public slug: readable title + the immutable row id as suffix
    (kb_articles has no slug column; the trailing id is what's actually looked up)."""
    return f"{_slugify(row['title'])}-{row['id']}"


def _article_by_slug(slug: str):
    m = re.search(r"(\d+)$", slug or "")
    if not m:
        return None
    return db.get_conn().execute(
        "SELECT id, title, symptom, answer, category FROM kb_articles "
        "WHERE id = ? AND status = 'published'", (int(m.group(1)),)
    ).fetchone()


def _snippet(text: str, n: int = 110) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _article_row_ctx(row) -> dict:
    return {"slug": article_slug(row), "title": row["title"],
            "snippet": _snippet(row["symptom"])}


def _body_html(symptom: str, answer: str) -> Markup:
    """KB symptom+answer -> the article body (SPEC-02a 5.3: h3/p/ol/ul/strong).
    Everything is escaped first; structure only from blank lines and -/1. list
    markers -- KB text is staff-authored plain text, not HTML."""
    out = []
    if (symptom or "").strip():
        out.append(f"<p><strong>{escape(' '.join(symptom.split()))}</strong></p>")
    lines = (answer or "").splitlines()
    list_tag = None

    def close_list():
        nonlocal list_tag
        if list_tag:
            out.append(f"</{list_tag}>")
            list_tag = None

    for raw in lines:
        line = raw.strip()
        if not line:
            close_list()
            continue
        m_ul = re.match(r"^[-*•]\s+(.*)$", line)
        m_ol = re.match(r"^\d+[.)]\s+(.*)$", line)
        if m_ul or m_ol:
            tag = "ul" if m_ul else "ol"
            if list_tag != tag:
                close_list()
                out.append(f"<{tag}>")
                list_tag = tag
            out.append(f"<li>{escape((m_ul or m_ol).group(1))}</li>")
        else:
            close_list()
            out.append(f"<p>{escape(line)}</p>")
    close_list()
    return Markup("".join(out))


def _category_counts(conn) -> dict:
    rows = conn.execute(
        "SELECT category, COUNT(*) AS n FROM kb_articles "
        "WHERE status = 'published' GROUP BY category").fetchall()
    return {r["category"]: r["n"] for r in rows}


def _categories_ctx(conn) -> list[dict]:
    counts = _category_counts(conn)
    return [{"slug": slug, "icon": slug, "count": counts.get(SLUG_TO_CATEGORY[slug], 0)}
            for slug in CATEGORY_SLUGS]


def _popular_ctx(conn, limit: int = 5) -> list[dict]:
    # "top articles" -- no view counter exists yet, so most-recently-updated
    # published stands in.  TODO(SPEC-02 §3): views-based ranking once tracked.
    rows = conn.execute(
        "SELECT id, title, symptom FROM kb_articles WHERE status = 'published' "
        "ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
    return [_article_row_ctx(r) for r in rows]


def _search_articles(q: str, limit: int = 10) -> list[dict]:
    """Embedding search over published KB when fastembed is real; LIKE fallback
    otherwise (or on any vec-path error). Mirrors app/router.py's published-only
    filter."""
    conn = db.get_conn()
    try:
        if not embeddings.is_using_fallback():
            hits = vectorstore.search("kb_articles", embeddings.embed(q),
                                      top_k=limit, where="status = 'published'")
            ids = [row_id for row_id, _sim in hits]
            if ids:
                marks = ",".join("?" * len(ids))
                rows = conn.execute(
                    f"SELECT id, title, symptom FROM kb_articles WHERE id IN ({marks})",
                    ids).fetchall()
                by_id = {r["id"]: r for r in rows}
                return [_article_row_ctx(by_id[i]) for i in ids if i in by_id]
    except Exception:
        pass  # fall through to LIKE
    like = f"%{q}%"
    rows = conn.execute(
        "SELECT id, title, symptom FROM kb_articles WHERE status = 'published' "
        "AND (title LIKE ? OR symptom LIKE ? OR answer LIKE ?) "
        "ORDER BY updated_at DESC LIMIT ?", (like, like, like, limit)).fetchall()
    return [_article_row_ctx(r) for r in rows]


def _related_articles(row, limit: int = 3) -> list[dict]:
    conn = db.get_conn()
    try:
        if not embeddings.is_using_fallback():
            hits = vectorstore.search(
                "kb_articles", embeddings.embed(f"{row['title']} {row['symptom']}"),
                top_k=limit + 1, where="status = 'published'")
            ids = [i for i, _ in hits if i != row["id"]][:limit]
            if ids:
                marks = ",".join("?" * len(ids))
                rows = conn.execute(
                    f"SELECT id, title, symptom FROM kb_articles WHERE id IN ({marks})",
                    ids).fetchall()
                by_id = {r["id"]: r for r in rows}
                return [_article_row_ctx(by_id[i]) for i in ids if i in by_id]
    except Exception:
        pass
    rows = conn.execute(
        "SELECT id, title, symptom FROM kb_articles WHERE status = 'published' "
        "AND category = ? AND id != ? ORDER BY updated_at DESC LIMIT ?",
        (row["category"], row["id"], limit)).fetchall()
    return [_article_row_ctx(r) for r in rows]


def _rel_time(ts: str) -> str:
    """sqlite datetime('now') text -> compact relative label (Space Mono, per design)."""
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return ts or ""
    secs = max(0, (datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


# Player-facing pill states the design ships CSS for (SPEC-02a §4.7) <- internal
# conversations.status values.
_STATUS_PILL = {"open": "open", "escalated": "escalated", "resolved": "resolved",
                "paused": "open", "answered": "answered", "closed": "closed"}


# ========================================================================= site app ==
site_app = FastAPI(title="Prime Rush Support Site",
                   docs_url=None, redoc_url=None, openapi_url=None)
site_app.mount("/static", StaticFiles(directory=str(config.ROOT / "static")), name="static")


@site_app.exception_handler(StarletteHTTPException)
async def _site_http_error(request: Request, exc: StarletteHTTPException):
    template = "web/404.html" if exc.status_code == 404 else "web/500.html"
    return _render(request, template, status_code=exc.status_code)


@site_app.exception_handler(Exception)
async def _site_server_error(request: Request, exc: Exception):
    return _render(request, "web/500.html", status_code=500)


# ------------------------------------------------------------------------- pages --

@site_app.get("/", response_class=HTMLResponse)
def home(request: Request):
    conn = db.get_conn()
    return _render(request, "web/index.html", {
        "categories": _categories_ctx(conn),
        "popular": _popular_ctx(conn),
    })


@site_app.get("/kb/{category_slug}", response_class=HTMLResponse)
def category(request: Request, category_slug: str):
    name = SLUG_TO_CATEGORY.get(category_slug)
    if not name:
        raise StarletteHTTPException(404)
    rows = db.get_conn().execute(
        "SELECT id, title, symptom FROM kb_articles WHERE status = 'published' "
        "AND category = ? ORDER BY updated_at DESC", (name,)).fetchall()
    return _render(request, "web/category.html", {
        "category": {"slug": category_slug},
        "articles": [_article_row_ctx(r) for r in rows],
    })


@site_app.get("/kb/article/{slug}", response_class=HTMLResponse)
def article(request: Request, slug: str):
    row = _article_by_slug(slug)
    if not row:
        raise StarletteHTTPException(404)
    lang, _ = _resolve_lang(request)
    t = make_t(lang)
    cat_slug = CATEGORY_TO_SLUG.get(row["category"], "general")

    # Cached translation (kb_translations) when the session language has one and
    # ?original=1 wasn't asked for. Read-only: the cache is populated by the
    # existing dashboard flow, never from this public route.
    title, symptom, answer = row["title"], row["symptom"], row["answer"]
    is_translated, has_translation = False, False
    trans_lang = KB_TRANSLATION_LANG.get(lang)
    if trans_lang:
        tr = db.get_conn().execute(
            "SELECT title, symptom, answer FROM kb_translations "
            "WHERE article_id = ? AND lang = ?", (row["id"], trans_lang)).fetchone()
        if tr:
            has_translation = True
            if request.query_params.get("original") != "1":
                title, symptom, answer = tr["title"], tr["symptom"], tr["answer"]
                is_translated = True

    return _render(request, "web/article.html", {
        "article": {
            "slug": article_slug(row),
            "title": title,
            "category_slug": cat_slug,
            "category_label": t("cat." + cat_slug),
            "body_html": _body_html(symptom, answer),
            "is_translated": is_translated,
            "translated_lang": lang if is_translated else None,
            "has_translation": has_translation,
        },
        "related": _related_articles(row),
    })


@site_app.post("/kb/article/{slug}/vote")
def article_vote(request: Request, slug: str, v: str = Form("up")):
    row = _article_by_slug(slug)
    if not row:
        raise StarletteHTTPException(404)
    vote = v if v in ("up", "down") else "up"
    lang, _ = _resolve_lang(request)
    with db.tx() as conn:
        conn.execute("INSERT INTO kb_votes (article_id, vote, lang) VALUES (?, ?, ?)",
                     (row["id"], vote, lang))
    if request.headers.get("x-requested-with") == "fetch":  # support.js AJAX path
        return JSONResponse({"ok": True})
    root = request.scope.get("root_path", "") or ""
    return RedirectResponse(f"{root}/kb/article/{slug}", status_code=303)


@site_app.post("/kb/article/{slug}/translate")
def article_translate(request: Request, slug: str):
    """TODO(SPEC-02 §2 i18n): populate kb_translations via the existing dashboard
    translate flow. This public sample never spends LLM tokens -- if a cached
    translation exists the article route already serves it, so this is a no-op
    redirect back to the article."""
    if not _article_by_slug(slug):
        raise StarletteHTTPException(404)
    root = request.scope.get("root_path", "") or ""
    return RedirectResponse(f"{root}/kb/article/{slug}", status_code=303)


@site_app.get("/search", response_class=HTMLResponse)
def search(request: Request, q: str = ""):
    q = q.strip()
    results = _search_articles(q) if q else []
    return _render(request, "web/search.html", {
        "q": q, "results": results, "count": len(results),
    })


@site_app.get("/ticket/{public_id}", response_class=HTMLResponse)
def ticket(request: Request, public_id: str):
    conn = db.get_conn()
    row = conn.execute(
        "SELECT id, status, closed_at FROM conversations WHERE public_id = ?",
        (public_id.strip().upper(),)).fetchone()
    if not row:
        raise StarletteHTTPException(404)
    msgs = conn.execute(
        "SELECT role, text, created_at FROM messages WHERE conversation_id = ? "
        "ORDER BY id", (row["id"],)).fetchall()
    status = _STATUS_PILL.get(row["status"], "closed")
    if row["closed_at"]:
        status = "closed"
    return _render(request, "web/ticket.html", {
        "ticket": {"public_id": public_id.strip().upper(), "status": status},
        "messages": [{
            "author": "you" if m["role"] == "user" else "staff",
            "time_rel": _rel_time(m["created_at"]),
            "time_iso": (m["created_at"] or "").replace(" ", "T") + "Z",
            "body_html": _body_html("", m["text"]),
        } for m in msgs],
    })


@site_app.post("/ticket/{public_id}/reply")
def ticket_reply(request: Request, public_id: str):
    """Read-only thread in this sample.  TODO(SPEC-02 §5): append the player
    reply to `messages`, reopen if needed, notify the dashboard queue."""
    root = request.scope.get("root_path", "") or ""
    return RedirectResponse(f"{root}/ticket/{public_id}", status_code=303)


@site_app.get("/chat", response_class=HTMLResponse)
def chat(request: Request):
    """DEMO MODE for this sample: the transcript is seeded server-side from
    static/web/fixtures/chat_demo.json into the [data-seed] block, chat_enabled
    is forced off so chat.js runs its fixture path (render seed, no transport),
    and the page is labelled PREVIEW both in the header eyebrow and as the first
    system note in the transcript.
    TODO(SPEC-02 §5 + SPEC-03): the real public chat API (/api/web/chat/message,
    /api/web/chat/poll, web_sessions, rate limits, escalation-to-ticket)."""
    fx = json.loads((_FIXTURES / "chat_demo.json").read_text(encoding="utf-8"))
    seed = ([{"type": "system", "text": "PREVIEW — demo transcript"}]
            + fx.get("initial_transcript", [])
            + fx.get("demo_all_kinds", []))
    return _render(request, "web/chat.html", {
        "session": {"public_id": "demo", "ticket_id": "PREVIEW — demo transcript",
                    "chat_enabled": False},
        "initial_transcript": seed,
    })


@site_app.get("/ingame", response_class=HTMLResponse)
def ingame(request: Request, sid: str = ""):
    """Invalid-token branch ONLY in this sample: brand flash then the identity
    sheet ('Confirm your player ID'), prefilled with any ?sid= from the deeplink.
    TODO(SPEC-02 §4): verify sessionToken JWT (signing scheme pending with W),
    create a web_sessions row, and 302 straight to /chat on the happy path."""
    return _render(request, "web/ingame.html", {"prefill_sid": sid.strip().upper()})


@site_app.post("/identity/link")
def identity_link(request: Request):
    """TODO(SPEC-02 §4): SID/email verification + web_sessions. No-op redirect so
    the design's identity sheet form doesn't dead-end in this sample."""
    root = request.scope.get("root_path", "") or ""
    return RedirectResponse(f"{root}/", status_code=303)


@site_app.get("/dev/components", response_class=HTMLResponse)
def dev_components(request: Request, key: str = ""):
    """SPEC-02a §10 gallery. Gated by env SITE_DEV_KEY (?key= must match);
    404 -- not 403 -- otherwise, so the page doesn't advertise its existence."""
    if not config.SITE_DEV_KEY or key != config.SITE_DEV_KEY:
        raise StarletteHTTPException(404)
    chat_fx = json.loads((_FIXTURES / "chat_demo.json").read_text(encoding="utf-8"))
    kb_fx = json.loads((_FIXTURES / "kb_demo.json").read_text(encoding="utf-8"))
    return _render(request, "web/dev_components.html", {
        "demo": chat_fx.get("demo_all_kinds", []),
        "categories": kb_fx.get("categories", []),
        "popular": kb_fx.get("popular", []),
    })


# ==================================================================== host routing ==

class SupportSiteHostMiddleware:
    """Pure ASGI dispatch: if the request's Host is the support-site domain, hand
    the WHOLE request to site_app at root paths; every other host falls through
    to the normal app (which additionally exposes the site under /site).
    Reads config.SUPPORT_SITE_HOST at call time (module attribute, same hot rule
    as the rest of app/config.py)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            host = ""
            for k, v in scope.get("headers") or ():
                if k == b"host":
                    host = v.decode("latin-1").split(":")[0].strip().lower()
                    break
            if host and host == (config.SUPPORT_SITE_HOST or "").lower():
                await site_app(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _attach_preview_redirects(app):
    """On non-support hosts the site lives under /site, but the design templates
    (deliberately untouched) emit root-absolute links like /kb/... and /chat.
    These thin redirects keep the /site preview fully click-through-able without
    colliding with any existing root route (every path here currently 404s;
    /chat gets GET only -- the existing POST /chat API is untouched)."""
    def _redir(request: Request):
        q = str(request.url.query)
        return RedirectResponse("/site" + request.url.path + (f"?{q}" if q else ""),
                                status_code=307)

    for path in ("/kb/{rest:path}", "/search", "/ticket/{rest:path}", "/ingame",
                 "/dev/components", "/legal/{rest:path}", "/identity/{rest:path}"):
        app.add_api_route(path, _redir, methods=["GET", "POST"], include_in_schema=False)
    app.add_api_route("/chat", _redir, methods=["GET"], include_in_schema=False)


def install(app):
    """Called once from app/main.py. Mount order matters only in that the /site
    mount and redirects are plain routes on the existing app, while the Host
    dispatch wraps everything."""
    app.mount("/site", site_app, name="support_site_preview")
    _attach_preview_redirects(app)
    app.add_middleware(SupportSiteHostMiddleware)
