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


def _is_staff(member: discord.Member) -> bool:
    if not DISCORD_STAFF_ROLE_ID:
        return member.guild_permissions.manage_messages
    return any(str(r.id) == DISCORD_STAFF_ROLE_ID for r in getattr(member, "roles", []))


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
            role_mention = f"<@&{DISCORD_STAFF_ROLE_ID}>" if DISCORD_STAFF_ROLE_ID else "@here"
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


if __name__ == "__main__":
    main()
