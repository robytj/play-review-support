"""Local REPL to exercise answer() without running the FastAPI server or Discord bot.

Usage: python scripts/cli_test.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, router, vectorstore


def main():
    db.init_db()
    for table in ("kb_articles", "canned", "answer_cache"):
        vectorstore.ensure_vec_table(table)
    conv_id = router.get_or_create_conversation("cli", "local-test-session")
    print("SupportBot CLI test -- type a question, Ctrl-D to quit.")
    while True:
        try:
            q = input("> ").strip()
        except EOFError:
            print()
            break
        if not q:
            continue
        result = router.answer(q, conv_id)
        print(f"[tier {result['tier']}{' ESCALATE' if result['escalate'] else ''}] {result['text']}")


if __name__ == "__main__":
    main()
