"""Phase 5 -- enrich the KB from ticket data already in our DB (SHADOW_BACKFILL_SPEC §5).

No new external access: reads conversations/suggestions from SQLite, clusters
similar Q/A, distills one draft KB article per cluster (Claude), lands them as
status='draft' for dashboard approval. Reuses build_kb.py's cluster/distill/store
helpers so the two pipelines can't drift.

Sources:
  A  old closed tickets (Discord backfill + Freshdesk + email): a player question
     + a human/staff reply -> staff text is ground truth.
  B  approved suggestions: status='approved', answer = COALESCE(edited, suggested)
     -- John's curated answers.
  C  ongoing live tickets: origin='live' conversations with staff replies (picked
     up naturally as shadow mode accumulates them; re-run later to ingest more).

Idempotent: every doc carries a prefixed source id (discord:<ext> / freshdesk:<ext>
/ email:<ext> / suggestion:<id>). Ids already present in kb_articles.source are
skipped, so re-runs only add genuinely new material.

Runs on John's machine / Railway (needs embedding model + Anthropic key -- neither
reachable from the sandbox). BACK UP data/supportbot.db first (spec §4).

    python scripts/build_kb_from_tickets.py --limit 20     # sample
    python scripts/build_kb_from_tickets.py --limit 0      # all clusters
    python scripts/build_kb_from_tickets.py --skip-llm     # cluster + report only
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, vectorstore, llm
from scripts.build_kb import cluster_docs, store_article


def _first_line(text: str, n: int = 80) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return line[:n] if line else "(no subject)"


def gather_docs(conn, gaps_only: bool = False) -> list[dict]:
    docs = []

    # A + C: conversations (any channel/origin) with a player question AND a staff reply.
    # With --gaps-only, restrict to tickets whose LATEST suggestion is a tier-3 gap
    # (and that have a staff answer) -- targets exactly the uncovered topics so we
    # don't re-draft articles for things the KB already answers.
    if gaps_only:
        rows = conn.execute(
            """
            SELECT c.id AS cid, c.channel, c.external_id,
                   (SELECT text FROM messages WHERE conversation_id=c.id AND role='user'  ORDER BY id ASC LIMIT 1) AS question,
                   (SELECT text FROM messages WHERE conversation_id=c.id AND role='human' ORDER BY id ASC LIMIT 1) AS staff
            FROM conversations c
            JOIN (SELECT conversation_id, MAX(id) AS id FROM suggestions GROUP BY conversation_id) lm
                 ON lm.conversation_id = c.id
            JOIN suggestions ls ON ls.id = lm.id
            WHERE ls.tier = 3
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT c.id AS cid, c.channel, c.external_id,
                   (SELECT text FROM messages WHERE conversation_id=c.id AND role='user'  ORDER BY id ASC LIMIT 1) AS question,
                   (SELECT text FROM messages WHERE conversation_id=c.id AND role='human' ORDER BY id ASC LIMIT 1) AS staff
            FROM conversations c
            """
        ).fetchall()
    for r in rows:
        q, staff = (r["question"] or "").strip(), (r["staff"] or "").strip()
        if not q or not staff:
            continue
        ext = r["external_id"] or r["cid"]
        docs.append({
            "source_id": f"{r['channel']}:{ext}",
            "subject": _first_line(q),
            "body": q,
            "resolution": staff,
        })

    # B: approved suggestions (curated answers). Skipped in gaps-only mode (we
    # only want ground-truth staff answers for the uncovered topics there).
    rows = [] if gaps_only else conn.execute(
        """
        SELECT s.id, s.question, COALESCE(s.edited_answer, s.suggested_answer) AS answer
        FROM suggestions s WHERE s.status='approved'
        """
    ).fetchall()
    for r in rows:
        q, ans = (r["question"] or "").strip(), (r["answer"] or "").strip()
        if not q or not ans:
            continue
        docs.append({
            "source_id": f"suggestion:{r['id']}",
            "subject": _first_line(q),
            "body": q,
            "resolution": ans,
        })
    return docs


def existing_source_tokens(conn) -> set:
    toks = set()
    for r in conn.execute("SELECT source FROM kb_articles WHERE source IS NOT NULL AND source != ''"):
        for t in (r["source"] or "").split(","):
            t = t.strip()
            if t:
                toks.add(t)
    return toks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20, help="max clusters to distill (0 = all)")
    ap.add_argument("--skip-llm", action="store_true", help="cluster + report only, no Claude calls / no writes")
    ap.add_argument("--gaps-only", action="store_true", dest="gaps_only",
                    help="draft only from tickets whose latest suggestion is a tier-3 gap (targets the uncovered tickets)")
    args = ap.parse_args()

    db.init_db()
    for table in ("kb_articles", "canned", "answer_cache"):
        vectorstore.ensure_vec_table(table)
    conn = db.get_conn()

    docs = gather_docs(conn, args.gaps_only)
    if args.gaps_only:
        print("[info] --gaps-only: sourcing from tier-3 gap tickets with a staff answer")
    already = existing_source_tokens(conn)
    fresh = [d for d in docs if d["source_id"] not in already]
    print(f"[info] candidate ticket docs: {len(docs)}; already in KB: {len(docs)-len(fresh)}; new: {len(fresh)}")
    if not fresh:
        print("[info] nothing new to ingest.")
        return

    clusters = cluster_docs(fresh)
    print(f"[info] {len(clusters)} clusters from {len(fresh)} docs")
    batch = clusters if args.limit == 0 else clusters[:args.limit]
    print(f"[info] cost gate: will distill {len(batch)} cluster(s) "
          f"(~{len(batch)} Claude calls){' [--skip-llm: none]' if args.skip_llm else ''}")

    created = 0
    for idx, member_idxs in enumerate(batch):
        members = [fresh[i] for i in member_idxs]
        texts = [f"Subject: {m['subject']}\nIssue: {m['body']}\nResolution: {m['resolution']}" for m in members]
        print(f"[info] cluster {idx}: {len(members)} doc(s) -- {members[0]['subject'][:60]}")
        if args.skip_llm:
            continue
        try:
            fields = llm.distill_cluster_to_article(texts)
        except Exception as e:
            print(f"[warn] distillation failed for cluster {idx}: {e!r} -- skipping")
            continue
        if not fields.get("title") or not fields.get("answer"):
            print(f"[warn] cluster {idx} incomplete, skipping")
            continue
        source_ids = [m["source_id"] for m in members]
        aid = store_article(fields["title"], fields["symptom"], fields["answer"],
                            fields.get("tags", ""), source_ids, fields.get("category", ""))
        created += 1
        print(f"[info]   -> draft #{aid}: {fields['title']}")

    print(f"[info] done. {created} draft KB article(s) created (status='draft'). "
          "Review/publish in SupportKB; nothing auto-publishes.")


if __name__ == "__main__":
    main()
