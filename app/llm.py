"""Claude Haiku RAG call -- Tier 2 only. Everything else in the router is free.

System prompt is a static string so Anthropic's prompt caching (cache_control) picks
it up automatically across requests, per spec section 4 ("Prompt-cached system prompt").
"""
import anthropic

from app.config import ANTHROPIC_API_KEY, RAG_MODEL, RAG_MAX_TOKENS

_client = None

SYSTEM_PROMPT = """You are the PrimeRush support agent. Answer the player's question \
using ONLY the knowledge-base excerpts provided below. Be brief, friendly, and concrete.

Rules:
- If the excerpts don't clearly answer the question, say you're not sure and that \
you're flagging it for the team -- never guess or invent policy, prices, or refund terms.
- Never promise a refund, ban reversal, or account action yourself -- say a human will \
review it.
- Keep replies under 120 words unless the question needs a numbered step list.
"""


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def answer_with_rag(question: str, kb_chunks: list[dict]) -> tuple[str, dict]:
    """kb_chunks: [{"title":..., "answer":...}, ...]. Returns (answer_text, usage_dict)."""
    context = "\n\n".join(
        f"[KB #{i+1}: {c['title']}]\n{c['answer']}" for i, c in enumerate(kb_chunks)
    )
    client = _get_client()
    resp = client.messages.create(
        model=RAG_MODEL,
        max_tokens=RAG_MAX_TOKENS,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": f"Knowledge base excerpts:\n\n{context}\n\n"
                           f"Player question: {question}",
            }
        ],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    usage = {
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }
    return text, usage


def distill_cluster_to_article(sample_texts: list[str], model: str = None) -> dict:
    """Used by build_kb.py / learn.py: turns a cluster of raw ticket texts into a
    draft KB article. Runs one call per cluster -- swap client.messages.create for
    client.messages.batches.create in build_kb.py once ticket volume justifies the
    50%-off Batch API (spec section 3).

    Defaults to RAG_MODEL (config.yaml's rag.model) instead of a separately
    hardcoded model string -- there was a real incident from this: the hardcoded
    default here (claude-3-5-haiku-latest) had been retired by Anthropic and every
    build_kb.py call 404'd with a model-not-found error, even though config.yaml
    had already been updated with a working model name for answer_with_rag()
    above. One source of truth now; pass `model=` explicitly only to override it
    for a specific call."""
    model = model or RAG_MODEL
    client = _get_client()
    joined = "\n\n---\n\n".join(sample_texts[:8])
    resp = client.messages.create(
        model=model,
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": (
                "Below are several player support tickets about the same underlying "
                "issue (player-facing text only -- internal notes already stripped). "
                "Write ONE knowledge-base article that would resolve this issue for "
                "future players. Respond with exactly these four lines, nothing else:\n"
                "TITLE: <short title>\n"
                "SYMPTOM: <what the player reports/asks, one sentence>\n"
                "ANSWER: <the resolution, player-facing tone, concrete steps if any>\n"
                "TAGS: <comma-separated tags>\n\n"
                f"{joined}"
            ),
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    fields = {"title": "", "symptom": "", "answer": "", "tags": ""}
    current = None
    for line in text.splitlines():
        for key, prefix in (("title", "TITLE:"), ("symptom", "SYMPTOM:"),
                             ("answer", "ANSWER:"), ("tags", "TAGS:")):
            if line.strip().upper().startswith(prefix):
                current = key
                fields[key] = line.split(":", 1)[1].strip()
                break
        else:
            if current:
                fields[current] += " " + line.strip()
    return fields
