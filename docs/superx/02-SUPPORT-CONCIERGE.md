# SuperX — 02 · Support concierge (the player side)

Support on SuperX is a **concierge you chat with**, not a help page with a chat bolted on. It
knows who you are and which game you're in, and it can get things done.

## 1 · Where it appears

| Surface | URL | When |
|---|---|---|
| **From the game** | `<game>.superx.gg/support?lt=…` | Player taps Support in the game. Opens signed in (01 §2.2), straight into the chat, game already known |
| **Concierge button** | every page of every store and the Hub | Always visible, bottom-right; labelled "Ask" with a live dot, not a "?" icon |
| **Store `/support` page** | `towerconquest.superx.gg/support` etc. | Full-height chat plus FAQ; replaces today's FAQ + email (MaskGun) and anonymous chat (TC) |
| **Hub** | `support.superx.gg` | Every game, all your tickets and purchases, chat history |
| **Contextual** | checkout failure, item page, missing reward | The store opens the concierge with context: "That payment didn't go through — want me to check?" |

One UI everywhere: the chat is served from `support.superx.gg` and embedded (iframe on
`*.superx.gg` with the shared session; assertion hand-off elsewhere). Store pages pass
context (`app_id`, page, order id, error) with one call.

## 2 · How it talks (the Instinct style)

Measured from the Instinct WhatsApp history: about half its turns are 2–6 short bubbles;
first bubbles open with an acknowledgement or the answer ("Got it —", "On it.", "Done —",
"Yes —", "Short answer:"); it says what it did ("Sent", "Checked live", "Found it"); only 16%
of its messages end with a question; it uses almost no emoji in text — the emoji live in
**reactions**.

Rules for the concierge:

1. **Instant receipt.** React to the player's message within 1 s (👀), show typing.
2. **Acknowledge, then deliver.** First bubble within ~2 s says what it's doing ("Got it —
   checking your Kitsune order now."). Results follow in 1–3 more bubbles. No walls of text:
   max ~240 characters per bubble.
3. **Lead with the answer.** "Done — it's in your locker." before any explanation.
4. **Do, don't ask.** When the player is proven and the action is safe, do it and say so.
   Ask only when two readings are genuinely different.
5. **Close the loop.** If something takes time, say when they'll hear back and how ("I'll
   ping you the moment it lands"), then actually do it (§6).
6. **Emoji as reactions.** ✅ when done, 🙏 on thanks, 👀 on receipt. In text, the game's own
   palette only (§4), at most one per bubble, never on bad news.
7. **Never fake it.** No invented prices, policies, or timelines; nothing about other
   players; no money in praise.

## 3 · What it knows

From SuperX ID and the game APIs (04 §2): name, linked games, level and highlights, wallet,
owned items, purchases (store and in-app, labelled App Store / Google Play / SuperX store),
pending deliveries, coupons, open tickets, ban status. Plus the game's KB and the store
catalog.

## 4 · Five personalities, one set of rules

Each app gets a **persona card** (config, editable in ops):

| Field | Example |
|---|---|
| name | **a character from that game's own world** (Roby, 18 Oct). Proposed from each roster: `prime-rush-latam` **Juliana** (Latam Legends; alt Rafael, Dos Santos) · `prime-rush-global` **Kaara** (Fight Club; alt Felicia, Arya) · `prime-rush-mena` TBC (needs a MENA-roster character) · `maskgun` **Mysterio** (mask roster; alt Phantom, Chief) · `tower-conquest` a named hero from one of its five universes — names aren't in the store code, TBC (placeholder: Kingsmen Captain) |
| voice | Prime Rush LATAM: warm, quick, Brazilian Portuguese slang; MaskGun: dry, tactical; TC: playful strategist |
| languages | pt-BR + es for `prime-rush-latam`; ar for `prime-rush-mena`; en default |
| emoji palette | Prime Rush 🔥⚡🎯 · TC 🏰🛡️✨ · MaskGun 🎭🎯💥 |
| signature lines | greeting, sign-off, "while I check" fillers (today's Prime Rush flavor lines, generalised) |
| lore | season, events, item series names, map names — from the KB and catalog |
| never says | competitor names, slurs, internal jargon (SID, gid, tier), vendor names |

**How a personality is learned**

1. **The game:** KB, patch notes, store catalog and item names (e.g. `collection/items.json`),
   event calendar → a per-game fact sheet the persona can cite.
2. **The players:** each game's own Discord tickets, chats and store reviews → the existing
   tone learner (correction pairs + staff replies) runs **per app**, producing a per-game
   style block and few-shot examples in the players' language.
3. **The grade:** ops ratings and edits feed back weekly; a per-game eval set (20–50
   conversations) checked by OpenPing (04 §5) keeps quality from drifting.
4. **Later:** per-game SuperTuned adapters replace the style blocks (SPEC-03 phase B).

Rules (scope, safety, money, privacy) are shared and can't be overridden by a persona.

**Everything comes from the game's universe** (Roby, 18 Oct). Not just the name: greetings,
fillers, how a fix is described, how bad news is softened, and the help articles themselves
are written in the world's own words — Prime Rush's series and maps, Tower Conquest's
universes and arenas, MaskGun's masks, maps and loadouts. Plain support-speak ("Your ticket
has been escalated") is a bug. Clarity still wins: in-world flavour never hides the actual
answer, the steps, or a number the player needs.

**Proactive, not reactive.** The concierge opens with what it already knows instead of "How
can I help?":
- a failed or pending delivery in the last 24 h → "Your Gold Vest drop didn't land — I've
  re-sent it";
- a payment that failed at checkout → offers to check before the player asks;
- an open issue → the status and what happens next;
- something about to expire (coupon, pass reward, event) → one line, once;
- a backend outage (GameGateway says unavailable) → says so first, with the ETA if known.
At most one proactive opener per visit; never two in a row on the same topic.

## 5 · What it can do (actions)

Every action uses the same APIs the stores use (04 §2), needs a proven player, is idempotent,
and writes an audit event visible in ops.

| Action | Prime Rush | Tower Conquest | MaskGun | Limit |
|---|---|---|---|---|
| Show purchases and delivery status | SuperX transactions | `store_transactions` | `/web/v1/purchases` | — |
| **Re-deliver an undelivered order** | grant via SuperX API | `WebFulfil` / fulfil-retry | `/web/v1/purchases/fulfil` | own paid orders only; once per order |
| Show wallet, owned items | `/users/me`, `ownedAttributes` | `WebWallet`, `WebProfile` | `/players/wallet`, `/profile` | — |
| Equip an item | `PUT /admin/users/equipped` | — | `/players/equip` | own items |
| Claim a free offer / daily reward | rewards API | `portal/claim` | coupons API | as the store allows |
| Apply or send a coupon | redeem codes | coupon system | coupon system | support coupons: ops-configured budget |
| Link another game | SuperX ID OTP | ← | ← | — |
| Report a bug | with build, device, last match from `/users/me` Support block | | | — |
| Hand to a human | ticket with full context | | | always available |

Anything that moves money beyond re-delivery (refunds, currency grants) is **proposed** by
the concierge and approved by a human in ops.

## 6 · When it's resolved (the Zomato pattern)

Food-delivery apps do support well because it's **attached to the order and they come back to
you**. Copy that:

- Support starts **from the thing**: "Problem with this order?" on every purchase in the
  account page and in the chat's purchase cards.
- A visible **status line** on every open issue: Received → Looking into it → Resolved, with
  an honest ETA when there is one.
- **We come back to you.** When an issue resolves (staff reply, item re-delivered, ticket
  closed), notify once on the best channel:
  1. in the chat, if the player is online;
  2. **push** through OpenPush (MaskGun's OneSignal until migrated);
  3. **in-game inbox mail** — all three backends already support it (Prime Rush
     `/users/inbox-message`, TC `Player/WebMail`, MaskGun `/web/v1/mail/send`);
  4. email, if we have one.
  The message deep-links back into the conversation inside the game.
- **One tap rating** on the resolution message; low ratings reopen with a human.
- **Proactive:** when the store's fulfil-retry gives up or a refund is flagged for review,
  the concierge messages the player first.

Rules: one notification per resolution, quiet hours by local time, no marketing in a
resolution message.

## 7 · After it's fixed: offers

Only after a resolved chat rated 4+ stars, never in disputes, bans or for minors, once per 14
days: one item that completes something the player collects, from the store catalog, with a
support coupon if ops enabled one. Attributed separately; graded against a holdout.
