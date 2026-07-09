"""FastAPI backend -- the one service both Discord and the web widget hit.
Phase 1: /chat /feedback /health. Phase 3/4 (dashboard, widget.js) mount onto this
same app in app/dashboard.py / app/widget.py once built.
"""
import json
from datetime import date

from fastapi import FastAPI
from pydantic import BaseModel

from app import db, router
from app import chat_api, dashboard_api, partner_api, web_support

app = FastAPI(title="PrimeRush SupportBot")
app.include_router(dashboard_api.router)
app.include_router(chat_api.router)  # shadow chat agent (SPEC-08), same bearer key
app.include_router(partner_api.router)  # SPEC-10 SuperX player tickets, separate PARTNER_API_KEY
# SPEC-02 public support site: Host == SUPPORT_SITE_HOST serves it at root
# (support.primerush.gg), every other host under /site (pre-DNS preview). All
# existing API routes stay untouched at root -- see app/web_support.py.
web_support.install(app)


def _bootstrap_chat_content():
    """Self-provision the data the chat agent depends on -- no exec-into-the-
    container ops step (Railway one-offs are awkward: `railway run` executes
    LOCALLY with injected env, so it can't touch the volume's SQLite file).

    1. Scope-gate KB: if there are no published+categorized kb_articles (the
       degenerate-gate state behind the 2026-07-09 purchase regression -- e.g.
       right after a DB replace), seed the 14-article playbook. Idempotent,
       team edits always win.
    2. Highlight baselines: if player_baselines is empty and Mongo is
       configured, build them in a background thread (sampled, AI-excluded) so
       'top X%' compliments light up without a manual run. Only when EMPTY --
       weekly refreshes stay explicit (scripts/build_player_baselines.py).
    Both best-effort: a failure logs loudly and never blocks boot.
    """
    import os
    import threading

    conn = db.get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM kb_articles "
                         "WHERE status = 'published' AND category != ''").fetchone()["n"]
        if n == 0:
            print("[warn] bootstrap: no published+categorized kb_articles -- "
                  "seeding the SupportKB playbook (scope gate depends on it)")
            from scripts import seed_support_playbook
            seed_support_playbook.main()
    except Exception as e:
        print(f"[error] bootstrap: playbook seeding failed ({e!r}) -- "
              "the scope gate will run on its keyword fallback")

    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM player_baselines").fetchone()["n"]
        if n == 0 and os.environ.get("MONGO_URI"):
            sample = os.environ.get("BASELINES_BOOT_SAMPLE", "1500")

            def _build():
                try:
                    from scripts import build_player_baselines
                    build_player_baselines.main(["--sample", sample])
                except Exception as e:  # noqa: BLE001
                    print(f"[error] bootstrap: baseline build failed ({e!r}) -- "
                          "elite-fallback highlights stay active")

            print(f"[info] bootstrap: player_baselines empty -- building in "
                  f"background (sample {sample})")
            threading.Thread(target=_build, name="baselines-bootstrap",
                             daemon=True).start()
    except Exception as e:
        print(f"[error] bootstrap: baseline check failed ({e!r})")


@app.on_event("startup")
def _startup():
    db.init_db()
    for table in ("kb_articles", "canned", "answer_cache"):
        __import__("app.vectorstore", fromlist=["ensure_vec_table"]).ensure_vec_table(table)
    _bootstrap_chat_content()
    # One service, not two (spec section 1) -- the Discord bot runs in this same
    # process/container so it shares this exact SQLite file, not a separate
    # Railway service with its own disk. No-ops if DISCORD_BOT_TOKEN is unset.
    from discord_bot.bot import start_in_background_thread
    start_in_background_thread()


class ChatRequest(BaseModel):
    channel: str                 # "discord" | "web"
    external_id: str             # discord thread id / web session id
    text: str
    page_url: str | None = None
    order_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: int
    message_id: int
    tier: int
    text: str
    escalate: bool


class FeedbackRequest(BaseModel):
    message_id: int
    signal: str   # thumbs_up | thumbs_down | reasked | human_takeover


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    context = json.dumps({"page_url": req.page_url, "order_id": req.order_id})
    conv_id = router.get_or_create_conversation(req.channel, req.external_id, context)
    router._log_message(conv_id, "user", None, req.text)
    result = router.answer(req.text, conv_id)
    return ChatResponse(conversation_id=conv_id, **result)


@app.post("/feedback")
def feedback(req: FeedbackRequest):
    with db.tx() as conn:
        conn.execute(
            "INSERT INTO feedback (message_id, signal) VALUES (?, ?)",
            (req.message_id, req.signal),
        )
        today = date.today().isoformat()
        if req.signal == "thumbs_up":
            db.bump_metric(today, "thumbs_up", 1)
        elif req.signal == "thumbs_down":
            db.bump_metric(today, "thumbs_down", 1)
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok"}
