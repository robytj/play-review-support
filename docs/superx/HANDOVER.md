# SuperX Support, SuperX ID and Ops: handover and build spec

**To:** Sreejit · **From:** Roby · **Date:** 19 Oct 2026 · **Status:** approved design, ready to build

This one document is enough to start. It covers what to build, where every piece of code
lives, what already works, the work broken into tickets, and the go-live checklist. The
detailed specs (`00`–`05` in this folder) and the clickable prototype go deeper on each part.

---

## 1 · What you're building

SuperX (superx.gg) is our web store and rewards platform. We're adding three things so every
game's players and operators work in one place:

| Product | Domain | One line |
|---|---|---|
| **SuperX ID** | `id.superx.gg` | One sign-in for every game. Tapping Support inside a game opens SuperX already signed in |
| **SuperX Support** | `support.superx.gg`, plus `<game>.superx.gg/support` and a button on every store page | A concierge chat that knows the player and fixes things. Each game's concierge is a character from that game |
| **SuperX Ops** | `ops.superx.gg` | The staff side: every ticket and live chat, store operations per game, store reviews, and daily reports on what players want |

Games and app ids. Use these everywhere; they match GameGateway:
`prime-rush-latam`, `prime-rush-global`, `prime-rush-mena`, `tower-conquest`, `maskgun`.

### See it first (about 10 minutes)

- **Clickable prototype:** `design/superx/prototype/index.html`. 23 linked pages across all
  three sites, in the Zero theme. Open it in a browser; every link works. To change it, edit
  `design/superx/prototype/_build/build.py` and run `python3 design/superx/prototype/_build/build.py`.
- **Chat mocks:** `design/superx/chat-mocks.html`. How a concierge conversation should look
  and feel.
- **Design reference:** zero.supertuned.ai. Same layout, type and tokens (§8).

---

## 2 · Source code and systems

### 2.1 Repositories

| Repo | Branch | What it is | Status |
|---|---|---|---|
| [`robytj/play-review-support`](https://github.com/robytj/play-review-support) | `master` | **Support engine** (FastAPI, Python): chat agent, KB, tickets, takeover, ratings, partner API, player context from the game DB. Also called PrimeRush-Bot / SupportBot | Running on Railway; 179 tests pass |
| [`robytj/play-review-responder`](https://github.com/robytj/play-review-responder) | `main` | **Ops dashboard** (Flask, one file `play_reviewer.py`): reviews responder, Ticket Review, Support Chat (live watch + takeover), SupportKB, Settings, cheaters, weapon meta | Running on Railway; becomes ops.superx.gg |
| [`JuneSoftware/primerush-creators`](https://github.com/JuneSoftware/primerush-creators) | `main` (Hub), `brx-store` (LATAM store), `global-store`, `mena-store`, `market-place` | Prime Rush Hub and stores (Next.js, Supabase auth, Xsolla) | Live |
| [`JuneSoftware/superx-tc`](https://github.com/JuneSoftware/superx-tc) | `main` | Tower Conquest + MaskGun stores, one codebase (`SUPERX_GAME_ID`), app in `store/` | Live |
| [`JuneSoftware/GameGateway`](https://github.com/JuneSoftware/GameGateway) | `main` | Backend availability API + admin (Google sign-in), Edge Config | Live; grows into the shared game API (§5.2) |
| [`LeeCory/superx.gg`](https://github.com/LeeCory/superx.gg) | — | www.superx.gg landing | Live |
| [`JuneSoftware/openpush`](https://github.com/JuneSoftware/openpush) | — | OpenPush, our push platform. Resolution notifications go through it | See its own specs |

`support-announcements` in primerush-creators is a **different project**. Don't build on it.

### 2.2 Specs in this repo (`play-review-support`)

| Path | Read when |
|---|---|
| `docs/superx/HANDOVER.md` | now |
| `docs/superx/00-OVERVIEW.md` | decisions and the verified current state |
| `docs/superx/01-SUPERX-ID.md` | building sign-in |
| `docs/superx/02-SUPPORT-CONCIERGE.md` | building the player side: style, characters, actions, notifications |
| `docs/superx/03-OPS.md` | building ops.superx.gg |
| `docs/superx/04-PLATFORM.md` | architecture, game APIs, chat storage, monitoring |
| `docs/superx/05-ROADMAP.md` | fix-first list and phases |
| `PLAYER_DATA_MAP.md` | the Prime Rush game DB (brx_main), field by field |
| `SHADOW_CHAT_RUNBOOK.md` | how the current chat engine is run, tested and recovered |
| `specs/support-platform/SPEC-08…11` | the engine features already built (chat, ticketing, partner API) |

### 2.3 Infrastructure

| Thing | Where | Notes |
|---|---|---|
| Support engine | Railway project `supportbot-service`, service `web` → `primebot.up.railway.app` | SQLite on a volume (`DB_PATH`) |
| Ops dashboard | Railway, `play-review-responder` | Google OAuth |
| Stores and Hub | Vercel team `superx-community` | projects: `primerush-creators` (primerush.superx.gg, hub.primerush.gg; shop/loja on `brx-store`), `primerush-store-global`, `mena-store`, `tc-webstore`, `maskgun-webstore`, `game-gateway`, `community-tools` (www.superx.gg) |
| Player accounts | Supabase, Prime Rush auth project | **Q1 below:** `kqzyvanoevklcipnzxzj` or `uqqagabepyqsquxvrvnf` |
| Prime Rush game DB | MongoDB `brx_main` | read-only user; schema in `PLAYER_DATA_MAP.md` |
| TC and MaskGun backends | TC game API (`GAME_BACKEND_BASE_URL`), MaskGun `/web/v1` (`MASKGUN_API_BASE`) | signed calls; see `superx-tc/store/games/*/server/adapter.ts` |
| Payments | Xsolla projects 299285 (LATAM), 264755 (global), 308748 (MENA), TC/MG via superx-tc | never shown by name to players |
| Monitoring | OpenPing (openping.ai) | §5.5 |
| Push | OpenPush; MaskGun uses OneSignal today | §5.6 |
| DNS | superx.gg | **Auto-renew is off; it expires 2027-06-11. Turn it on.** |

### 2.4 Environment variables (names only)

- **Support engine:** `ANTHROPIC_API_KEY`, `SUPPORT_SERVICE_API_KEY`, `PARTNER_API_KEY`, `DB_PATH`, `SECRET_KEY`,
  `DASHBOARD_PASSWORD`, `MONGO_URI`, `MONGO_DB_NAME`, `MONGO_ACCOUNT_COLLECTION`,
  `MONGO_EMAIL_FIELD`, `MONGO_SID_FIELD`, `BANNED_STATES`, `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`,
  `DISCORD_STAFF_ROLE_ID`, `DISCORD_ESCALATION_CHANNEL_ID`, `DISCORD_TICKETS_CATEGORY_ID`,
  `DISCORD_SWEEP_CHANNELS`, `DISCORD_SWEEP_HISTORY`, `FRESHDESK_DOMAIN`, `FRESHDESK_API_KEY`,
  `SUPPORT_SITE_HOST`, `SITE_DEV_KEY`, `BASELINES_BOOT_SAMPLE`, `DIAG_TEST_SID`
- **Ops dashboard:** `SUPPORTBOT_API_URL`, `SUPPORTBOT_API_KEY`, `GOOGLE_OAUTH_CLIENT_ID`,
  `GOOGLE_OAUTH_CLIENT_SECRET`, `OAUTH_REDIRECT_URI`, `FLASK_SECRET_KEY`, `MONGO_URI`, `MONGO_DB_NAME`,
  `ANTHROPIC_API_KEY`, `APPS_CONFIG`, `GCS_*`, `GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT`, `USERS_FILE`,
  `SERVICE_API_KEY`, `BANNED_STATES`
- **superx-tc chat proxy:** `SUPPORT_CHAT_BASE_URL`, `SUPPORT_CHAT_SECRET`

### 2.5 Access you need (Roby to grant)

- [ ] GitHub: `robytj/play-review-support`, `robytj/play-review-responder` (collaborator)
- [ ] Railway: `supportbot-service` and the responder project
- [ ] Vercel `superx-community`: probably already (GameGateway deploys there); confirm the store projects too
- [ ] Supabase Prime Rush auth project (admin)
- [ ] MongoDB `brx_main` read-only credentials
- [ ] Anthropic API key for the support engine
- [ ] OpenPing and OpenPush accounts
- [ ] DNS for superx.gg (Cloudflare or registrar)
- [ ] Discord server admin (support channels)

---

## 3 · What already works

| Area | Working today | Where |
|---|---|---|
| Chat agent | SID-first chat, Prime Rush player context (profile, purchases, bans, highlights), cost-tiered answers (canned → approved → KB → Claude), typo-tolerant intents, menus, player memory, bug intake, never-500 guard | engine `app/chat_engine.py`, `app/router.py`, `app/player_context.py`, `app/intents.py` |
| Humans in the loop | live watch + takeover, hand back, 1–5 star ratings, learning from staff edits | engine `app/chat_api.py`; responder Support Chat tab |
| Tickets | priority (payers auto-P1), assignee, SLA, audit events, recommendations from the KB, partner API for players' own tickets | engine `app/ticketing.py`, `app/partner_api.py`; responder Ticket Review |
| Channels | Discord (shadow, read-only), Freshdesk, email import, web | engine `discord_bot/`, `scripts/` |
| Public help site sample | per-host routing, help centre in four languages | engine `app/web_support.py`, `templates/web/` |
| Diagnostics | health, Mongo ping, scope-gate health | engine `/api/dashboard/chat/health`, responder Diagnostics |
| TC store chat | `/support` with an FAQ and a chat that calls the engine's **public `/chat`** | superx-tc `store/app/api/support/chat/route.ts`, `store/components/site/ChatWidget.tsx` |

**What doesn't exist yet:** SuperX ID; multi-game support in the engine (it's Prime Rush only);
the Next.js support site; the store concierge button; actions that change things in TC or
MaskGun; resolution push; Postgres chat storage; daily intent reports; ops.superx.gg on its
own domain and theme.

---

## 4 · Fix first (live problems, this week)

| # | Problem | Fix | Where |
|---|---|---|---|
| F1 | **Tower Conquest players get Prime Rush answers.** The TC chat posts to the engine's public `/chat`, which ignores the game | Read the `[towerconquest:<lang>]` prefix the proxy already sends, tag `app_id=tower-conquest`, answer only from a TC KB (tickets only until one exists) | engine `app/main.py:110` |
| F2 | Public `/chat` needs no key and has no rate limit, so anyone can spend our model budget | Require the bearer `SUPPORT_CHAT_SECRET` (superx-tc already sends it if set); per-IP and per-id limits | engine `app/main.py`; set the env on `tc-webstore` |
| F3 | **Anyone can act as any player on the LATAM store.** `/ingame` decodes the session JWT without verifying it, then trusts `?userid=` | Verify the signature, create a real session, remove `?userid` | primerush-creators `brx-store`: `app/ingame/route.ts`, `components/store/hooks/useStoreAccount.ts` |
| F4 | A service-auth API key is hard-coded in source | Rotate it and move it to env | primerush-creators `app/api/redeem-code/route.ts:38` |
| F5 | The chat names payment vendors to players | Labels → "App Store", "Google Play", "SuperX store" | engine `app/player_context.py:102` `_PAYMENT_LABELS` |

---

## 5 · What to build

### 5.1 SuperX ID (`01-SUPERX-ID.md`)

- **Accounts:** the Prime Rush Supabase auth project becomes the SuperX account store. New
  table `superx_links(account_id, app_id, player_id, short_id, nickname, linked_via, proven_at)`,
  unique on (app_id, player_id). Migrate `game_accounts` into it. The JWT's existing `xId` claim
  carries the account id.
- **From the game (the main path):** the client gets a 60-second one-time **launch code** from
  its backend and opens `https://<game>.superx.gg/support?lt=<code>`. The store server exchanges
  it with the game backend, then with SuperX ID (find-or-create the account), and sets the session.
  MaskGun already has the exchange (`/web/v1/launch/exchange`). **TC and Prime Rush backends need
  the same endpoint.**
- **On the web:** game ID + 6-digit code sent to in-game mail (flows exist in both repos); Google; Apple.
- **Sessions:** one cookie for every `*.superx.gg` site (`Domain=.superx.gg; Secure; HttpOnly;
  SameSite=Lax`). Stores on other domains (`*.primerush.gg`, `store.primerushgame.com`,
  `store.primerushmena.com`) sign in by redirect to `id.superx.gg/authorize` (code + PKCE).
  Embedded chat on those domains gets a 5-minute signed **player assertion** by `postMessage`,
  never in a URL.
- **Proof levels:** anonymous, claimed (typed ID), proven (game, code, Google, Apple), staff.
  Purchases, actions and offers need **proven**. Remove every bare-SID sign-in (TC `?sid=`).
- **API:** `POST /v1/launch/exchange`, `GET /authorize`, `POST /token`, `GET /v1/me`,
  `POST /v1/links/otp/send|verify`, `POST /v1/assertion`.

### 5.2 Game APIs in GameGateway v2 (`04` §2)

Every call the stores make to TC, MaskGun and Prime Rush backends, behind one service so the
stores, support and ops share them, with keys and store config managed in one place:

| Endpoint | Wraps |
|---|---|
| `GET /v2/apps/{app}/players/{id}` (profile, wallet, owned) | TC `WebProfile`/`WebWallet`; MG `/players/profile`, `/wallet`; PR `/users/me`, `/profile` |
| `GET …/players/{id}/orders` | TC `store_transactions`; MG `/purchases/*`; PR transactions |
| `POST …/orders/{order}/redeliver` | TC `WebFulfil`; MG `/purchases/fulfil`; PR grant |
| `POST …/mail`, `…/coupons`, `…/equip`, `…/claim` | in-game mail, coupon ledgers, equip, free offers |

Start from the existing adapters: `superx-tc/store/games/{tower-conquest,maskgun}/server/adapter.ts`
and the Prime Rush calls in primerush-creators. Each caller gets its own key and scope, with rate
limits and an audit log per call. The stores can switch over later.

### 5.3 Support engine, multi-game (`04` §3–4)

- `app_id` on every table and request; per-app KB, character, tone examples and eval set.
- Identity only from SuperX ID tokens or assertions. Retire the public `/chat` once TC uses the
  concierge.
- Tools = GameGateway v2 calls, each with a proof check, an idempotency key and an audit event.
- **Move storage from SQLite to Postgres** (Railway, pgvector). Tables: `conversations`,
  `messages`, `intents` (one per player message: intent, entities, sentiment, language, outcome),
  `actions`, `notifications`, `ratings`, `ticket_events`.

### 5.4 Player side: support.superx.gg + concierge (`02`)

- **Next.js on Vercel** (team `superx-community`), Zero theme. Pages per the prototype
  `design/superx/prototype/support/` and `id/`.
- **Everywhere:** the store `/support` pages, a prominent concierge button on every store and Hub
  page (one script tag, iframe from support.superx.gg), and the hub at support.superx.gg.
  Replace superx-tc's `ChatWidget` and the Prime Rush Hub's Discord SUPPORT link.
- **Characters, one per game, from that game's world:**

  | App | Character |
  |---|---|
  | `prime-rush-latam` | Juliana (Latam Legends) |
  | `prime-rush-global` | Kaara (Fight Club) |
  | `maskgun` | Mysterio (mask) |
  | `tower-conquest` | **name needed (Q3)**; placeholder "Kingsmen Captain" |
  | `prime-rush-mena` | **character needed (Q3)** |

  Everything they say (greetings, fixes, bad news, help articles) uses their game's universe.
  Plain support-speak is a bug.
- **Conversation style** (measured from Roby's agent, Instinct): react to the player's message
  instantly; first bubble within about 2 s acknowledges ("Got it — checking that order");
  answer first ("Done —"); short bubbles (≤ 240 characters, 1–3 per turn); act instead of
  asking; emoji mostly as reactions.
- **Proactive:** open with what you already know: a failed delivery, a failed payment, an
  open issue, a reward about to expire, an outage. At most one opener per visit.
- **Actions** (proven players, logged, idempotent): show orders and delivery status, **re-send a
  failed delivery**, show wallet and items, equip, claim free offers, apply coupons, link a game,
  report a bug, hand to a human. Refunds and currency grants are **proposed** and need a human.
- **Coming back (the Zomato pattern):** support starts from the order ("Problem with this
  order?"); open issues show a status line; when it's fixed, notify once (chat if online →
  push → in-game mail → email) with a deep link back; one-tap rating.
- **Offers after a fix:** only after a 4★+ resolution, never in disputes, bans or for minors,
  at most once per 14 days.

### 5.5 Ops side: ops.superx.gg (`03`)

Start by putting the responder on the domain; rebuild modules in the Zero theme as you go.
- Google sign-in limited to staff domains (copy GameGateway's `ADMIN_GOOGLE_ALLOWED_DOMAINS`).
  Roles: agent, lead, store ops, admin.
- Pages (prototype `design/superx/prototype/ops/`): Today, Live (watch, take over, hand back),
  Inbox (every game and channel incl. store reviews, SLA), ticket with player card and suggested
  next step, Approvals, Store reviews (drafts in each character's voice), **Store ops per game**
  (GameGateway availability and maintenance message, failed deliveries, refunds flagged for
  review, coupon budgets), Reports, Characters, Knowledge.
- **Reports:** an LLM-written daily digest per game (top asks with counts, new issues, quotes,
  what couldn't be answered); a spike alert when an intent hits 3× baseline in an hour.

### 5.6 Monitoring and notifications (`04` §5–6)

- **OpenPing:** support site, each `/support` page and `widget.js` (5 min); engine, Postgres and
  GameGateway (1 min); a **scripted test conversation per app** (15 min); character evals
  (daily); a test push + in-game mail (hourly). Status page `status.superx.gg`, alerts to Slack.
- **Notifications:** one notify call with fallbacks: live chat → OpenPush (MaskGun via OneSignal
  for now) → in-game mail (PR `/users/inbox-message`, TC `Player/WebMail`, MG `/web/v1/mail/send`) →
  email. One per resolution, quiet hours, no marketing in it.

---

## 6 · Tickets

Effort: S ≤ 2 days, M ≤ 1 week, L ≤ 2 weeks.

| # | Ticket | Size | Depends | Done when |
|---|---|---|---|---|
| **P0 · Fix first** | | | | |
| SX-01 | F1: tag TC traffic, TC-only answers | S | — | a TC question never gets a Prime Rush article |
| SX-02 | F2: key + rate-limit public `/chat` | S | — | unauthenticated call → 401; limits enforced |
| SX-03 | F3: verify `/ingame` JWT on brx-store, drop `?userid` | M | — | a forged token is refused |
| SX-04 | F4: rotate the hard-coded key | S | — | key gone from source and history scan |
| SX-05 | F5: vendor-neutral purchase labels | S | — | no vendor names in player replies |
| SX-06 | Turn on superx.gg auto-renew | S | — | renewal on |
| **P1 · Foundations** | | | | |
| SX-10 | `support.superx.gg` Next.js shell in the Zero theme (from the prototype) | M | — | deployed, theme matches prototype |
| SX-11 | `ops.superx.gg` custom domain on the responder + OAuth redirect | S | — | staff sign in at ops.superx.gg |
| SX-12 | Engine: `app_id` everywhere, keyed player API (extends `/api/partner/*`) | M | — | five apps isolated; tests pass |
| SX-13 | OpenPing monitors on what exists today | S | — | green dashboard, Slack alerts |
| **P2 · SuperX ID** | | | | |
| SX-20 | id.superx.gg on the Prime Rush Supabase project; `superx_links` + migration | L | Q1 | accounts with linked players |
| SX-21 | Launch-code exchange: MaskGun now; TC and Prime Rush backend endpoints | L | Q2 | tapping Support in each game lands signed in |
| SX-22 | `.superx.gg` session cookie; stores mint their session from it | M | SX-20 | one sign-in across every superx.gg site |
| SX-23 | Redirect sign-in for non-superx domains + player assertion | M | SX-20 | primerush.gg stores signed in via id.superx.gg |
| **P3 · Concierge v1** | | | | |
| SX-30 | GameGateway v2 read endpoints (profile, wallet, orders) for all apps | L | Q4 | engine reads TC/MG/PR orders through it |
| SX-31 | Concierge widget (`widget.js`, iframe) on every store + Hub; `/support` pages | M | SX-22 | button on every page, opens signed-in chat |
| SX-32 | Characters v1: per-app card, in-universe voice, tone examples per game | M | Q3 | each game's chat sounds like its world |
| SX-33 | Instinct-style UX: reactions, acknowledge bubble, multi-bubble, proactive opener | M | SX-31 | first bubble < 2 s; opener shows a failed delivery |
| **P4 · Actions + coming back** | | | | |
| SX-40 | GameGateway v2 write endpoints: redeliver, mail, coupons, equip, claim | L | SX-30 | idempotent, audited |
| SX-41 | Concierge actions + approvals queue for refunds/currency | M | SX-40 | failed delivery fixed in chat, no human |
| SX-42 | Notify service: chat → OpenPush → in-game mail → email, deep link back | M | SX-40 | push received when an issue resolves |
| SX-43 | Order-attached support ("Problem with this order?") | S | SX-30 | from purchases into a pre-filled chat |
| **P5 · Ops + storage** | | | | |
| SX-50 | Engine storage → Postgres (pgvector), intents table | L | — | data migrated; SQLite retired |
| SX-51 | Ops: Inbox incl. store reviews, Live, Approvals in the Zero theme | L | SX-11 | operators work only in ops.superx.gg |
| SX-52 | Ops: Store ops per game | M | SX-40 | availability, deliveries, refunds, coupons managed here |
| SX-53 | Daily per-game digest + spike alerts | M | SX-50 | digest in ops + Slack daily |
| SX-54 | Characters + Knowledge editors with evals | M | SX-32 | edit and test a character before publishing |
| **P6 · Everywhere** | | | | |
| SX-60 | Account page: games, purchases, conversations | M | SX-23 | one page for every game |
| SX-61 | Offers after 4★+ fixes, with holdout | M | SX-41 | attributed revenue reported |

---

## 7 · Go-live checklist (per game)

- [ ] Fix-first items closed
- [ ] Launch code signs the player in from the game (Android, iOS)
- [ ] Concierge button and `/support` live; old chat/Discord links replaced
- [ ] Character chosen, voice reviewed by the game team, eval ≥ 85
- [ ] KB for the game published (≥ the top 20 asks)
- [ ] Read tools work; redeliver tested end-to-end on a test account
- [ ] Resolution push + in-game mail received on a test device
- [ ] OpenPing: site, widget, engine, agent test, notification test green for 7 days
- [ ] Ops: staff trained on Live, Approvals, Store ops
- [ ] Kill switch tested (`chat_enabled` off → store shows contact fallback)
- [ ] Budget alerts set (model spend per app per day)

Roll out game by game: **MaskGun first** (launch exchange already exists), then Tower
Conquest, then Prime Rush LATAM, Global, MENA.

---

## 8 · Theme (zero.supertuned.ai)

| Token | Value |
|---|---|
| ink / ink2 / ink3 | `#0A0A0A` / `#4A4845` / `#868079` |
| paper / paper2 / card | `#F7F5F1` / `#EFEDE7` / `#FFFFFF` |
| line / line2 | `#E3E0DA` / `#D2CFC9` |
| **pink (SuperX)** | `#F5308C`: headline periods, brand dot, store links |
| signal | `#FF5B2E`: alerts and "needs you" only |
| green | `#00C267`: live, healthy |
| game dots | Prime Rush `#F7C600` · TC `#7C3AED` · MaskGun `#FFB400` |
| type | Geist; JetBrains Mono for labels |

Layout: ink sidebar (232 px) · paper centre · chat dock (372 px). Cards 12–14 px radius, 1 px
lines, no shadows. Every headline ends with a pink period. Full CSS in
`design/superx/prototype/_build/build.py` (`CSS`).

---

## 9 · Open questions (owner: Roby unless noted)

| # | Question | Blocks |
|---|---|---|
| Q1 | Which Supabase project is the Prime Rush auth project, and does www.superx.gg use it? | SX-20 |
| Q2 | TC and Prime Rush backend teams: add a launch-code exchange like MaskGun's | SX-21 |
| Q3 | Characters for Tower Conquest and Prime Rush MENA | SX-32 |
| Q4 | GameGateway's bigger role (Sreejit) | SX-30 |
| Q5 | Keep Discord as a channel into the same inbox? (recommended) | SX-51 |

## 10 · Contacts

Roby: decisions, access, characters. Store code: primerush-creators (LeeCory and the web
team), superx-tc (web team). Engine and ops dashboard history: this repo's git log and
`SHADOW_CHAT_RUNBOOK.md`.
