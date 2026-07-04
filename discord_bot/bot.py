"""Discord adapter -- spec section 5. Thin: it calls the exact same
app.router.answer() the web widget calls (imported directly, same codebase/deploy --
no HTTP hop needed since this runs as a second process in the same Railway service).

PERMANENTLY READ-ONLY (2026-07-04): this bot never posts, replies, or DMs on
Discord. It only reads messages, drafts a suggested response via router.answer(),
and logs it -- staff read the suggestion on the Support tab's ticket grid and
reply to the player in Discord themselves. The only thing it ever writes back to
Discord is an emoji reaction (👀 on a new ticket, ✅ on `!resume`), never message
text. This replaces an earlier design that had a `shadow_mode` toggle meant to be
flipped off once trusted -- that toggle is gone on purpose: on 2026-07-04 an env
var rename briefly disabled channel scoping on a version of this bot that COULD
reply, and it spammed the live server with a repeated holding message on every
message in every channel it could see (see project memory / incident notes).
Making read-only unconditional means there is no code path left that can ever
repeat that failure mode, regardless of config or env state.

Tickets on this server are opened by a separate bot (Ticket King), which creates a
brand-new private channel per ticket under one category and posts the ticket itself
as an embed *from its own bot account* -- so we can't blanket-ignore bot-authored
messages like a simpler setup would; instead we ignore only our own messages, and
for any other bot/app message we try to parse it as a Ticket King card (see
_parse_ticket_king_card) and ignore it if it doesn't look like one.

Any staff message in a tracked channel/thread pauses suggestion generation there
(no point spending a Haiku call on a conversation a human already has); `!resume`
un-pauses it. Tier-3 escalations are marked in the DB (app/router.py) so the
conversation shows up in the Support tab's escalation queue -- no Discord ping,
since pinging would itself be a message send.

Feedback (👍/👎ing a reply) used to be collected in Discord because the bot's own
message was there to react to. Now that nothing gets posted, that path is gone --
if you want thumbs-up/down on suggested responses, add it as a button in the
Support tab (POST /api/feedback) instead.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord
from discord.ext import commands

from app import db, router
from app.config import DISCORD_BOT_TOKEN, DISCORD_STAFF_ROLE_ID, DISCORD_TICKETS_CATEGORY_ID

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# DISCORD_STAFF_ROLE_ID may hold more than one role id, comma-separated (e.g. a
# "Moderator" role and a separate "Staff Volunteer" role) -- either one counts as
# staff for pausing suggestion generation.
_STAFF_ROLE_IDS = {rid.strip() for rid in DISCORD_STAFF_ROLE_ID.split(",") if rid.strip()}


def _is_staff(member: discord.Member) -> bool:
    if not _STAFF_ROLE_IDS:
        return member.guild_permissions.manage_messages
    return any(str(r.id) in _STAFF_ROLE_IDS for r in getattr(member, "roles", []))


_ACCOUNT_ID_FIELD_RE = re.compile(r"id\s+da\s+sua\s+conta", re.IGNORECASE)   # "Qual é o ID da sua conta?"
_QUESTION_FIELD_RE = re.compile(r"d[uú]vida|problema", re.IGNORECASE)         # "...sua dúvida ou problema?"


def _parse_ticket_king_card(message: discord.Message):
    """Ticket King posts the ticket itself as an embed from its own bot account
    when a player opens one -- title 'Ticket Aberto', with fields like 'Qual é
    o ID da sua conta?' (-> the player's account id) and 'Qual é a sua dúvida
    ou problema?' (-> their actual question). Returns (player_id, question),
    either of which may be None. Both None means this message doesn't look
    like a Ticket King card at all (e.g. some other bot/app's unrelated
    message in the same channel) -- callers should ignore it in that case."""
    for embed in message.embeds:
        player_id, question = None, None
        for f in embed.fields or []:
            name, value = f.name or "", (f.value or "").strip()
            if _ACCOUNT_ID_FIELD_RE.search(name):
                player_id = value
            elif _QUESTION_FIELD_RE.search(name):
                question = value
        if player_id or question:
            return player_id, question
    return None, None


def _in_tickets_scope(channel) -> bool:
    """True if this channel/thread lives under DISCORD_TICKETS_CATEGORY_ID.
    Tickets on this server are opened by a separate bot (Ticket King), which
    creates one brand-new private channel per ticket inside a single category
    -- so we match on category, not on a single fixed channel id. Threads
    check their parent channel's category. Unset category -> no restriction
    (fine for a quick local test with a simpler server; on the live server
    this should always be set)."""
    if not DISCORD_TICKETS_CATEGORY_ID:
        return True
    cat_id = getattr(channel, "category_id", None)
    if cat_id is not None:
        return str(cat_id) == DISCORD_TICKETS_CATEGORY_ID
    parent = getattr(channel, "parent", None)  # threads expose their parent channel here
    if parent is not None:
        return str(getattr(parent, "category_id", "")) == DISCORD_TICKETS_CATEGORY_ID
    return False


@bot.event
async def on_ready():
    print(f"[info] logged in as {bot.user} (id={bot.user.id}) -- read-only mode, no auto-replies")


@bot.event
async def on_message(message: discord.Message):
    ticket_player_id = None
    ticket_question = None

    if message.author.bot:
        if bot.user and message.author.id == bot.user.id:
            return  # never process our own messages
        ticket_player_id, ticket_question = _parse_ticket_king_card(message)
        if not ticket_player_id and not ticket_question:
            return  # some other bot/app's message, not a ticket card -- ignore
    else:
        await bot.process_commands(message)
        if message.content.startswith("!"):
            return

    is_dm = isinstance(message.channel, discord.DMChannel)

    # Scope: only actively watch the configured tickets category (+ its threads)
    # and DMs -- spec section 5 ("listens in your support channel(s), ticket
    # threads, and DMs"). Stays quiet everywhere else.
    if not is_dm and not _in_tickets_scope(message.channel):
        return

    external_id = str(message.channel.id)

    conn = db.get_conn()
    convo = conn.execute(
        "SELECT id, status FROM conversations WHERE channel='discord' AND external_id=?",
        (external_id,),
    ).fetchone()

    # Staff talking in an existing thread -> pause suggestion generation there,
    # a human already has the wheel.
    if convo and not is_dm and isinstance(message.author, discord.Member) and _is_staff(message.author):
        if convo["status"] == "open":
            conn.execute("UPDATE conversations SET status='paused' WHERE id=?", (convo["id"],))
            conn.commit()
            print(f"[info] conversation {convo['id']} paused by staff message")
        return

    if convo and convo["status"] in ("paused", "escalated"):
        # human has the wheel -- 'paused' from a staff reply, 'escalated' because
        # router.answer() already hit tier 3 once on this conversation. Either way
        # stop generating new suggestions until !resume brings it back.
        return

    # The actual question to route: Ticket King's card carries it in a field
    # (message.content on that message is usually just an @-mention), a plain
    # follow-up message from the player carries it in message.content directly.
    question_text = ticket_question or message.content
    if not question_text:
        # A ticket card with an account id but no question yet (unusual, but
        # possible) -- still worth remembering the player id for later messages.
        if ticket_player_id:
            router.get_or_create_conversation("discord", external_id, player_id=ticket_player_id)
        return

    # Ingest the ticket and run it through the full router so the suggested
    # response shows up in the Support tab's ticket grid exactly like a live
    # answer would -- but never post anything back to Discord except a 👀
    # reaction, so staff can see the bot is alive and watching without it ever
    # speaking for itself.
    conv_id = router.get_or_create_conversation("discord", external_id, player_id=ticket_player_id)
    router._log_message(conv_id, "user", None, question_text)
    result = router.answer(question_text, conv_id)
    print(
        f"[suggest] conv={conv_id} player_id={ticket_player_id!r} tier={result['tier']} "
        f"escalate={result['escalate']} suggested={result['text'][:150]!r}"
    )
    try:
        await message.add_reaction("👀")
    except discord.HTTPException as e:
        print(f"[warn] couldn't add reaction ({e!r})")


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
    # Acknowledge with a reaction, not a sent message -- the bot never authors
    # message text in Discord, even for admin utility commands.
    try:
        await ctx.message.add_reaction("✅")
    except discord.HTTPException as e:
        print(f"[warn] couldn't add resume reaction ({e!r})")


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
    print("[info] Discord bot starting in background thread (read-only mode)")


if __name__ == "__main__":
    main()
