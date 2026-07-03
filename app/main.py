"""FastAPI backend -- the one service both Discord and the web widget hit.
Phase 1: /chat /feedback /health. Phase 3/4 (dashboard, widget.js) mount onto this
same app in app/dashboard.py / app/widget.py once built.
"""
import json
from datetime import date

from fastapi import FastAPI
from pydantic import BaseModel

from app import db, router

app = FastAPI(title="PrimeRush SupportBot")


@app.on_event("startup")
def _startup():
    db.init_db()
    for table in ("kb_articles", "canned", "answer_cache"):
        __import__("app.vectorstore", fromlist=["ensure_vec_table"]).ensure_vec_table(table)


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
