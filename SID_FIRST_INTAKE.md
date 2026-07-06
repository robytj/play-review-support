# SID-first intake — the one change that makes support 10× faster to action

*Owner: Support + SupportBot. Status: recommendation for the team (§4B).*

## The key insight

Every support action we can take — check a purchase, verify a ban, restore an item,
look a player up at `admin.brx.indusgame.com/player/<SID>` — needs the player's **SID**
(their `shortId`). Right now most tickets don't carry one, so an agent has to hunt for
the player before they can even start.

We just backfilled SIDs for the historical tickets by matching the **sender email** to
`account.email.id` in Mongo. It worked, but it only resolved **~7% of emails
(138 / 2,050 → 168 tickets)**. The reason is structural, not fixable after the fact:

- a large share of players are **guest accounts with no email on file at all**;
- players routinely **email us from a different address** than the one on their game account;
- **Discord tickets carry no email** — only a Discord display name, which isn't in `account`.

So no amount of clever backfilling gets us to high coverage. **The leverage is at intake:
ask for the SID (or the registered email) the moment a ticket is created.** A SID the
player hands us needs zero lookup; a registered email resolves reliably on the first try.

## What to change (support team)

Make **"Player SID (or the email on your game account)"** a required first field on every
intake surface:

1. **Discord (Ticket King):** add it to the ticket-open form / first auto-prompt in the
   ticket channel ("Please paste your Player SID — find it in-game under Profile → your ID
   under your name"). This is the biggest gap today (Discord tickets have no email at all).
2. **Web support widget:** required field on the contact form.
3. **Freshdesk:** add a required "Player SID" custom field to the contact form / portal.
4. **Email:** the support auto-reply should ask for the SID if the message didn't include
   one, before an agent picks it up.

Tell players exactly where to find it: **in-game → Profile → the short code under their
nickname** (that's the `shortId`, e.g. `CS9DNY34`). One screenshot in each channel's
pinned/help text removes 90% of the "what's a SID?" back-and-forth.

## What we'll change (SupportBot — live ingestion)

The backfill resolver (`scripts/resolve_sids.py`) can run **at ingestion time** instead of
as a one-off, so every *new* ticket lands with `player_id` already set:

- On each new ticket (Discord bot message, web widget, Freshdesk webhook, inbound email),
  in order: (a) if the player supplied a SID, **validate** it against `account.shortId`
  and use it; (b) else if we have a sender/registered email, resolve `email.id → shortId`;
  (c) else leave blank and have the agent/bot ask (the SID-first gate below).
- Persist the resolved SID to `conversations.player_id` immediately, so the admin link and
  any future automated action are ready with no per-view lookup.
- Keep it cheap and within the DB rules: **direct match queries only** (`shortId` and
  `email.id` are both indexed), dedupe, and cache — never scan.

## SID-first gate (feeds Phase 6)

For the live agent, this becomes a **hard gate**: the bot determines/asks for the SID
**before** taking or suggesting any account-affecting action, and no approve-to-send
(Phase 6) is allowed on a ticket without a resolved SID. For historical review it's just
informational; for live it's a precondition.

**Net:** intake capture (team) + ingestion-time resolution (bot) means new tickets start
at ~100% SID coverage instead of ~7%, and every downstream action gets faster and safer.
