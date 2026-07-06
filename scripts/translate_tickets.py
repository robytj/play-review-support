"""One-time (idempotent, resumable) batch pass that pre-translates non-English
tickets into English and caches them in ticket_translations (PROJECT_HANDOFF §4C),
so the Ticket Review pane's translate button is instant and each ticket costs at
most one Haiku call, ever.

Scope: the LATEST suggestion per conversation (same rows the grid shows). For each,
it translates the reviewer-facing text -- the player's question, the historical
staff reply, and the bot's final answer -- in a single Haiku call. English tickets
are detected and cached as a no-op skip (no API call).

Cost control (§4C):
  - one call per ticket, all fields batched together
  - already-cached tickets are skipped on re-run (resumable)
  - English tickets skipped for free
  - --limit lets you meter spend; re-run until "0 remaining"

Requires ANTHROPIC_API_KEY (Haiku via config.RAG_MODEL). Run on John's machine or
the Railway console -- the Claude sandbox has no outbound network for this.

    python -m scripts.translate_tickets --dry-run     # show what WOULD be translated
    python -m scripts.translate_tickets --limit 50    # translate up to 50, then stop
    python -m scripts.translate_tickets               # translate everything remaining
"""
from __future__ import annotations

import argparse
import sys

from app import db, llm

TARGET = "en"


def _latest_suggestions(conn):
    return conn.execute(
        """
        SELECT s.id, s.question, s.staff_answer, s.edited_answer, s.suggested_answer, s.source
        FROM suggestions s
        WHERE s.id = (SELECT MAX(s2.id) FROM suggestions s2 WHERE s2.conversation_id = s.conversation_id)
        ORDER BY s.id
        """
    ).fetchall()


def _already_done(conn, sid: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM ticket_translations WHERE suggestion_id = ? AND target_lang = ?",
        (sid, TARGET),
    ).fetchone() is not None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="max tickets to translate this run (0 = no cap)")
    ap.add_argument("--dry-run", action="store_true", help="report only; no API calls, no writes")
    args = ap.parse_args()

    db.init_db()
    conn = db.get_conn()
    rows = _latest_suggestions(conn)

    todo = [r for r in rows if not _already_done(conn, r["id"])]
    print(f"{len(rows)} tickets, {len(rows) - len(todo)} already cached, {len(todo)} remaining.")

    translated = skipped_en = errors = 0
    for r in todo:
        if args.limit and (translated + skipped_en) >= args.limit:
            print(f"Hit --limit {args.limit}; stopping (re-run to continue).")
            break
        sid = r["id"]
        question = r["question"] or ""
        staff = r["staff_answer"] or ""
        final = (r["edited_answer"] or r["suggested_answer"] or "")
        source_lang = llm.detect_language(question)

        if source_lang == TARGET:
            skipped_en += 1
            if args.dry_run:
                continue
            with db.tx() as cx:
                cx.execute(
                    "INSERT OR REPLACE INTO ticket_translations "
                    "(suggestion_id, target_lang, source_lang, question, staff_answer, final_answer) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (sid, TARGET, source_lang, question, staff, final),
                )
            continue

        if args.dry_run:
            translated += 1
            print(f"  would translate #{sid} (detected {source_lang or '?'}): {question[:60]!r}")
            continue

        try:
            out = llm.translate_text_fields(
                {"question": question, "staff_answer": staff, "final_answer": final},
                target_lang=TARGET,
            )
            with db.tx() as cx:
                cx.execute(
                    "INSERT OR REPLACE INTO ticket_translations "
                    "(suggestion_id, target_lang, source_lang, question, staff_answer, final_answer) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (sid, TARGET, source_lang, out["question"], out["staff_answer"], out["final_answer"]),
                )
            translated += 1
            if translated % 25 == 0:
                print(f"  ...{translated} translated")
        except Exception as e:  # keep going; re-run resumes where it stopped
            errors += 1
            print(f"  ! #{sid} failed: {e}", file=sys.stderr)

    verb = "would translate" if args.dry_run else "translated"
    print(f"\nDone. {verb}={translated}, english-skipped={skipped_en}, errors={errors}.")
    remaining = sum(1 for r in _latest_suggestions(conn) if not _already_done(conn, r["id"]))
    print(f"{remaining} still remaining.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
