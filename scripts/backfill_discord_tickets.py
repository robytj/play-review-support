"""Discord ticket backfill -- see SHADOW_BACKFILL_SPEC.md for the full plan.

Status: only the `discover` subcommand is implemented. The spec is explicit that
each phase stops for John's review before the next one is built -- `fetch` and
`replay` come after he's reviewed backfill_out/channels_audit.json and said go.

REST-only by design (constraint #1 in the spec): plain `requests` against Discord's
HTTP API, no discord.py gateway connection here. Posting is structurally impossible
from this script. DISCORD_BOT_TOKEN is only ever read from local .env (constraint #2)
-- it stays unset on Railway until Phase 6.

This sandbox has no network path to Discord (verified separately), so `discover`
is meant to be run on John's machine:
    python scripts/backfill_discord_tickets.py discover
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from dotenv import load_dotenv

load_dotenv()

API_BASE = "https://discord.com/api/v10"
DISCORD_EPOCH_MS = 1420070400000  # 2015-01-01T00:00:00Z -- snowflake timestamp origin
CHANNEL_TYPE_CATEGORY = 4
AUDIT_LOG_ACTION_CHANNEL_DELETE = 12

TRANSCRIPT_NAME_RE = re.compile(r"transcript|log|arquivo|fechado|closed", re.IGNORECASE)

OUT_DIR = Path(__file__).resolve().parent.parent / "backfill_out"


def _require_env(*names: str) -> dict:
    """Aborts naming exactly which var is missing/empty -- never silently falls
    back to 'all channels' (spec Phase 0 step 0). These are expected to already
    be set on Railway; John copies them into local .env for this script."""
    values = {}
    missing = []
    for name in names:
        v = os.environ.get(name, "").strip()
        if not v:
            missing.append(name)
        values[name] = v
    if missing:
        print(f"[error] missing/empty in local .env: {', '.join(missing)}", file=sys.stderr)
        print(
            "[error] copy these from the PrimeRush-Bot Railway service's variables "
            "into local .env (copy, don't move -- the live service still needs them) "
            "and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)
    return values


def _snowflake_to_dt(snowflake: str) -> datetime:
    ms = (int(snowflake) >> 22) + DISCORD_EPOCH_MS
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


class DiscordREST:
    """Minimal REST client: bot-token auth, GET only (discover never writes),
    honors 429 Retry-After. No gateway, no discord.py -- see module docstring."""

    def __init__(self, token: str):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bot {token}"})

    def get(self, path: str, params: dict = None) -> requests.Response:
        url = f"{API_BASE}{path}"
        while True:
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                wait = resp.json().get("retry_after", 2)
                print(f"[warn] rate limited on {path}, sleeping {wait}s")
                time.sleep(wait)
                continue
            return resp

    def get_json(self, path: str, params: dict = None):
        resp = self.get(path, params=params)
        if resp.status_code != 200:
            print(f"[warn] GET {path} -> {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()


def _list_guild_channels(client: DiscordREST, guild_id: str) -> list[dict]:
    data = client.get_json(f"/guilds/{guild_id}/channels")
    if data is None:
        print("[error] couldn't list guild channels -- check DISCORD_GUILD_ID and bot permissions", file=sys.stderr)
        sys.exit(1)
    return data


def _list_active_threads(client: DiscordREST, guild_id: str) -> list[dict]:
    data = client.get_json(f"/guilds/{guild_id}/threads/active")
    return (data or {}).get("threads", [])


def _list_archived_threads(client: DiscordREST, channel_id: str) -> list[dict]:
    """Paginated public archived threads for one channel (there's no guild-wide
    archived-threads endpoint, unlike active threads)."""
    threads = []
    before = None
    while True:
        params = {"limit": 100}
        if before:
            params["before"] = before
        data = client.get_json(f"/channels/{channel_id}/threads/archived/public", params=params)
        if not data:
            break
        batch = data.get("threads", [])
        threads.extend(batch)
        if not data.get("has_more") or not batch:
            break
        before = batch[-1]["thread_metadata"]["archive_timestamp"]
    return threads


def _deletion_check(client: DiscordREST, guild_id: str, all_channels: list[dict], ticket_channels: list[dict]) -> dict:
    """Phase 0 step 2: does Ticket King delete closed tickets, and if so, is
    there a transcript/log channel that holds the history instead? Everything
    here is read-only and scoped to metadata -- no message bodies fetched."""
    # (a) created_at distribution via snowflake decode -- free, no extra API call.
    created = sorted(_snowflake_to_dt(c["id"]) for c in ticket_channels)
    by_month = {}
    for dt in created:
        key = dt.strftime("%Y-%m")
        by_month[key] = by_month.get(key, 0) + 1

    # (b) scan ALL guild channels (names only) for a transcript/log channel.
    transcript_candidates = [
        {"id": c["id"], "name": c.get("name", "")}
        for c in all_channels
        if TRANSCRIPT_NAME_RE.search(c.get("name", ""))
    ]

    # (c) audit log CHANNEL_DELETE entries -- Discord retains ~45 days only.
    audit = client.get_json(
        f"/guilds/{guild_id}/audit-logs",
        params={"action_type": AUDIT_LOG_ACTION_CHANNEL_DELETE, "limit": 100},
    )
    delete_entries = (audit or {}).get("audit_log_entries", [])

    note = None
    if created and delete_entries and not transcript_candidates:
        note = (
            "Channel-delete events found in the ~45-day audit log window AND no "
            "transcript/log channel was found by name. Ticket King is likely "
            "deleting closed tickets with no on-server backup -- older history "
            "probably only survives in Freshdesk, if at all. Ask John to check "
            "Ticket King's own dashboard/config for its 'delete on close' vs "
            "'archive/transcript' setting to confirm."
        )
    elif transcript_candidates:
        note = (
            f"Found {len(transcript_candidates)} channel(s) that look like a "
            "transcript/log channel by name -- ask John whether Ticket King posts "
            "closed-ticket transcripts there, and whether to include it in Phase 1 fetch."
        )

    return {
        "created_at_month_distribution": by_month,
        "earliest_ticket_channel": created[0].isoformat() if created else None,
        "latest_ticket_channel": created[-1].isoformat() if created else None,
        "transcript_channel_candidates": transcript_candidates,
        "audit_log_channel_delete_count_last_100": len(delete_entries),
        "note": note or "No strong signal either way -- confirm with John / Ticket King's own settings.",
    }


def discover():
    env = _require_env("DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "DISCORD_TICKETS_CATEGORY_ID", "DISCORD_STAFF_ROLE_ID")
    client = DiscordREST(env["DISCORD_BOT_TOKEN"])
    guild_id = env["DISCORD_GUILD_ID"]
    category_id = env["DISCORD_TICKETS_CATEGORY_ID"]

    print(f"[info] listing channels for guild {guild_id} ...")
    all_channels = _list_guild_channels(client, guild_id)

    category = next((c for c in all_channels if c["id"] == category_id and c["type"] == CHANNEL_TYPE_CATEGORY), None)
    if category is None:
        print(f"[error] no category channel with id {category_id} found in this guild -- double-check DISCORD_TICKETS_CATEGORY_ID", file=sys.stderr)
        sys.exit(1)
    print(f"[info] tickets category: \"{category['name']}\" (id={category_id})")

    ticket_channels = [c for c in all_channels if c.get("parent_id") == category_id]
    print(f"[info] {len(ticket_channels)} channel(s) directly under this category")

    print("[info] listing active threads for the guild ...")
    active_threads = _list_active_threads(client, guild_id)
    ticket_channel_ids = {c["id"] for c in ticket_channels}
    active_ticket_threads = [t for t in active_threads if t.get("parent_id") in ticket_channel_ids]
    print(f"[info] {len(active_ticket_threads)} active thread(s) under ticket channels")

    print("[info] listing archived threads per ticket channel (paginated) ...")
    archived_ticket_threads = []
    for c in ticket_channels:
        archived = _list_archived_threads(client, c["id"])
        archived_ticket_threads.extend(archived)
    print(f"[info] {len(archived_ticket_threads)} archived thread(s) under ticket channels")

    print("[info] running deletion check (audit log + transcript-channel name scan) ...")
    deletion_check = _deletion_check(client, guild_id, all_channels, ticket_channels)

    OUT_DIR.mkdir(exist_ok=True)
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "guild_id": guild_id,
        "category": {"id": category["id"], "name": category["name"]},
        "ticket_channels": [
            {
                "id": c["id"],
                "name": c.get("name", ""),
                "created_at": _snowflake_to_dt(c["id"]).isoformat(),
            }
            for c in ticket_channels
        ],
        "active_ticket_threads": [
            {"id": t["id"], "name": t.get("name", ""), "parent_id": t.get("parent_id")}
            for t in active_ticket_threads
        ],
        "archived_ticket_threads": [
            {"id": t["id"], "name": t.get("name", ""), "parent_id": t.get("parent_id")}
            for t in archived_ticket_threads
        ],
        "counts": {
            "ticket_channels": len(ticket_channels),
            "active_ticket_threads": len(active_ticket_threads),
            "archived_ticket_threads": len(archived_ticket_threads),
            "total_all_guild_channels": len(all_channels),
        },
        "deletion_check": deletion_check,
    }
    out_path = OUT_DIR / "channels_audit.json"
    with open(out_path, "w") as f:
        json.dump(audit, f, indent=2)

    print("\n[info] ==== SUMMARY ====")
    print(f"  Category:            {category['name']}  (id={category_id})")
    print(f"  Ticket channels:     {len(ticket_channels)}")
    print(f"  Active threads:      {len(active_ticket_threads)}")
    print(f"  Archived threads:    {len(archived_ticket_threads)}")
    print(f"  Earliest channel:    {deletion_check['earliest_ticket_channel']}")
    print(f"  Latest channel:      {deletion_check['latest_ticket_channel']}")
    print(f"  Transcript channel(s) found: {len(deletion_check['transcript_channel_candidates'])}")
    for tc in deletion_check["transcript_channel_candidates"]:
        print(f"    - {tc['name']} (id={tc['id']})")
    print(f"  CHANNEL_DELETE events in last 100 audit-log entries: {deletion_check['audit_log_channel_delete_count_last_100']}")
    print(f"  Note: {deletion_check['note']}")
    print(f"\n[info] wrote {out_path}")
    print(
        "\n[info] STOP -- per SHADOW_BACKFILL_SPEC.md Phase 0, this is a review gate.\n"
        "        Confirm with John that this is the right category and these are the\n"
        "        right ticket channels, and decide whether to include a transcript\n"
        "        channel (if one was found above) before Phase 1 (fetch) is built."
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["discover"], help="Only 'discover' (Phase 0) is implemented so far -- see SHADOW_BACKFILL_SPEC.md")
    args = ap.parse_args()
    if args.command == "discover":
        discover()


if __name__ == "__main__":
    main()
