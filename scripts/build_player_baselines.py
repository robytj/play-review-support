"""Build population baselines for the chat highlight compliments (app/highlights.py).

Samples real player accounts from brx_main, aggregates their user.stats exactly
the way app/player_context.py does for one player, computes each highlight
metric with THE SAME functions the chat uses (app/highlights.METRICS -- one
definition, no drift), and stores percentile quantiles (p50/75/90/95/99) in the
`player_baselines` SQLite table.

Run it from the deployed service environment (needs MONGO_URI), e.g.:

    railway run python scripts/build_player_baselines.py --sample 2000

Design rules carried over from the rest of the repo:
  - % sampling, never full scans (weapon-meta rule): one $sample over `account`,
    then chunked, indexed $in aggregations over user.stats.
  - AI-account exclusion per SPEC-11 §5: AI ids are 5 digits, real players 16
    digits -- exclude short ids AND isBot, belt and braces.
  - Progress prints per chunk; safe to re-run anytime (upserts per metric).
  - Money stays invisible: no purchase/spend metrics exist here by design.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402

from app import db, highlights  # noqa: E402
from app.highlights import METRICS, QUANTS  # noqa: E402
from app.player_context import (  # noqa: E402  -- reuse the exact prod aggregation shape
    _STAT_MAX_FIELDS, _STAT_SUM_FIELDS, _to_dt,
)

MONGO_URI = os.environ.get("MONGO_URI", "")
MONGO_ACCOUNT_COLLECTION = os.environ.get("MONGO_ACCOUNT_COLLECTION", "account")
MIN_REAL_ID_DIGITS = 6      # SPEC-11 §5: AI ids are 5 digits, real players 16


def _mongo():
    from pymongo import MongoClient
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    try:
        return client.get_default_database()
    except Exception:
        return client[os.environ.get("MONGO_DB_NAME", "brx_main")]


def _is_real_player(acc: dict) -> bool:
    if acc.get("isBot"):
        return False
    return len(str(acc.get("_id", ""))) >= MIN_REAL_ID_DIGITS


def _sample_accounts(mdb, n: int) -> list[dict]:
    pipeline = [
        {"$sample": {"size": n}},
        {"$project": {"_id": 1, "matchesPlayed": 1, "matchesCount": 1,
                      "createTime": 1, "isBot": 1}},
    ]
    accounts = [a for a in mdb[MONGO_ACCOUNT_COLLECTION].aggregate(pipeline)
                if _is_real_player(a)]
    print(f"[info] sampled {len(accounts)} real accounts "
          f"(requested {n}; AI/bot rows excluded)")
    return accounts


def _stats_for_chunk(mdb, user_ids: list) -> dict:
    """userId -> aggregated stats dict (sums + max), same shape as
    player_context._aggregate_stats builds for one player."""
    group = {"_id": "$userId"}
    group.update({f: {"$sum": f"${f}"} for f in _STAT_SUM_FIELDS})
    group.update({f: {"$max": f"${f}"} for f in _STAT_MAX_FIELDS})
    out = {}
    for row in mdb["user.stats"].aggregate([
        {"$match": {"userId": {"$in": user_ids}}},
        {"$group": group},
    ]):
        uid = row.pop("_id")
        out[uid] = {k: (v or 0) for k, v in row.items()}
    return out


def _metric_samples(accounts: list[dict], stats_by_uid: dict) -> dict[str, list[float]]:
    samples: dict[str, list[float]] = {m: [] for m in METRICS}
    for acc in accounts:
        matches = acc.get("matchesPlayed")
        if matches is None:
            matches = acc.get("matchesCount")
        ctx = SimpleNamespace(
            stats=stats_by_uid.get(acc["_id"]) or {},
            matches_played=matches,
            create_time=_to_dt(acc.get("createTime")),
        )
        for metric, (value_fn, _elite, _line) in METRICS.items():
            try:
                v = value_fn(ctx)
            except Exception:
                v = None
            if v is not None:
                samples[metric].append(float(v))
    return samples


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=2000,
                    help="accounts to sample (default 2000)")
    ap.add_argument("--chunk", type=int, default=200,
                    help="user.stats aggregation chunk size (default 200)")
    ap.add_argument("--min-per-metric", type=int, default=100,
                    help="skip a metric with fewer samples than this (default 100)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and print, write nothing")
    args = ap.parse_args(argv)

    if not MONGO_URI:
        print("[error] MONGO_URI is not set -- run inside the service environment "
              "(e.g. `railway run ...`)")
        return 1

    db.init_db()
    mdb = _mongo()
    accounts = _sample_accounts(mdb, args.sample)
    if not accounts:
        print("[error] no accounts sampled")
        return 1

    stats_by_uid: dict = {}
    ids = [a["_id"] for a in accounts]
    n_chunks = (len(ids) + args.chunk - 1) // args.chunk
    for i in range(0, len(ids), args.chunk):
        chunk = ids[i:i + args.chunk]
        stats_by_uid.update(_stats_for_chunk(mdb, chunk))
        done = i // args.chunk + 1
        print(f"[info] user.stats aggregation: chunk {done}/{n_chunks} "
              f"({done * 100 // n_chunks}%)")

    samples = _metric_samples(accounts, stats_by_uid)
    for metric, values in samples.items():
        if len(values) < args.min_per_metric:
            print(f"[warn] {metric}: only {len(values)} samples "
                  f"(< {args.min_per_metric}) -- skipped, fallback thresholds stay active")
            continue
        arr = np.asarray(values, dtype=np.float64)
        quantiles = {q: float(np.percentile(arr, q)) for q in QUANTS}
        pretty = ", ".join(f"p{q}={v:,.2f}" for q, v in quantiles.items())
        print(f"[info] {metric}: n={len(values)}  {pretty}")
        if not args.dry_run:
            highlights.save_baseline(metric, quantiles, len(values))
    if args.dry_run:
        print("[info] dry run -- nothing written")
    else:
        print(f"[done] baselines written to player_baselines "
              f"({db.get_conn().execute('SELECT COUNT(*) AS n FROM player_baselines').fetchone()['n']} metrics)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
