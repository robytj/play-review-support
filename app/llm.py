"""Claude Haiku RAG call -- Tier 2 only. Everything else in the router is free.

System prompt is a static string so Anthropic's prompt caching (cache_control) picks
it up automatically across requests, per spec section 4 ("Prompt-cached system prompt").
"""
import anthropic

from app.config import ANTHROPIC_API_KEY, RAG_MODEL, RAG_MAX_TOKENS, KB_CATEGORIES, KB_DEFAULT_CATEGORY, KB_TRANSLATION_LANGS

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


def _system_prompt() -> str:
    """Base system prompt + the Phase-7 tone style block, if one has been built. The
    block is a single cached row (app/tone.get_style_block) — one indexed read, never a
    per-call scan of the suggestions table — and it's concatenated into the SAME system
    text so Anthropic prompt-caching still covers it. Empty until the first
    'Refresh tone examples'; behaviour is identical to before when empty."""
    try:
        from app import tone
        block = tone.get_style_block()
    except Exception:
        block = ""
    return f"{SYSTEM_PROMPT}\n\n{block}" if block else SYSTEM_PROMPT


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
                "text": _system_prompt(),
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
    category_list = "\n".join(f"- {c}" for c in KB_CATEGORIES)
    resp = client.messages.create(
        model=model,
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": (
                "Below are several player support tickets about the same underlying "
                "issue (player-facing text only -- internal notes already stripped). "
                "Write ONE knowledge-base article that would resolve this issue for "
                "future players. Respond with exactly these five lines, nothing else:\n"
                "TITLE: <short title>\n"
                "SYMPTOM: <what the player reports/asks, one sentence>\n"
                "ANSWER: <the resolution, player-facing tone, concrete steps if any>\n"
                "TAGS: <comma-separated tags>\n"
                "CATEGORY: <pick exactly one from this list, copied verbatim, nothing else:\n"
                f"{category_list}>\n\n"
                f"{joined}"
            ),
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    fields = {"title": "", "symptom": "", "answer": "", "tags": "", "category": ""}
    current = None
    for line in text.splitlines():
        for key, prefix in (("title", "TITLE:"), ("symptom", "SYMPTOM:"),
                             ("answer", "ANSWER:"), ("tags", "TAGS:"),
                             ("category", "CATEGORY:")):
            if line.strip().upper().startswith(prefix):
                current = key
                fields[key] = line.split(":", 1)[1].strip()
                break
        else:
            if current:
                fields[current] += " " + line.strip()
    if fields["category"] not in KB_CATEGORIES:
        fields["category"] = categorize_keywords(f"{fields['title']} {fields['symptom']} {fields['tags']}")
    return fields


# ------------------------------------------------- shadow chat agent (SPEC-08) --

RECOGNITION_SYSTEM_PROMPT = """You phrase a short recognition line for a game-support chat.
You are given a small set of FACTS about the player. Rules, non-negotiable:
- Use ONLY the provided facts. Never invent, estimate, or embellish numbers, dates, or achievements.
- Voice: the founder of a small, passionate game studio greeting a player they are genuinely delighted to meet — high-energy, gamer-to-gamer, warm and specific. Celebrate their achievements like they matter (they do). Never corporate, never robotic, no sycophantic filler.
- At most 2 sentences (3 when a supporter fact is present). Addressed to the player ("you"), no emoji spam (one emoji max).
- If "supporter: high" is present, add warm, specific gratitude for their long and generous support of the game (like "a huge thank-you for being one of our biggest supporters — it genuinely keeps the game running"). If "supporter: yes" is present, add one light thank-you for supporting the game. If no supporter fact is present, do not mention purchases or supporting the game at all.
- Money stays invisible: never mention amounts, totals, prices, currencies, or purchase counts, and never use the words "payer", "spender", or "VIP".
- Do not mention facts that are missing from the input. Do not ask a question.
Output the message text only, nothing else."""


def phrase_recognition(facts: dict) -> str:
    """SPEC-08 §2.4 -- the ONE Haiku call in the scripted phase: turns server-computed
    recognition facts (playing-since, matches played, one highlight) into a warm
    2-sentence line. Facts are computed deterministically in app/chat_engine.py;
    this call only phrases them. Caller falls back to a deterministic template on
    any failure -- this function just raises through."""
    client = _get_client()
    lines = "\n".join(f"- {k}: {v}" for k, v in facts.items() if v not in (None, ""))
    resp = client.messages.create(
        model=RAG_MODEL,
        max_tokens=120,
        system=[{"type": "text", "text": RECOGNITION_SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"FACTS:\n{lines}"}],
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip()


def extract_sid_from_image(image_b64: str, media_type: str) -> str | None:
    """SPEC-08 §2.2 -- Haiku vision pass over a player-uploaded profile/settings
    screenshot. Returns an uppercase 8-char SID-shaped token or None; the caller
    still validates it against Mongo (this extracts, it never authenticates)."""
    import re as _re
    client = _get_client()
    resp = client.messages.create(
        model=RAG_MODEL,
        max_tokens=50,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text",
                 "text": ("This is a screenshot of a game profile or settings screen. "
                          "Find the player ID / SID: an 8-character code of capital "
                          "letters and digits (e.g. AB12CD3E). Reply with ONLY that "
                          "8-character code, or NONE if you can't find one.")},
            ],
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip().upper()
    m = _re.search(r"\b[A-Z0-9]{8}\b", text)
    return m.group(0) if m else None


# ---------------------------------------------------------------- categorization --

# No-API-call fallback: used to backfill category on rows that predate the
# `category` column (see app/dashboard_api.py list_kb()'s self-healing backfill)
# and as a safety net whenever the LLM's CATEGORY line doesn't exactly match
# KB_CATEGORIES. Ordered -- first matching category wins, so put more specific
# buckets before "General".
_CATEGORY_KEYWORDS = [
    ("Bans & Fair Play", ("ban", "banned", "suspend", "cheat", "cheater", "hack", "exploit", "report a player", "fair play", "toxic")),
    ("Payments & Purchases", ("refund", "chargeback", "purchase", "payment", "billing", "receipt", "gems", "diamonds", "coins", "subscription", "charged", "invoice", "price")),
    ("Account & Login", ("login", "log in", "password", "account", "signed out", "can't sign in", "verify", "2fa", "linked account", "lost my account")),
    ("Technical Issues", ("crash", "bug", "error", "freeze", "lag", "loading", "won't start", "not working", "black screen", "connection")),
    ("Updates & Patches", ("update", "patch", "version", "new release", "changelog", "maintenance")),
    ("Rewards & Events", ("reward", "event", "prize", "leaderboard", "tournament", "season pass", "battle pass", "missing reward")),
    ("Gameplay & Progression", ("level", "progress", "stuck", "how do i", "how to", "strategy", "unlock", "upgrade", "tutorial")),
]


def categorize_keywords(text: str) -> str:
    """Cheap, offline categorizer -- no Claude call, safe to run on every request.
    Falls back to KB_DEFAULT_CATEGORY ('General') when nothing matches, which is
    deliberately a real, visible category rather than blank/null so the SupportKB
    tab never has to special-case an 'uncategorized' bucket."""
    t = (text or "").lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(kw in t for kw in keywords):
            return category
    return KB_DEFAULT_CATEGORY


# ------------------------------------------------------------------- translation --

def translate_article(title: str, symptom: str, answer: str, lang: str, model: str = None) -> dict:
    """On-demand translation for the SupportKB tab's language switcher. lang is one
    of KB_TRANSLATION_LANGS' keys ('pt' | 'es' | 'ar'). Caller (app/dashboard_api.py)
    is responsible for caching the result in kb_translations and invalidating it
    whenever the source article is edited -- this function itself is stateless."""
    if lang not in KB_TRANSLATION_LANGS:
        raise ValueError(f"unsupported translation language: {lang!r}")
    lang_name = KB_TRANSLATION_LANGS[lang]
    model = model or RAG_MODEL
    client = _get_client()
    resp = client.messages.create(
        model=model,
        max_tokens=600,
        messages=[{
            "role": "user",
            "content": (
                f"Translate this player-support knowledge-base article into {lang_name}. "
                "Keep the tone player-facing and natural (not a literal word-for-word "
                "translation) and keep any product/feature names that wouldn't normally "
                "be translated as-is. Respond with exactly these three lines, nothing else:\n"
                "TITLE: <translated title>\n"
                "SYMPTOM: <translated symptom>\n"
                "ANSWER: <translated answer>\n\n"
                f"TITLE: {title}\n"
                f"SYMPTOM: {symptom}\n"
                f"ANSWER: {answer}"
            ),
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    fields = {"title": "", "symptom": "", "answer": ""}
    current = None
    for line in text.splitlines():
        for key, prefix in (("title", "TITLE:"), ("symptom", "SYMPTOM:"), ("answer", "ANSWER:")):
            if line.strip().upper().startswith(prefix):
                current = key
                fields[key] = line.split(":", 1)[1].strip()
                break
        else:
            if current:
                fields[current] += " " + line.strip()
    return fields


# ------------------------------------------------------ ticket translation (§4C) --

# Cheap, offline, no-API-call language guess. Used only to SKIP translating tickets
# that are already in the target language (the common case is English), so the
# one-time batch pass in scripts/translate_tickets.py doesn't waste a Haiku call on
# them. Deliberately conservative: when unsure it returns "" (unknown) and the
# caller translates anyway rather than risk leaving foreign text untranslated.
_STOPWORDS = {
    "en": {" the ", " and ", " you ", " your ", " for ", " with ", " have ", " this ",
           " that ", " not ", " can ", " please ", " help ", " account ", " game "},
    "pt": {" não ", " você ", " está ", " para ", " com ", " meu ", " minha ", " jogo ",
           " conta ", " por favor ", " obrigado ", " que ", " uma ", " também "},
    "es": {" no ", " que ", " está ", " para ", " con ", " mi ", " por favor ",
           " gracias ", " cuenta ", " juego ", " una ", " pero ", " hola "},
}


def detect_language(text: str) -> str:
    """Returns 'en' | 'pt' | 'es' | '' (unknown). Heuristic stopword scoring -- good
    enough to decide 'is this already English?' without an API round-trip. Arabic /
    other non-Latin scripts are detected by codepoint range."""
    t = (text or "").lower()
    # Email tickets store a "[sender@domain] " prefix in the message/question text;
    # strip a single leading bracketed token so it doesn't skew short-text detection.
    if t.startswith("["):
        end = t.find("]")
        if 0 < end < 80:
            t = t[end + 1:].strip()
    if not t.strip():
        return ""
    if any("؀" <= ch <= "ۿ" for ch in t):  # Arabic block
        return "ar"
    padded = f" {t} "
    scores = {lang: sum(padded.count(w) for w in words) for lang, words in _STOPWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else ""


_LANG_NAMES = {"en": "English", "pt": "Portuguese", "es": "Spanish", "ar": "Arabic",
               "fr": "French", "de": "German", "hi": "Hindi"}


def translate_text_fields(fields: dict[str, str], target_lang: str = "en",
                          model: str = None) -> dict[str, str]:
    """Translate an arbitrary set of named text fields into target_lang in ONE Haiku
    call (cost-controlled per §4C). `fields` is {name: text}; returns {name: translated}
    for the same keys. Empty inputs are passed through untouched. Used by the Ticket
    Review translate button and the scripts/translate_tickets.py batch pass; results
    are cached by the caller in ticket_translations, never re-translated per view."""
    lang_name = _LANG_NAMES.get(target_lang, target_lang)
    model = model or RAG_MODEL
    # Only send non-empty fields to the model; keep a stable ordering.
    items = [(k, v) for k, v in fields.items() if (v or "").strip()]
    if not items:
        return {k: (v or "") for k, v in fields.items()}
    client = _get_client()
    numbered = "\n".join(f"[[{i+1}]]\n{v}" for i, (_, v) in enumerate(items))
    resp = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": (
                f"Translate each numbered section below into {lang_name}. Keep a natural, "
                "player-support tone (not word-for-word), and keep product/feature names, "
                "error codes, SIDs, emails and URLs unchanged. Preserve the exact "
                "[[n]] markers and output ONLY the translated sections, each under its "
                f"marker, nothing else:\n\n{numbered}"
            ),
        }],
    )
    text = "".join(b.text for b in resp.content if b.type == "text")
    # Parse back the [[n]] blocks.
    parsed: dict[int, str] = {}
    current = None
    buf: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[[") and stripped.rstrip().endswith("]]"):
            if current is not None:
                parsed[current] = "\n".join(buf).strip()
            try:
                current = int(stripped.strip("[] "))
            except ValueError:
                current = None
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        parsed[current] = "\n".join(buf).strip()

    out = {k: (v or "") for k, v in fields.items()}
    for i, (k, original) in enumerate(items):
        out[k] = parsed.get(i + 1, original)  # fall back to original if a block went missing
    return out
