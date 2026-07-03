"""Bootstrap pipeline -- spec section 3.

raw threads -> embed & cluster similar issues -> one Claude call per cluster distills
a draft KB article -> drafts land in kb_articles (status='draft') for dashboard
approval -> published articles get embedded & indexed.

Usage:
    python scripts/build_kb.py --in data/freshdesk_export.json
    python scripts/build_kb.py --dummy          # generates sample tickets, no API calls,
                                                  # for smoke-testing the pipeline offline
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from app import db, embeddings, vectorstore, llm
from app.config import EMBEDDING_DIM

CLUSTER_SIM_THRESHOLD = 0.80  # greedy clustering: join a doc to the nearest cluster if cos-sim >= this


def load_tickets(path: str) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def dummy_tickets() -> list[dict]:
    """Small fake dataset covering a few recurring themes, purely to prove the
    pipeline mechanics (embed -> cluster -> distill -> store -> index) work end to
    end before pointing it at real Freshdesk data."""
    samples = [
        ("Can't log in after password reset", "I reset my password but the app still says wrong password.",
         "Cleared cache and had the player log in via email link instead of password; confirmed working."),
        ("Forgot password, reset not working", "Reset email never arrived and now I'm locked out.",
         "Resent reset email from admin panel, told player to check spam folder; resolved."),
        ("Where is my order", "I bought gems 2 days ago and still don't see them in game.",
         "Order was delayed by payment processor; manually credited gems and confirmed receipt."),
        ("Order missing after purchase", "Paid for the starter pack but got nothing.",
         "Verified receipt, manually granted starter pack; refreshed player's inventory cache."),
        ("How do I link my account to Google Play", "Want to make sure my progress is saved.",
         "Walked player through Settings > Account > Link Google Play; confirmed sync."),
    ]
    return [
        {"ticket_id": i, "subject": s, "body": b, "resolution": r, "tags": []}
        for i, (s, b, r) in enumerate(samples)
    ]


def cluster_docs(docs: list[dict]) -> list[list[int]]:
    """Greedy single-linkage clustering by cosine similarity of the embedded
    subject+body. Good enough at bootstrap volume (thousands of docs); revisit with
    a real clustering lib if that stops being true."""
    texts = [f"{d['subject']}\n{d['body']}" for d in docs]
    vecs = embeddings.embed_batch(texts)
    clusters: list[list[int]] = []
    cluster_centroids: list[np.ndarray] = []
    for i, v in enumerate(vecs):
        best_j, best_sim = -1, -1.0
        for j, c in enumerate(cluster_centroids):
            sim = float(np.dot(v, c))
            if sim > best_sim:
                best_sim, best_j = sim, j
        if best_j >= 0 and best_sim >= CLUSTER_SIM_THRESHOLD:
            clusters[best_j].append(i)
            members = clusters[best_j]
            cluster_centroids[best_j] = np.mean([vecs[m] for m in members], axis=0)
        else:
            clusters.append([i])
            cluster_centroids.append(v)
    return clusters


def store_article(title, symptom, answer, tags, source_ids) -> int:
    with db.tx() as conn:
        cur = conn.execute(
            "INSERT INTO kb_articles (title, symptom, answer, tags, status, source) "
            "VALUES (?, ?, ?, ?, 'draft', ?)",
            (title, symptom, answer, tags, ",".join(str(s) for s in source_ids)),
        )
        article_id = cur.lastrowid
    vec = embeddings.embed(f"{title}\n{symptom}")
    vectorstore.upsert("kb_articles", article_id, vec)
    return article_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="infile", default=None)
    ap.add_argument("--dummy", action="store_true", help="use built-in sample tickets, no LLM calls needed for embedding-only smoke test")
    ap.add_argument("--skip-llm", action="store_true", help="cluster + report only, don't call Claude or write articles")
    args = ap.parse_args()

    if args.dummy:
        docs = dummy_tickets()
    elif args.infile:
        docs = load_tickets(args.infile)
    else:
        print("[error] pass --in <file> or --dummy", file=sys.stderr)
        sys.exit(1)

    print(f"[info] {len(docs)} source tickets")
    db.init_db()
    for table in ("kb_articles", "canned", "answer_cache"):
        vectorstore.ensure_vec_table(table)

    clusters = cluster_docs(docs)
    print(f"[info] {len(clusters)} clusters (threshold={CLUSTER_SIM_THRESHOLD})")

    created = 0
    for idx, member_idxs in enumerate(clusters):
        members = [docs[i] for i in member_idxs]
        texts = [f"Subject: {m['subject']}\nIssue: {m['body']}\nResolution: {m.get('resolution', '')}" for m in members]
        print(f"[info] cluster {idx}: {len(members)} ticket(s) -- {members[0]['subject'][:60]}")
        if args.skip_llm:
            continue
        try:
            fields = llm.distill_cluster_to_article(texts)
        except Exception as e:
            print(f"[warn] distillation failed for cluster {idx}: {e!r} -- skipping")
            continue
        if not fields.get("title") or not fields.get("answer"):
            print(f"[warn] cluster {idx} produced incomplete article, skipping")
            continue
        source_ids = [m["ticket_id"] for m in members]
        article_id = store_article(fields["title"], fields["symptom"], fields["answer"],
                                    fields["tags"], source_ids)
        created += 1
        print(f"[info]   -> draft article #{article_id}: {fields['title']}")

    print(f"[info] done. {created} draft KB article(s) created (status='draft', awaiting dashboard approval).")


if __name__ == "__main__":
    main()
