"""One-time (idempotent) enrichment pass that fills the To / From / Date fields the
Ticket Review grid needs (PROJECT_HANDOFF §4A #1, #2, #4) into
`conversations.context`, so the dashboard API can serve them without re-reading the
CSV / raw Discord dumps on every request (or at all, on Railway where those files
don't exist).

What it writes into each conversation's context JSON (nothing destructive -- only
adds keys, never removes existing ones):

  email:
    context["to"]            <- recipient support address, from support_emails.csv
                                (matched by the gmail thread id in context.gmail_thread)
    context["from"]          <- already present; left as-is
    context["reported_date"] <- ISO date of the ticket (CSV `date`, else conv.created_at)

  discord:
    context["submitter"]     <- first real (non-bot) author's display name, from
                                backfill_out/raw/<external_id>.json
    context["to"]            <- "<channel_name> / <external_id>"  (e.g. "ticket-19 / 15203...")
    context["reported_date"] <- earliest real (non-bot) message timestamp from the raw dump

  freshdesk:
    context["to"]            <- the support inbox label (FRESHDESK_DOMAIN if set)
    (from / reported_date are NOT recoverable from data/freshdesk_export.json --
     it carries only ticket_id/subject/body/resolution/tags -- so they're left unset
     and the API falls back to an "unknown / reported date" label.)

Run offline on the local DB, then re-sync to Railway (BACKFILL_RUNBOOK §C.5):
    python -m scripts.enrich_ticket_metadata          # apply
    python -m scripts.enrich_ticket_metadata --dry-run # report only, no writes

Safe to re-run: every write is an upsert of a computed value, so a second run is a
no-op unless the underlying source data changed.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.environ.get("DB_PATH", str(ROOT / "data" / "supportbot.db"))
CSV_PATH = ROOT / "support_emails.csv"
RAW_DIR = ROOT / "backfill_out" / "raw"

# Thread id lives at the end of a gmail deep link, e.g.
# https://mail.google.com/mail/u/0/#all/1924356c5a5ea4a4  ->  1924356c5a5ea4a4
_THREAD_RE = re.compile(r"([0-9a-f]{8,})\s*$")


def _thread_id_from_gmail_url(url: str) -> str | None:
    if not url:
        return None
    m = _THREAD_RE.search(url.strip())
    return m.group(1) if m else None


def load_email_to_map() -> dict[str, dict]:
    """thread_id -> {"to": ..., "date": ...} from the Gmail export CSV."""
    out: dict[str, dict] = {}
    if not CSV_PATH.exists():
        print(f"  ! {CSV_PATH.name} not found -- skipping email `to` backfill", file=sys.stderr)
        return out
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tid = (row.get("thread_id") or "").strip()
            if tid:
                out[tid] = {"to": (row.get("to") or "").strip(),
                            "date": (row.get("date") or "").strip()}
    return out


def discord_meta(external_id: str) -> dict:
    """{"submitter": name, "reported_date": iso, "channel_name": ...} from the raw
    Discord message dump. Skips bot/system messages (Ticket King's welcome embed,
    category picker, etc.) so the submitter is the actual player."""
    path = RAW_DIR / f"{external_id}.json"
    if not path.exists():
        return {}
    try:
        msgs = json.load(open(path, encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(msgs, list):
        return {}
    # Discord returns newest-first from the API; sort oldest-first by timestamp so
    # "first real author" and "earliest date" are chronological, not fetch-order.
    real = [m for m in msgs
            if isinstance(m, dict)
            and not (m.get("author") or {}).get("bot")
            and (m.get("timestamp"))
            and (m.get("content") or m.get("attachments"))]
    real.sort(key=lambda m: m.get("timestamp") or "")
    if not real:
        return {}
    first = real[0]
    author = first.get("author") or {}
    submitter = author.get("global_name") or author.get("username") or ""
    return {
        "submitter": submitter,
        "reported_date": (first.get("timestamp") or "")[:10],  # YYYY-MM-DD
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    freshdesk_to = os.environ.get("FRESHDESK_DOMAIN", "") or "Freshdesk support"

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    email_map = load_email_to_map()

    rows = conn.execute(
        "SELECT id, channel, external_id, context, created_at FROM conversations"
    ).fetchall()

    stats = {"email_to": 0, "email_date": 0, "discord_submitter": 0,
             "discord_date": 0, "discord_to": 0, "freshdesk_to": 0, "unchanged": 0}
    writes: list[tuple[str, int]] = []

    for r in rows:
        try:
            ctx = json.loads(r["context"] or "{}")
        except Exception:
            ctx = {}
        before = json.dumps(ctx, sort_keys=True)
        ch = r["channel"]

        if ch == "email":
            tid = _thread_id_from_gmail_url(ctx.get("gmail_thread", ""))
            info = email_map.get(tid or "")
            if info:
                if info["to"] and not ctx.get("to"):
                    ctx["to"] = info["to"]; stats["email_to"] += 1
            # reported_date: prefer the CSV date, else the (already real) conv date.
            if not ctx.get("reported_date"):
                ctx["reported_date"] = (info["date"][:10] if info and info["date"]
                                        else (r["created_at"] or "")[:10])
                stats["email_date"] += 1

        elif ch == "discord":
            meta = discord_meta(r["external_id"] or "")
            if meta.get("submitter") and not ctx.get("submitter"):
                ctx["submitter"] = meta["submitter"]; stats["discord_submitter"] += 1
            if meta.get("reported_date") and not ctx.get("reported_date"):
                ctx["reported_date"] = meta["reported_date"]; stats["discord_date"] += 1
            if not ctx.get("to"):
                cname = ctx.get("channel_name") or "ticket"
                ctx["to"] = f"{cname} / {r['external_id']}"; stats["discord_to"] += 1

        elif ch == "freshdesk":
            if not ctx.get("to"):
                ctx["to"] = freshdesk_to; stats["freshdesk_to"] += 1

        after = json.dumps(ctx, sort_keys=True)
        if after != before:
            writes.append((json.dumps(ctx), r["id"]))
        else:
            stats["unchanged"] += 1

    print(f"DB: {DB_PATH}")
    print(f"Scanned {len(rows)} conversations, {len(writes)} to update.")
    for k, v in stats.items():
        print(f"  {k:20s} {v}")

    if args.dry_run:
        print("\n--dry-run: no writes performed.")
        return 0

    conn.executemany("UPDATE conversations SET context = ? WHERE id = ?", writes)
    conn.commit()
    print(f"\nWrote {len(writes)} conversations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
