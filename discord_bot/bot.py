"""Discord adapter -- spec section 5. Thin: it calls the exact same
app.router.answer() the web widget calls (imported directly, same codebase/deploy --
no HTTP hop needed since this runs as a second process in the same Railway service).

Flow: message in a tracked channel/thread or DM -> router.answer() -> reply in-thread.
New question in a channel -> opens a thread (free ticketing, no ticket bot needed).
Any staff message in a thread pauses the bot there; `!resume` un-pauses.
Bot reacts to its own answers with 👍/👎; those reactions are logged as feedback.
Tier-3 escalations ping the staff role in a private staff channel.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord
from discord.ext import commands

from app import db, router
from app.config import (
    DISCORD_BOT_TOKEN, DISCORD_STAFF_ROLE_ID, DISCORD_ESCALATION_CHANNEL_ID,
    DISCORD_TICKETS_CHANNEL_ID,
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# in-memory cache of "this discord message id -> supportbot message_id" for reaction feedback.
# Small and short-lived (only recent bot replies matter) -- fine as a process-local dict;
# unlike scan_jobs in play-review-responder this isn't shared state across workers because
# the Discord bot only ever runs as a single process (one gateway connection per bot token).
_reply_message_map: dict[int, int] = {}


# DISCORD_STAFF_ROLE_ID may hold more than one role id, comma-separated (e.g. a
# "Moderator" role and a separate "Staff Volunteer" role) -- either one counts as
# staff for pausing the bot and getting pinged on Tier-3 escalations.
_STAFF_ROLE_IDS = {rid.strip() for rid in DISCORD_STAFF_ROLE_ID.split(",") if rid.strip()}


def _is_staff(member: discord.Member) -> bool:
    if not _STAFF_ROLE_IDS:
        return member.guild_permissions.manage_messages
    return any(str(r.id) in _STAFF_ROLE_IDS for r in getattr(member, "roles", []))


@bot.event
async def on_ready():
    print(f"[info] logged in as {bot.user} (id={bot.user.id})")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    await bot.process_commands(message)
    if message.content.startswith("!"):
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_thread = isinstance(message.channel, discord.Thread)

    # Scope: only actively answer in the configured tickets channel (+ threads
    # opened under it) and in DMs -- spec section 5 ("listens in your support
    # channel(s), ticket threads, and DMs"). Stays quiet everywhere else. If
    # DISCORD_TICKETS_CHANNEL_ID is unset, no restriction is applied (fine for
    # a quick local test, not for a real server with more than one channel).
    if DISCORD_TICKETS_CHANNEL_ID and not is_dm:
        if is_thread:
            in_scope = str(getattr(message.channel, "parent_id", "")) == DISCORD_TICKETS_CHANNEL_ID
        else:
            in_scope = str(message.channel.id) == DISCORD_TICKETS_CHANNEL_ID
        if not in_scope:
            return

    external_id = str(message.channel.id)

    conn = db.get_conn()
    convo = conn.execute(
        "SELECT id, status FROM conversations WHERE channel='discord' AND external_id=?",
        (external_id,),
    ).fetchone()

    # Staff talking in an existing thread -> pause the bot there, don't auto-answer.
    if convo and not is_dm and isinstance(message.author, discord.Member) and _is_staff(message.author):
        if convo["status"] == "open":
            conn.execute("UPDATE conversations SET status='paused' WHERE id=?", (convo["id"],))
            conn.commit()
            print(f"[info] conversation {convo['id']} paused by staff message")
        return

    if convo and convo["status"] == "paused":
        return  # human has the wheel; !resume brings the bot back

    # New question outside a thread -> open a thread so this becomes free ticketing.
    target_channel = message.channel
    if not is_dm and not is_thread:
        try:
            thread = await message.create_thread(name=message.content[:80] or "Support question")
            target_channel = thread
            external_id = str(thread.id)
        except discord.HTTPException as e:
            print(f"[warn] couldn't create thread ({e!r}), replying inline")

    conv_id = router.get_or_create_conversation("discord", external_id)
    await target_channel.trigger_typing() if hasattr(target_channel, "trigger_typing") else None

    result = router.answer(message.content, conv_id)
    sent = await target_channel.send(result["text"])
    _reply_message_map[sent.id] = result["message_id"]

    for emoji in ("👍", "👎"):
        try:
            await sent.add_reaction(emoji)
        except discord.HTTPException:
            pass

    if result["escalate"] and DISCORD_ESCALATION_CHANNEL_ID:
        chan = bot.get_channel(int(DISCORD_ESCALATION_CHANNEL_ID))
        if chan:
            role_mention = " ".join(f"<@&{rid}>" for rid in _STAFF_ROLE_IDS) if _STAFF_ROLE_IDS else "@here"
            await chan.send(
                f"{role_mention} Tier-3 escalation from {message.author.mention}: "
                f"{sent.jump_url}\n> {message.content[:200]}"
            )


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    if str(payload.emoji) not in ("👍", "👎"):
        return
    message_id = _reply_message_map.get(payload.message_id)
    if message_id is None:
        return
    signal = "thumbs_up" if str(payload.emoji) == "👍" else "thumbs_down"
    with db.tx() as conn:
        conn.execute("INSERT INTO feedback (message_id, signal) VALUES (?, ?)", (message_id, signal))
    from datetime import date
    db.bump_metric(date.today().isoformat(), signal, 1)
    print(f"[info] feedback {signal} on message {message_id}")


@bot.command(name="resume")
async def resume(ctx: commands.Context):
    if not _is_staff(ctx.author):
        return
    external_id = str(ctx.channel.id)
    with db.tx() as conn:
        conn.execute(
            "UPDATE conversations SET status='open' WHERE channel='discord' AND external_id=?",
            (external_id,),
        )
    await ctx.send("Bot resumed for this thread.")


def main():
    if not DISCORD_BOT_TOKEN:
        print("[error] DISCORD_BOT_TOKEN not set", file=sys.stderr)
        sys.exit(1)
    db.init_db()
    from app import vectorstore
    for table in ("kb_articles", "canned", "answer_cache"):
        vectorstore.ensure_vec_table(table)
    bot.run(DISCORD_BOT_TOKEN)


def _run_in_thread():
    """Runs the bot's asyncio loop in this (non-main) thread. Deliberately uses
    bot.start() + a fresh event loop instead of bot.run() -- bot.run() installs
    SIGINT/SIGTERM handlers via loop.add_signal_handler(), which only works in
    the interpreter's main thread and would raise ValueError here."""
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(bot.start(DISCORD_BOT_TOKEN))
    except Exception as e:
        print(f"[error] Discord bot crashed: {e!r}")


def start_in_background_thread():
    """Called from app/main.py's FastAPI startup hook -- per the spec, this is
    ONE service, not two. Discord and the web widget must share the same SQLite
    file, which only works if they're the same process/container. (Railway
    volumes attach to a single service; splitting web/worker into separate
    Railway services would give each its own disk and silently fork the KB/
    conversation data in two.) No-ops if DISCORD_BOT_TOKEN is unset so the web
    service still runs fine without a Discord bot configured."""
    if not DISCORD_BOT_TOKEN:
        print("[info] DISCORD_BOT_TOKEN not set -- Discord bot disabled, web service runs standalone")
        return
    import threading
    t = threading.Thread(target=_run_in_thread, daemon=True, name="discord-bot")
    t.start()
    print("[info] Discord bot starting in background thread")


if __name__ == "__main__":
    main()
