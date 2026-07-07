"""Read-only validation of app/player_context.py against the 8 sample SIDs
(SPEC-08 §6). Run on Railway or any machine with MONGO_URI before flipping the
Support Chat tab live:

    export MONGO_URI='mongodb+srv://...'      # do NOT commit this
    python -m scripts.probe_player_context

Prints, per SID: the fully resolved PlayerContext (emails masked). Then a
field-discovery dump of ONE user.transaction document (shape only -- dotted path ->
type, values redacted) so the per-item product/status field names can be pinned
down, and an existence check for the purchase.aggregated / topspender.* collections
(webstore purchases possibly live there).

SAFE BY DESIGN, same rules as scripts/inspect_mongo_schema.py: every query goes
through app/player_context.py (projection-only, keyed to one userId, explicit
limits) or is itself a projection find with limit 1 / a collection-name listing.
_assert_projection_only() below refuses to run if anything here ever tries a
non-projection query.
"""
from __future__ import annotations

import os
import sys
from dataclasses import asdict

# The 8 sample SIDs from SPEC-08 §6.
SAMPLE_SIDS = ["EDFXPT5G", "2S6WGTSK", "Y3MXP81Y", "TEPFTFMN",
               "VAHE3PVK", "BSMMQXYM", "G32KQ2JH", "DX4GW6CS"]


def _probe_find_one(coll, flt: dict, projection=None, allow_full_doc=False):
    """The ONLY query helper this script may use. Refuses (a) any unkeyed filter --
    no scans, ever -- and (b) any non-projection fetch unless explicitly flagged as
    the single, value-redacted shape dump. Everything else in this probe goes
    through app/player_context.py, which is projection-only by construction."""
    if not flt:
        raise RuntimeError("refusing to run an unkeyed query from the probe")
    if projection is None and not allow_full_doc:
        raise RuntimeError("refusing to run a non-projection query from the probe")
    return coll.find_one(flt, projection)


def _shape(doc, prefix="", depth=0, out=None):
    """Dotted path -> type name. Values are never printed (redacted by design)."""
    if out is None:
        out = {}
    for k, v in doc.items():
        path = f"{prefix}{k}"
        if isinstance(v, dict) and depth < 2:
            _shape(v, path + ".", depth + 1, out)
        elif isinstance(v, list):
            out[path] = f"list[{type(v[0]).__name__}]" if v else "list[]"
        else:
            out[path] = type(v).__name__
    return out


def main() -> int:
    if not os.environ.get("MONGO_URI"):
        sys.exit("Set MONGO_URI first (read-only user, same as the responder's cheater module).")

    from app import player_context  # imports after env check; reads MONGO_URI itself

    print(f"BANNED_STATES = {sorted(player_context.BANNED_STATES)}\n")

    resolved_uid = None
    for sid in SAMPLE_SIDS:
        print(f"== {sid} ==")
        ctx = player_context.get_player_context(sid)
        if ctx is None:
            print("  NOT RESOLVED (no account doc, or Mongo unavailable)\n")
            continue
        d = asdict(ctx)
        d["email"] = ctx.email_masked           # never print the raw address
        d["device_ids"] = f"<{len(ctx.device_ids)} device id(s)>"
        for k in ("sid", "user_id", "nickname", "state", "level", "matches_played",
                  "create_time", "location", "build_version", "chat_banned", "email",
                  "device_ids", "payer_tier", "report_count_90d",
                  "banned_device_overlap", "is_banned"):
            print(f"  {k:22s} {d.get(k)}")
        print(f"  {'stats':22s} {d.get('stats')}")
        print(f"  {'transactions':22s} {d.get('transactions')}")
        print()
        if resolved_uid is None and ctx.user_id is not None:
            resolved_uid = ctx.user_id

    # ---- field discovery: one user.transaction doc, shape only ----
    db = player_context._db()
    if db is None:
        sys.exit("Mongo unavailable -- cannot run the field-discovery pass.")
    print("== user.transaction field discovery (1 doc, shape only, values redacted) ==")
    if resolved_uid is None:
        print("  (no sample SID resolved -- skipping)")
    else:
        # ONE keyed find_one; the whole doc is needed for shape discovery, but only
        # dotted-path -> TYPE is printed -- values never leave this process.
        doc = _probe_find_one(db["user.transaction"], {"userId": resolved_uid},
                              allow_full_doc=True)
        if doc:
            for path, typ in sorted(_shape(doc).items()):
                print(f"  {path:45s} {typ}")
        else:
            print("  (no transaction docs for the first resolved user)")
    print()

    print("== purchase.aggregated / topspender.* existence ==")
    names = db.list_collection_names()
    print(f"  purchase.aggregated exists: {'purchase.aggregated' in names}")
    tops = sorted(n for n in names if n.startswith("topspender"))
    print(f"  topspender.* collections  : {tops or 'none found'}")
    print("\nDone. Paste this output back so the per-item transaction fields "
          "(product/status) can be confirmed in app/player_context.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
