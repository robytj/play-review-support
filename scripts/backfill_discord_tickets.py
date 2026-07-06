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

    def get_json(self, path: str, params: dict = None, quiet: bool = False):
        resp = self.get(path, params=params)
        if resp.status_code != 200:
            if not quiet:
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


def _print_categories(all_channels, stream=sys.stderr):
    """List every category the bot can see with its child-channel count -- the
    map John needs to pick the right DISCORD_TICKETS_CATEGORY_ID(s)."""
    cats = [c for c in all_channels if c.get("type") == CHANNEL_TYPE_CATEGORY]
    counts = {}
    for c in all_channels:
        pid = c.get("parent_id")
        if pid:
            counts[pid] = counts.get(pid, 0) + 1
    print(f"[hint] categories visible in this guild ({len(cats)}):", file=stream)
    for c in sorted(cats, key=lambda x: counts.get(x["id"], 0), reverse=True):
        print(f"    id={c['id']}  channels={counts.get(c['id'],0):3d}  name=\"{c.get('name','')}\"", file=stream)
    if not cats:
        print("    (none visible -- likely a bot-permissions issue: the bot isn't in "
              "this guild or can't View Channels)", file=stream)


def peek(category_arg: str | None = None):
    """Read-only: print the child-channel NAMES under each requested tickets
    category, so John can confirm which categories actually hold per-player Ticket
    King channels (names look like a username / ticket number) vs normal discussion
    channels. Category ids come from --category (comma-separated) if given, else
    from DISCORD_TICKETS_CATEGORY_ID; if neither, the full category map is shown.
    No messages are fetched."""
    env = _require_env("DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID")
    client = DiscordREST(env["DISCORD_BOT_TOKEN"])
    guild_id = env["DISCORD_GUILD_ID"]
    all_channels = _list_guild_channels(client, guild_id)
    src = category_arg if category_arg else os.environ.get("DISCORD_TICKETS_CATEGORY_ID", "")
    wanted = {x.strip() for x in src.split(",") if x.strip()}
    cats = [c for c in all_channels if c.get("type") == CHANNEL_TYPE_CATEGORY and (not wanted or c["id"] in wanted)]
    if not cats:
        print("[warn] no matching categories; showing the full category map:")
        _print_categories(all_channels, stream=sys.stdout)
        return
    for cat in sorted(cats, key=lambda x: x.get("name", "").lower()):
        kids = [c for c in all_channels if c.get("parent_id") == cat["id"]]
        print(f"\n=== {cat.get('name','')}  (id={cat['id']}, {len(kids)} channels) ===")
        for c in sorted(kids, key=lambda x: x.get("name", "").lower()):
            print(f"    [{c.get('type')}] id={c['id']}  \"{c.get('name','')}\"")


def discover(category_arg: str | None = None):
    # --category (comma-separated) overrides the env var, so John can iterate on
    # the right category set without editing .env each time.
    need = ["DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "DISCORD_STAFF_ROLE_ID"]
    if not category_arg:
        need.append("DISCORD_TICKETS_CATEGORY_ID")
    env = _require_env(*need)
    client = DiscordREST(env["DISCORD_BOT_TOKEN"])
    guild_id = env["DISCORD_GUILD_ID"]
    # May be a single id or a comma-separated list -- this server routes tickets
    # into several topic categories, so support both.
    src = category_arg if category_arg else env["DISCORD_TICKETS_CATEGORY_ID"]
    category_ids = [x.strip() for x in src.split(",") if x.strip()]

    print(f"[info] listing channels for guild {guild_id} ...")
    all_channels = _list_guild_channels(client, guild_id)

    by_id = {c["id"]: c for c in all_channels}
    categories, bad = [], []
    for cid in category_ids:
        c = by_id.get(cid)
        if c and c.get("type") == CHANNEL_TYPE_CATEGORY:
            categories.append(c)
        else:
            bad.append((cid, c))
    if bad or not categories:
        for cid, c in bad:
            if c is not None:
                print(f"[error] id {cid} is channel type {c.get('type')} (\"{c.get('name','')}\"), "
                      f"not a category (type {CHANNEL_TYPE_CATEGORY}) -- use its parent category's id.", file=sys.stderr)
            else:
                print(f"[error] id {cid} is not among the {len(all_channels)} channels the bot can see "
                      "(wrong server, or the bot lacks View Channel on that private category).", file=sys.stderr)
        print(file=sys.stderr)
        _print_categories(all_channels)
        print("\n[hint] set DISCORD_TICKETS_CATEGORY_ID in local .env to one id, or several "
              "comma-separated ids, from the list above, then re-run discover. "
              "Tip: `python scripts/backfill_discord_tickets.py peek` lists the channel "
              "NAMES inside each category so you can confirm which hold real tickets.", file=sys.stderr)
        sys.exit(1)
    cat_id_set = {c["id"] for c in categories}
    print(f"[info] {len(categories)} tickets categor(y/ies): " +
          ", ".join(f"\"{c['name']}\" ({c['id']})" for c in categories))

    ticket_channels = [c for c in all_channels if c.get("parent_id") in cat_id_set]
    print(f"[info] {len(ticket_channels)} channel(s) directly under these categor(y/ies)")

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
        "categories": [{"id": c["id"], "name": c["name"]} for c in categories],
        "category": {"id": categories[0]["id"], "name": categories[0]["name"]},  # backward compat
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
        "category_ids": [c["id"] for c in categories],
    }
    out_path = OUT_DIR / "channels_audit.json"
    with open(out_path, "w") as f:
        json.dump(audit, f, indent=2)

    print("\n[info] ==== SUMMARY ====")
    print("  Categories:          " + ", ".join(f"{c['name']} ({c['id']})" for c in categories))
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


def sample(channel_arg: str, limit: int):
    """Read-only: dump the first N messages of one or more channels so we can see
    their structure before building parsers (esp. transcript/log channels: are
    Ticket King transcripts embeds, or attached .html/.txt files?). Also verifies
    the bot can actually read message history there (else fetch will 403). Writes
    backfill_out/sample_<id>.json and prints a compact per-message summary."""
    env = _require_env("DISCORD_BOT_TOKEN")
    client = DiscordREST(env["DISCORD_BOT_TOKEN"])
    OUT_DIR.mkdir(exist_ok=True)
    for cid in [x.strip() for x in channel_arg.split(",") if x.strip()]:
        resp = client.get(f"/channels/{cid}/messages", params={"limit": limit})
        if resp.status_code != 200:
            print(f"[warn] channel {cid}: GET messages -> {resp.status_code} {resp.text[:150]} "
                  "(bot likely can't read this channel -- fetch would get the same)")
            continue
        msgs = resp.json()
        json.dump(msgs, open(OUT_DIR / f"sample_{cid}.json", "w"), indent=2, ensure_ascii=False)
        print(f"\n=== channel {cid}: {len(msgs)} message(s) (newest first) ===")
        for m in msgs:
            a = m.get("author") or {}
            who = f"{a.get('username','?')}{'[bot]' if a.get('bot') else ''}"
            embeds = m.get("embeds") or []
            emb = ""
            if embeds:
                titles = [e.get("title") or "(no title)" for e in embeds]
                fnames = [f.get("name","") for e in embeds for f in (e.get("fields") or [])]
                emb = f" embeds={len(embeds)} titles={titles} fields={fnames[:8]}"
            atts = [att.get("filename","") for att in (m.get("attachments") or [])]
            att = f" attachments={atts}" if atts else ""
            content = (m.get("content") or "").replace("\n", " ")[:100]
            print(f"  - {who}: {content!r}{emb}{att}")
        print(f"[info] full dump -> {OUT_DIR / f'sample_{cid}.json'}")


# ============================ Phase 1 — fetch history ============================
# REST GET only (constraint #1). Runs on John's machine after he approves the
# Phase 0 audit. Writes raw dumps first, then ingests into SQLite.

def _get_messages_paginated(client: DiscordREST, channel_id: str):
    """All messages in a channel/thread, oldest-first, 100/page via the `before`
    cursor. Returns (messages, forbidden) -- forbidden=True if the bot can't read
    the channel (403), so the caller can count+skip quietly instead of a wall of
    warnings. Honors rate limits through DiscordREST.get()."""
    out, before, forbidden = [], None, False
    while True:
        params = {"limit": 100}
        if before:
            params["before"] = before
        resp = client.get(f"/channels/{channel_id}/messages", params=params)
        if resp.status_code == 403:
            forbidden = True
            break
        if resp.status_code != 200:
            print(f"[warn] GET messages {channel_id} -> {resp.status_code}: {resp.text[:150]}")
            break
        batch = resp.json()
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        before = batch[-1]["id"]  # messages come newest-first; page further back
        time.sleep(0.3)
    out.sort(key=lambda m: int(m["id"]))  # oldest-first for readable transcripts
    return out, forbidden


def _parse_card_rest(message: dict):
    """REST-JSON equivalent of discord_bot.bot._parse_ticket_king_card. Reuses the
    SAME compiled field regexes from the bot (lazy import -> single source of truth,
    can't drift) applied to raw embed-field dicts. Returns (player_id, question)."""
    from discord_bot.bot import _ACCOUNT_ID_FIELD_RE, _QUESTION_FIELD_RE
    for embed in message.get("embeds") or []:
        player_id = question = None
        for f in embed.get("fields") or []:
            name, value = f.get("name") or "", (f.get("value") or "").strip()
            if _ACCOUNT_ID_FIELD_RE.search(name):
                player_id = value
            elif _QUESTION_FIELD_RE.search(name):
                question = value
        if player_id or question:
            return player_id, question
    return None, None


def _member_is_staff(client: DiscordREST, guild_id: str, user_id: str, staff_ids: set, cache: dict) -> bool:
    if user_id in cache:
        return cache[user_id]
    # quiet: a 404 just means the user left the guild -> treat as non-staff
    m = client.get_json(f"/guilds/{guild_id}/members/{user_id}", quiet=True)
    roles = set((m or {}).get("roles", []))
    is_staff = bool(roles & staff_ids)
    cache[user_id] = is_staff
    return is_staff


def fetch(confirm_category: str, include_transcript: bool = False):
    audit_path = OUT_DIR / "channels_audit.json"
    if not audit_path.exists():
        print(f"[error] {audit_path} not found -- run `discover` first (Phase 0).", file=sys.stderr)
        sys.exit(1)
    audit = json.load(open(audit_path))
    audited_cat_ids = audit.get("category_ids") or [audit["category"]["id"]]
    # accept a single id or comma-separated ids; every one must be in the audit
    confirmed = {x.strip() for x in confirm_category.split(",") if x.strip()}
    if confirmed != set(audited_cat_ids):
        print(f"[error] --confirm-category {sorted(confirmed)} != audited categories "
              f"{sorted(audited_cat_ids)}. Re-run discover / pass the exact id(s). Refusing to fetch.",
              file=sys.stderr)
        sys.exit(1)

    env = _require_env("DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "DISCORD_TICKETS_CATEGORY_ID", "DISCORD_STAFF_ROLE_ID")
    client = DiscordREST(env["DISCORD_BOT_TOKEN"])
    guild_id = env["DISCORD_GUILD_ID"]
    staff_ids = {r.strip() for r in env["DISCORD_STAFF_ROLE_ID"].split(",") if r.strip()}

    # channels to fetch: ticket channels + their threads (+ optional transcript channel)
    targets = [(c["id"], c["name"]) for c in audit["ticket_channels"]]
    targets += [(t["id"], t.get("name", "")) for t in audit.get("active_ticket_threads", [])]
    targets += [(t["id"], t.get("name", "")) for t in audit.get("archived_ticket_threads", [])]
    if include_transcript:
        for tc in audit.get("deletion_check", {}).get("transcript_channel_candidates", []):
            targets.append((tc["id"], tc["name"] + " (transcript)"))

    from app import db
    db.init_db()
    conn = db.get_conn()
    existing = {r[0] for r in conn.execute(
        "SELECT external_id FROM conversations WHERE channel='discord'").fetchall()}

    raw_dir = OUT_DIR / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    role_cache: dict = {}
    n_tickets = n_sid = n_question = n_staff = n_skipped = n_forbidden = 0

    for cid, cname in targets:
        msgs, forbidden = _get_messages_paginated(client, cid)
        if forbidden:
            n_forbidden += 1
            continue
        json.dump(msgs, open(raw_dir / f"{cid}.json", "w"), indent=2, ensure_ascii=False)
        if not msgs:
            n_skipped += 1
            continue
        # find the Ticket King card
        player_id = question = None
        for m in msgs:
            pid, q = _parse_card_rest(m)
            player_id = player_id or pid
            question = question or q
            if player_id and question:
                break
        # Skip non-ticket channels like the "🎟️┃tickets" panel: no card question
        # AND no human/player content, just the bot's panel embed. Never a ticket.
        non_bot = [m for m in msgs
                   if not (m.get("author") or {}).get("bot") and (m.get("content") or "").strip()]
        if not question and not non_bot:
            n_skipped += 1
            continue
        if cid in existing:
            n_skipped += 1
            continue

        # This server's Ticket King card often has no SID/question fields (players
        # just type). Fall back to the first player message for a display question.
        display_q = question or (non_bot[0].get("content") or "").strip()
        cur = conn.execute(
            "INSERT INTO conversations (channel, origin, external_id, status, context, player_id) "
            "VALUES ('discord','backfill',?,'resolved',?,?)",
            (cid, json.dumps({"source": "discord", "category": "Discord",
                              "channel_name": cname, "question": display_q}, ensure_ascii=False),
             player_id))
        conv_id = cur.lastrowid
        n_tickets += 1
        if player_id:
            n_sid += 1
        if question:
            n_question += 1
            conn.execute(
                "INSERT INTO messages (conversation_id, role, tier_used, text, author_name) VALUES (?,?,?,?,?)",
                (conv_id, "user", None, question, player_id or "player"))

        had_staff = False
        for m in msgs:
            author = m.get("author") or {}
            # skip bots (Ticket King card already captured; our own/other bot noise ignored)
            if author.get("bot"):
                continue
            content = (m.get("content") or "").strip()
            if not content:
                continue
            uid = author.get("id", "")
            name = author.get("global_name") or author.get("username") or "user"
            if _member_is_staff(client, guild_id, uid, staff_ids, role_cache):
                role = "human"; had_staff = True
            else:
                # the player's own follow-ups; the card question is already stored
                if question and content == question:
                    continue
                role = "user"
            conn.execute(
                "INSERT INTO messages (conversation_id, role, tier_used, text, author_name) VALUES (?,?,?,?,?)",
                (conv_id, role, None, content, name))
        if had_staff:
            n_staff += 1
        conn.commit()

    print("\n[info] ==== FETCH SUMMARY ====")
    print(f"  channels/threads scanned : {len(targets)}")
    print(f"  tickets ingested         : {n_tickets}")
    print(f"  ... with a player SID    : {n_sid}")
    print(f"  ... with a card question : {n_question}  (this Ticket King has no question field; player's 1st message is used instead)")
    print(f"  ... with a staff reply   : {n_staff}")
    print(f"  skipped (empty/dupe)     : {n_skipped}")
    print(f"  inaccessible (403)       : {n_forbidden}  (bot lacks read access -- e.g. the 《 TICKETS 》 category)")
    print(f"\n[info] raw dumps -> {raw_dir}")
    print("[info] STOP -- Phase 1 gate. Sample raw dumps + dashboard feed with John before replay.")


# ============================ Phase 3 — replay ==================================
# Uses the PURE router.suggest() (no live side effects). Persists exactly one
# suggestion per ticket, ever (constraint 6). Runs on John's machine / Railway
# (needs the embedding model + Anthropic key -- neither reachable from the sandbox).

def replay(limit: int, source: str | None, tier3_only: bool = False):
    from app import db, embeddings, router

    db.init_db()
    conn = db.get_conn()
    src_where = "AND c.channel = ?" if source else ""
    src_params = (source,) if source else ()
    if tier3_only:
        # Re-evaluate ONLY tickets whose LATEST suggestion is a tier-3 gap (e.g.
        # after publishing more KB). Creates NEW rows with supersedes_id -- the
        # originals are never overwritten (constraint 6).
        rows = conn.execute(
            f"""
            SELECT c.id AS cid, c.channel,
                   (SELECT text FROM messages WHERE conversation_id=c.id AND role='user'  ORDER BY id ASC LIMIT 1) AS question,
                   (SELECT text FROM messages WHERE conversation_id=c.id AND role='human' ORDER BY id ASC LIMIT 1) AS staff_answer,
                   ls.id AS supersedes_id
            FROM conversations c
            JOIN (SELECT conversation_id, MAX(id) AS id FROM suggestions GROUP BY conversation_id) lm
                 ON lm.conversation_id = c.id
            JOIN suggestions ls ON ls.id = lm.id
            WHERE c.origin='backfill' {src_where} AND ls.tier = 3
            """,
            src_params,
        ).fetchall()
    else:
        # First pass: backfilled tickets with a player question and NO suggestion yet.
        rows = conn.execute(
            f"""
            SELECT c.id AS cid, c.channel,
                   (SELECT text FROM messages WHERE conversation_id=c.id AND role='user'  ORDER BY id ASC LIMIT 1) AS question,
                   (SELECT text FROM messages WHERE conversation_id=c.id AND role='human' ORDER BY id ASC LIMIT 1) AS staff_answer,
                   NULL AS supersedes_id
            FROM conversations c
            WHERE c.origin='backfill' {src_where}
              AND NOT EXISTS (SELECT 1 FROM suggestions s WHERE s.conversation_id=c.id)
            """,
            src_params,
        ).fetchall()
    todo = [r for r in rows if (r["question"] or "").strip()]
    mode = "tier-3 re-eval" if tier3_only else "first-pass"
    print(f"[info] {mode}: {len(todo)} ticket(s) to (re)generate (source={source or 'all'})")
    print(f"[info] cost estimate: <= {len(todo) if limit==0 else min(limit,len(todo))} Haiku calls "
          "(<=1/ticket, tier<2 costs nothing). Embeddings are local.")
    print("[warn] BACK UP data/supportbot.db before a full run (see spec §4).")
    batch = todo if limit == 0 else todo[:limit]
    if not batch:
        print("[info] nothing to do.")
        return
    print(f"[info] generating {len(batch)} suggestion(s) (limit={'none' if limit==0 else limit}) ...")

    made = 0
    for r in batch:
        res = router.suggest(r["question"])
        conn.execute(
            "INSERT INTO suggestions (conversation_id, source, question, suggested_answer, tier, "
            "retrieved_chunks, staff_answer, status, supersedes_id) VALUES (?,?,?,?,?,?,?, 'pending', ?)",
            (r["cid"], r["channel"], r["question"], res["text"], res["tier"],
             json.dumps(res.get("chunks") or [], ensure_ascii=False), r["staff_answer"], r["supersedes_id"]))
        conn.commit()
        made += 1

    # ---- learnings report ----
    def _cos(a, b):
        va, vb = embeddings.embed(a), embeddings.embed(b)
        dot = sum(x*y for x, y in zip(va, vb))
        na = sum(x*x for x in va) ** 0.5 or 1.0
        nb = sum(x*x for x in vb) ** 0.5 or 1.0
        return dot/(na*nb)

    # count only the LATEST suggestion per conversation (ignore superseded ones)
    sugg = conn.execute(
        "SELECT s.tier, s.suggested_answer, s.staff_answer, c.channel "
        "FROM suggestions s "
        "JOIN (SELECT conversation_id, MAX(id) AS id FROM suggestions GROUP BY conversation_id) lm ON lm.id=s.id "
        "JOIN conversations c ON c.id=s.conversation_id "
        "WHERE c.origin='backfill'" + (" AND c.channel=?" if source else ""),
        src_params).fetchall()
    tier_dist = {0: 0, 1: 0, 2: 0, 3: 0}
    strong, weak = [], []
    for s in sugg:
        tier_dist[s["tier"]] = tier_dist.get(s["tier"], 0) + 1
        if s["staff_answer"] and s["tier"] < 3:
            sim = _cos(s["suggested_answer"], s["staff_answer"])
            (strong if sim >= 0.6 else weak).append((sim, s["channel"], s["tier"]))
    strong.sort(reverse=True); weak.sort()
    OUT_DIR.mkdir(exist_ok=True)
    with open(OUT_DIR / "replay_learnings.md", "w") as f:
        f.write("# Replay learnings\n\n")
        f.write(f"Suggestions generated this run: {made}\n\n")
        f.write("## Tier distribution (0-2 = KB had something, 3 = KB gap)\n\n")
        for t in (0, 1, 2, 3):
            f.write(f"- tier {t}: {tier_dist.get(t,0)}\n")
        f.write(f"\n## Strong responses (agree with staff, cosine >= 0.6): {len(strong)}\n\n")
        for sim, ch, t in strong[:25]:
            f.write(f"- {sim:.2f}  [{ch} tier{t}]\n")
        f.write(f"\n## Needs human training (tier 3 gaps + disagreements): "
                f"{tier_dist.get(3,0)} gaps + {len(weak)} low-agreement\n\n")
        for sim, ch, t in weak[:25]:
            f.write(f"- {sim:.2f}  [{ch} tier{t}] KB answer diverges from staff\n")
    print(f"[info] generated {made} suggestion(s); wrote {OUT_DIR/'replay_learnings.md'}")
    print("[info] STOP -- Phase 3 gate. Review the learnings report + Ticket Review grid.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    dp = sub.add_parser("discover", help="Phase 0: list ticket channels + deletion check (read-only)")
    dp.add_argument("--category", default=None, help="comma-separated category id(s); overrides DISCORD_TICKETS_CATEGORY_ID")
    pp = sub.add_parser("peek", help="Read-only: list child-channel names under the given tickets categor(y/ies)")
    pp.add_argument("--category", default=None, help="comma-separated category id(s) to peek; else uses env, else shows full map")
    sp = sub.add_parser("sample", help="Read-only: dump first N messages of a channel to inspect structure / verify read access")
    sp.add_argument("--channel", required=True, help="comma-separated channel id(s) to sample")
    sp.add_argument("--limit", type=int, default=15, help="messages per channel (default 15)")
    fp = sub.add_parser("fetch", help="Phase 1: fetch history for audited channels, ingest as tickets")
    fp.add_argument("--confirm-category", required=True, help="must match category id in channels_audit.json")
    fp.add_argument("--include-transcript", action="store_true", help="also fetch the transcript channel found in Phase 0")
    rp = sub.add_parser("replay", help="Phase 3: generate a persistent suggestion per ticket + learnings report")
    rp.add_argument("--limit", type=int, default=20, help="0 = all; default 20 sample")
    rp.add_argument("--source", choices=["discord", "freshdesk", "email"], default=None)
    rp.add_argument("--tier3-only", action="store_true", dest="tier3_only",
                    help="re-evaluate only tickets whose latest suggestion is tier 3 (e.g. after publishing KB); "
                         "creates new rows with supersedes_id, originals kept")
    args = ap.parse_args()

    if args.command == "discover":
        discover(args.category)
    elif args.command == "peek":
        peek(args.category)
    elif args.command == "sample":
        sample(args.channel, args.limit)
    elif args.command == "fetch":
        fetch(args.confirm_category, args.include_transcript)
    elif args.command == "replay":
        replay(args.limit, args.source, args.tier3_only)


if __name__ == "__main__":
    main()
