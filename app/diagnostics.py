"""Full system test for shadow-chat readiness (Support Settings > Full System Test).

Runs every dependency check end-to-end ON THIS DEPLOY and returns structured step
results with real (credential-sanitized) error detail, so 'SID not found' can be
traced to its actual cause: env unset, driver missing, DNS, Atlas IP access list,
auth failure, or genuinely absent data.

Read-only by construction: only ping, indexed find_one with projection, and
estimated_document_count are used against Mongo.
"""
from __future__ import annotations

import os
import re
import time

TEST_SID = os.environ.get("DIAG_TEST_SID", "EDFXPT5G")  # known-good sample (SPEC-08 §6)

_CRED_RE = re.compile(r"(://[^/:@\s]+):[^@\s]+@")


def _sanitize(text: str) -> str:
    """Never leak the Mongo password into API responses/logs."""
    return _CRED_RE.sub(r"\1:***@", str(text))


def _step(name: str, ok: bool, detail: str = "", ms: int | None = None) -> dict:
    d = {"name": name, "ok": bool(ok), "detail": _sanitize(detail)}
    if ms is not None:
        d["ms"] = ms
    return d


def run_full_test() -> dict:
    from app import config

    steps: list[dict] = []

    # ---- 1. local service basics -------------------------------------------------
    steps.append(_step("chat_enabled (Support Settings toggle)", bool(config.CHAT_ENABLED),
                       "on" if config.CHAT_ENABLED else "off — chat returns 503"))
    steps.append(_step("ANTHROPIC_API_KEY present", bool(os.environ.get("ANTHROPIC_API_KEY")),
                       "" if os.environ.get("ANTHROPIC_API_KEY")
                       else "unset — recognition phrasing + Tier-2 + image SID extraction degrade"))

    try:
        from app import db as appdb
        with appdb.get_conn() as c:
            kb = c.execute("SELECT COUNT(*) FROM kb_articles WHERE status='published'").fetchone()[0]
            canned = c.execute("SELECT COUNT(*) FROM canned").fetchone()[0]
            sessions = c.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0]
        steps.append(_step("SQLite (tickets/KB/chat tables)", True,
                           f"{kb} published KB articles, {canned} canned, {sessions} chat sessions"))
        if kb == 0:
            steps.append(_step("KB content", False,
                               "0 published articles — Tier-2 answers impossible; DB volume likely not synced"))
    except Exception as e:
        steps.append(_step("SQLite (tickets/KB/chat tables)", False, repr(e)))

    try:
        from app import scope_gate
        label, score = scope_gate.classify("I can't log in to my account")
        steps.append(_step("Scope gate", True, f"classify('can't log in') -> {label} ({score:.2f}); "
                           f"backend: {getattr(scope_gate, 'backend_name', lambda: 'n/a')() if callable(getattr(scope_gate, 'backend_name', None)) else 'embeddings-or-keyword'}"))
    except Exception as e:
        steps.append(_step("Scope gate", False, repr(e)))

    # ---- 2. game Mongo, step by step ----------------------------------------------
    uri = os.environ.get("MONGO_URI", "")
    db_name = os.environ.get("MONGO_DB_NAME", "brx_main")
    if not uri:
        steps.append(_step("MONGO_URI env", False, "unset on this service"))
        return {"steps": steps, "ok": False}
    host = _sanitize(uri).split("@")[-1].split("?")[0].rstrip("/")
    default_db_in_uri = bool(re.search(r"@[^/]+/[^?]+", uri))
    steps.append(_step("MONGO_URI env", True,
                       f"host={host} · default db in URI: {'yes' if default_db_in_uri else f'no -> using MONGO_DB_NAME={db_name}'}"))

    try:
        import pymongo
        steps.append(_step("pymongo driver", True, f"v{pymongo.version}"))
    except ImportError as e:
        steps.append(_step("pymongo driver", False,
                           f"{e!r} — add pymongo+dnspython to requirements.txt"))
        return {"steps": steps, "ok": False}

    from pymongo import MongoClient
    t0 = time.time()
    try:
        client = MongoClient(uri, serverSelectionTimeoutMS=6000)
        client.admin.command("ping")
        steps.append(_step("Mongo connect + ping", True, "", ms=int((time.time() - t0) * 1000)))
    except Exception as e:
        detail = _sanitize(repr(e))
        hint = ""
        low = detail.lower()
        if "timed out" in low or "serverselection" in low:
            hint = (" — HINT: connection reached nothing. Most common cause: this Railway "
                    "project's egress IP is not in the Atlas IP Access List (the responder "
                    "lives in a different project that IS allowed). Add 0.0.0.0/0 or this "
                    "project's egress IPs in Atlas > Network Access.")
        elif "authentication" in low or "auth failed" in low:
            hint = " — HINT: user/password in MONGO_URI is wrong for this cluster."
        elif "dns" in low or "resolution" in low or "getaddrinfo" in low:
            hint = " — HINT: SRV/DNS lookup failed; check the hostname in MONGO_URI."
        elif "ssl" in low or "tls" in low:
            hint = " — HINT: TLS handshake refused; often also the Atlas IP Access List."
        steps.append(_step("Mongo connect + ping", False, detail + hint,
                           ms=int((time.time() - t0) * 1000)))
        return {"steps": steps, "ok": False}

    try:
        db = client[db_name]
        acc_coll = os.environ.get("MONGO_ACCOUNT_COLLECTION", "account")
        t0 = time.time()
        doc = db[acc_coll].find_one(
            {os.environ.get("MONGO_SID_FIELD", "shortId"): TEST_SID},
            {"_id": 1, "shortId": 1, "nickname": 1, "state": 1},
        )
        if doc:
            from app.player_context import _nickname_str
            steps.append(_step(f"account lookup (test SID {TEST_SID})", True,
                               f"found: {_nickname_str(doc.get('nickname'))} · state={doc.get('state')}",
                               ms=int((time.time() - t0) * 1000)))
        else:
            steps.append(_step(f"account lookup (test SID {TEST_SID})", False,
                               f"connected fine but no doc in {db_name}.{acc_coll} — wrong DB/collection "
                               f"name, or this cluster isn't the LatAm one",
                               ms=int((time.time() - t0) * 1000)))
    except Exception as e:
        steps.append(_step(f"account lookup (test SID {TEST_SID})", False, repr(e)))

    for coll in ("user.stats", "user.transaction"):
        try:
            n = db[coll].estimated_document_count()
            steps.append(_step(f"{coll} readable", True, f"~{n:,} docs"))
        except Exception as e:
            steps.append(_step(f"{coll} readable", False, repr(e)))

    # ---- 3. end-to-end player context via the real code path -----------------------
    try:
        from app import player_context
        player_context._cache_clear() if hasattr(player_context, "_cache_clear") else None
        ctx = player_context.get_player_context(TEST_SID)
        if ctx:
            steps.append(_step("get_player_context() end-to-end", True,
                               f"{ctx.nickname} · {ctx.matches_played} matches · payer {ctx.payer_tier}"))
        else:
            steps.append(_step("get_player_context() end-to-end", False,
                               "returned None despite the direct lookups above — check [warn] logs"))
    except Exception as e:
        steps.append(_step("get_player_context() end-to-end", False, repr(e)))

    ok = all(s["ok"] for s in steps)
    return {"steps": steps, "ok": ok}
