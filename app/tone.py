"""Phase 7 — tone-learning loop (PHASE_6_7_SPEC).

Builds ONE pre-rendered "style block" from the suggestions corpus and caches it in the
single-row `tone_cache` table. app/llm.py answer_with_rag() reads that cached block and
prepends it to the (prompt-cached) system prompt, so Tier-2 RAG answers mirror how
PrimeRush support actually writes — without any fine-tuning and without querying the whole
suggestions table on every request.

Two signals, strongest first:
  1. Correction pairs  — rows where a human edited the draft
     (`edited_answer != suggested_answer`): "draft -> how we actually say it".
  2. Historical voice   — real `staff_answer` replies from the backfill corpus.

Rebuilt on demand via the dashboard "Refresh tone examples" button
(POST /api/dashboard/tone/refresh -> build_style_block()). Selection is bounded and
token-budgeted; nothing here runs per RAG call except a single-row read in get_style_block().
"""
from __future__ import annotations

from app import db

# Defaults (PHASE_6_7_SPEC open question — tunable). N correction pairs, M staff replies.
DEFAULT_N_PAIRS = 8
DEFAULT_M_STAFF = 6
# Rough char budget for the whole block (~4 chars/token => ~1.5k tokens). Truncate to fit.
CHAR_BUDGET = 6000
# Per-example trims so one long ticket can't eat the whole budget.
MAX_PAIR_CHARS = 500
MAX_STAFF_CHARS = 400


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())  # collapse whitespace/newlines
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _select(conn, n_pairs: int, m_staff: int):
    # source != 'chat': shadow chat sessions (SPEC-08 §5/§8) are test traffic --
    # their escalated suggestions (and any edits reviewers make to them) must never
    # train the voice. Explicit guard in code, not convention.
    pairs = conn.execute(
        """
        SELECT suggested_answer, edited_answer
        FROM suggestions
        WHERE edited_answer IS NOT NULL
          AND TRIM(edited_answer) != ''
          AND edited_answer != suggested_answer
          AND source != 'chat'
        ORDER BY id DESC
        LIMIT ?
        """,
        (n_pairs,),
    ).fetchall()

    # Representative staff replies: bounded length (skip one-liners and walls of text),
    # de-duplicated, most recent first. Bounded query — no scan of the whole table body.
    staff = conn.execute(
        """
        SELECT staff_answer FROM suggestions
        WHERE staff_answer IS NOT NULL
          AND LENGTH(staff_answer) BETWEEN 40 AND 600
          AND source != 'chat'
        GROUP BY staff_answer
        ORDER BY MAX(id) DESC
        LIMIT ?
        """,
        (m_staff,),
    ).fetchall()
    return pairs, staff


def render_style_block(pairs, staff) -> str:
    """Render the selected examples into the prompt-injected block. Applies per-example
    trims and the overall CHAR_BUDGET, dropping from the end — staff first, then pairs —
    so the strongest signal (correction pairs) survives truncation."""
    pairs, staff = list(pairs), list(staff)
    while staff and len("\n".join(_assemble(pairs, staff))) > CHAR_BUDGET:
        staff = staff[:-1]
    while pairs and len("\n".join(_assemble(pairs, staff))) > CHAR_BUDGET:
        pairs = pairs[:-1]
    return "\n".join(_assemble(pairs, staff))


def _assemble(pairs, staff):
    out = [
        "PRIMERUSH SUPPORT VOICE — mirror this. These are real examples of how our team "
        "writes to players: match the tone, warmth, brevity, greetings/sign-offs, and the "
        "player's language. Do not copy them verbatim; write a fresh answer in this voice.",
    ]
    if pairs:
        out.append("\nHow we revise drafts (draft → what we actually send):")
        for s, e in pairs:
            out.append(f'- Draft: "{_clip(s, MAX_PAIR_CHARS)}"')
            out.append(f'  We send: "{_clip(e, MAX_PAIR_CHARS)}"')
    if staff:
        out.append("\nHow our team replies:")
        for (a,) in staff:
            out.append(f'- "{_clip(a, MAX_STAFF_CHARS)}"')
    return out


def build_style_block(n_pairs: int = DEFAULT_N_PAIRS, m_staff: int = DEFAULT_M_STAFF) -> dict:
    """Rebuild + cache the style block. Returns stats. Called by the refresh endpoint."""
    conn = db.get_conn()
    pairs, staff = _select(conn, n_pairs, m_staff)
    block = render_style_block(pairs, staff) if (pairs or staff) else ""
    with db.tx() as c:
        c.execute(
            "INSERT INTO tone_cache (id, style_block, n_pairs, n_staff, chars, built_at) "
            "VALUES (1, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(id) DO UPDATE SET style_block=excluded.style_block, "
            "n_pairs=excluded.n_pairs, n_staff=excluded.n_staff, chars=excluded.chars, "
            "built_at=excluded.built_at",
            (block, len(pairs), len(staff), len(block)),
        )
    return {"n_pairs": len(pairs), "n_staff": len(staff), "chars": len(block),
            "built": True}


def get_style_block() -> str:
    """Cheap single-row read used by answer_with_rag(). Empty string until first build."""
    conn = db.get_conn()
    row = conn.execute("SELECT style_block FROM tone_cache WHERE id = 1").fetchone()
    return (row["style_block"] if row else "") or ""


def get_stats() -> dict:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT n_pairs, n_staff, chars, built_at FROM tone_cache WHERE id = 1"
    ).fetchone()
    return dict(row) if row else {"n_pairs": 0, "n_staff": 0, "chars": 0, "built_at": None}
