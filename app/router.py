"""The one brain both channels call. Cheapest-first tiered routing -- spec section 4.

answer(question, conversation_id, context) -> dict:
    {"tier": 0|1|2|3, "text": str, "message_id": int, "escalate": bool}
"""
from datetime import date

from app import db, vectorstore, embeddings, llm, config

HOLDING_REPLY = (
    "I've flagged this for the team — you'll hear back here. Thanks for your patience!"
)


def _is_sensitive(question: str) -> bool:
    q = question.lower()
    return any(kw in q for kw in config.SENSITIVE_KEYWORDS)


def _log_message(conversation_id: int, role: str, tier, text: str, chunks=None) -> int:
    import json
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO messages (conversation_id, role, tier_used, text, retrieved_chunks) "
            "VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, tier, text, json.dumps(chunks or [])),
        )
        return cur.lastrowid


def _bump(tier: int):
    today = date.today().isoformat()
    db.bump_metric(today, f"tier{tier}_count", 1)


def _tier0_canned(q_vec):
    hits = vectorstore.search("canned", q_vec, top_k=1)
    if not hits:
        return None
    row_id, sim = hits[0]
    if sim < config.TAU_CANNED:
        return None
    conn = db.get_conn()
    row = conn.execute("SELECT answer FROM canned WHERE id = ?", (row_id,)).fetchone()
    return row["answer"] if row else None


def _tier1_answer_cache(q_vec):
    hits = vectorstore.search("answer_cache", q_vec, top_k=1, where="approved = 1")
    if not hits:
        return None
    row_id, sim = hits[0]
    if sim < config.TAU_ANSWER_CACHE:
        return None
    conn = db.get_conn()
    row = conn.execute("SELECT answer FROM answer_cache WHERE id = ?", (row_id,)).fetchone()
    if row:
        conn.execute("UPDATE answer_cache SET send_count = send_count + 1 WHERE id = ?", (row_id,))
        conn.commit()
        return row["answer"]
    return None


def _tier2_haiku_rag(question, q_vec):
    hits = vectorstore.search("kb_articles", q_vec, top_k=config.RAG_TOP_K, where="status = 'published'")
    if not hits or hits[0][1] < config.TAU_RETRIEVAL_CONFIDENCE:
        return None, None
    conn = db.get_conn()
    chunks = []
    for row_id, sim in hits:
        row = conn.execute("SELECT title, answer FROM kb_articles WHERE id = ?", (row_id,)).fetchone()
        if row:
            chunks.append({"title": row["title"], "answer": row["answer"], "similarity": sim})
    if not chunks:
        return None, None
    text, usage = llm.answer_with_rag(question, chunks)
    # seed the answer cache as unapproved -- promoted to canned only after positive feedback (learn.py)
    with db.tx() as c:
        c.execute(
            "INSERT INTO answer_cache (question_text, answer, approved) VALUES (?, ?, 0)",
            (question, text),
        )
        cache_id = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    vectorstore.upsert("answer_cache", cache_id, q_vec)
    return text, chunks


def answer(question: str, conversation_id: int) -> dict:
    q_vec = embeddings.embed(question)

    if _is_sensitive(question):
        _bump(3)
        mid = _log_message(conversation_id, "bot", 3, HOLDING_REPLY)
        return {"tier": 3, "text": HOLDING_REPLY, "message_id": mid, "escalate": True}

    canned = _tier0_canned(q_vec)
    if canned is not None:
        _bump(0)
        mid = _log_message(conversation_id, "bot", 0, canned)
        return {"tier": 0, "text": canned, "message_id": mid, "escalate": False}

    cached = _tier1_answer_cache(q_vec)
    if cached is not None:
        _bump(1)
        mid = _log_message(conversation_id, "bot", 1, cached)
        return {"tier": 1, "text": cached, "message_id": mid, "escalate": False}

    rag_answer, chunks = _tier2_haiku_rag(question, q_vec)
    if rag_answer is not None:
        _bump(2)
        mid = _log_message(conversation_id, "bot", 2, rag_answer, chunks)
        return {"tier": 2, "text": rag_answer, "message_id": mid, "escalate": False}

    _bump(3)
    mid = _log_message(conversation_id, "bot", 3, HOLDING_REPLY)
    return {"tier": 3, "text": HOLDING_REPLY, "message_id": mid, "escalate": True}


def get_or_create_conversation(channel: str, external_id: str, context: str = "") -> int:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT id FROM conversations WHERE channel = ? AND external_id = ? AND status != 'resolved'",
        (channel, external_id),
    ).fetchone()
    if row:
        return row["id"]
    with db.tx() as c:
        cur = c.execute(
            "INSERT INTO conversations (channel, external_id, context) VALUES (?, ?, ?)",
            (channel, external_id, context),
        )
        return cur.lastrowid
