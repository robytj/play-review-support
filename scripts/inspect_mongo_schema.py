"""Read-only, load-safe probe of the brx_main Mongo to confirm the email/username -> SID
field mapping needed for scripts/resolve_sids.py (PROJECT_HANDOFF §4A #3).

SAFE BY DESIGN: only lists indexes and samples a few docs with an explicit small
limit (no collection scans, no unbounded queries). Emails are partially redacted in
the output so it's safe to paste back. Requires `pymongo` + `dnspython` and network
(run on your machine, not the Claude sandbox).

Usage:
    export MONGO_URI='mongodb+srv://...'      # do NOT commit this
    pip install pymongo dnspython
    python -m scripts.inspect_mongo_schema
"""
from __future__ import annotations

import os
import re
import sys

try:
    import pymongo
    from bson import ObjectId  # noqa: F401
except ImportError:
    sys.exit("pip install pymongo dnspython, then re-run.")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def redact(v):
    if isinstance(v, str) and EMAIL_RE.match(v):
        u, _, d = v.partition("@")
        return f"{u[:2]}***@{d}"
    if isinstance(v, str) and len(v) > 60:
        return v[:60] + "…"
    return v


def shape(doc, prefix="", depth=0, out=None):
    """Flatten to dotted paths -> type, one level into nested dicts."""
    if out is None:
        out = {}
    for k, v in doc.items():
        path = f"{prefix}{k}"
        if isinstance(v, dict) and depth < 2:
            shape(v, path + ".", depth + 1, out)
        elif isinstance(v, list):
            out[path] = f"list[{type(v[0]).__name__}]" if v else "list[]"
        else:
            out[path] = type(v).__name__
    return out


def main() -> int:
    uri = os.environ.get("MONGO_URI")
    if not uri:
        sys.exit("Set MONGO_URI env var first (the mongodb+srv://... string).")
    cli = pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000)
    db = cli.get_default_database()  # brx_main from the URI path
    print(f"DB: {db.name}\n")

    acc = db["account"]

    print("== account indexes (candidates for efficient $in lookups) ==")
    for ix in acc.list_indexes():
        print(f"  {ix.get('name'):30s} {dict(ix.get('key'))}")
    print()

    print("== account sample: field paths -> type (3 docs) ==")
    seen_paths = set()
    samples = list(acc.find({}, limit=3))
    for i, doc in enumerate(samples):
        sh = shape(doc)
        seen_paths |= set(sh)
        print(f"-- doc {i} --")
        for p in sorted(sh):
            print(f"  {p:40s} {sh[p]}")
        print(f"  _id -> type={type(doc['_id']).__name__}  value={redact(str(doc['_id']))}")
        print()

    print("== fields that look like email / sid / discord / username ==")
    interesting = [p for p in sorted(seen_paths)
                   if re.search(r"mail|sid|discord|user_?name|handle|login|account", p, re.I)]
    for p in interesting:
        # pull one example value for each interesting path (from the samples we already have)
        val = None
        for doc in samples:
            cur = doc
            ok = True
            for part in p.split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    ok = False; break
            if ok:
                val = cur; break
        print(f"  {p:40s} e.g. {redact(str(val))}")

    print("\n== NEXT: tell Claude which path is the player email and which is the SID "
          "(the value used in admin.brx.indusgame.com/player/<SID>). ==")
    cli.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
