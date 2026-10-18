# SPEC-12 — White Glove on SuperX: support.superx.gg, the store widget, and the ops desk

**Owner:** Roby · **Written:** 18 Oct 2026 · **Status:** draft for review · **Mocks:** `outputs/superx-support-mocks/index.html`

> One sentence: a player who comes for help lands inside SuperX, signed in once, with their
> profile, collection, purchases and tickets on the same account, and the store one tap away.

Builds on the support spec pack (`specs/support-platform/`, SPEC-01…11), the player data map
(`PLAYER_DATA_MAP.md`), and the SuperX plans in `~/Documents/Claude/Projects/SuperXWebstore/`.
Identity follows `SuperTuned/docs/colour-system.md`.

---

## 0 · Decisions this spec asks for

| # | Decision | Recommendation |
|---|---|---|
| D1 | Domains | `support.superx.gg` (players), `ops.superx.gg` (staff). Keep the per-game hubs (`primerush.superx.gg` …) as the store fronts; make `webstore.superx.gg` the cross-game store front that links into them, not a rewrite |
| D2 | One account | SuperX (Supabase) account is the single player identity; each game's SID is a linked *game identity*. Support trusts the SuperX session, never a bare SID, for anything account-specific |
| D3 | System of record | SupportBot keeps tickets, chats, KB and agent state. SuperX keeps accounts, store orders and rewards. Game backends keep gameplay and in-game purchases. No data is copied between them — they call each other |
| D4 | Widget | An iframe widget served from `support.superx.gg`, embedded with one script tag on every store page |
| D5 | Ops desk | The reviews responder (play-review-responder) moves to `ops.superx.gg` as the *White Glove Desk*: domain first, then multi-game, then reskin |
| D6 | Look | Product chrome follows the SuperTuned identity (Paper/Ink, White Glove dot for support, In the Pink for the store). Game art supplies game colour; chrome never does |
| D7 | Public copy | No payment-vendor names in player-facing copy (SuperX one-pager rule). This changes live bot copy today — §9.3 |

---

## 1 · What exists today

### 1.1 SuperX, live

- `superx.gg` — "SuperX Store | Play our games": landing with Prime Rush, Tower Conquest, MaskGun.
- Per-game hubs on subdomains: `primerush.superx.gg` ("The Hub"), `towerconquest.superx.gg`,
  `maskgun.superx.gg`. Prime Rush nav: **Collection · Tasks (rewards) · Store · Teams · Custom
  Rooms · Creators**. Collection pages are per item (`/collection/gun_smg_01_skin_0013_evox1`)
  with series (Loud, Latam Legends, Bharat, Nippon …) and rarities (Prismatic, Legendary, Epic).
- **Support today = a footer link to Discord.** That is the slot this spec replaces.
- Code: `JuneSoftware/primerush-creators` (branches `market-place`, `global-store`,
  `membership-live`), `JuneSoftware/superx-tc`, Vercel project `superx-community/primerush-creators`.
  Stack per our specs: Next.js + Supabase + the web-payments provider.
  Auth per `PRIME-RUSH-CATALOG-SPEC.md §3`: in-game deep link `/ingame?sessionToken=<JWT>`,
  SID + OTP (planned), email/password fallback; profile via SuperX `/users/me`; grants via
  `IndusGrantRequest`.

> ⚠️ **Not yet reviewed:** those repos are private and weren't readable from this session. Every
> claim about SuperX code in this spec comes from the live site and our own specs. §11 lists what
> must be verified against the code before build starts. The local `superx-next` repo is a
> Fortnite-API prototype and is **not** the live platform.

### 1.2 Support platform (PrimeRush-Bot, FastAPI on Railway)

Shadow-tested and running: SID-first chat agent (game → SID → name confirm → recognition with
percentile highlights → issue loop), cost-tiered router (canned → approved cache → KB RAG →
escalate), purchase and ban intents, typo-tolerant intents, menus, player memory, bug intake,
live human takeover, 1–5 star ratings, ticketing (priority/assignee/SLA/audit), partner API
(`/api/partner/*`, SPEC-10), the public help-site sample with host routing
(`support.primerush.gg` → root), and self-provisioning content at boot.

### 1.3 Ops dashboard (play-review-responder, Flask on Railway)

Google sign-in, roles. Tabs: Reviews (store review responder), Cheaters, Match Analyzer,
Diagnostics, Support, SupportKB, Ticket Review, Support Chat, Support Settings, Weapon Meta,
Weapon Config, Admin.

---

## 2 · Target shape

```
                        superx.gg  (landing — In the Pink)
                            │
   ┌────────────────────────┼─────────────────────────────┐
   │                        │                             │
webstore.superx.gg   primerush.superx.gg …          support.superx.gg   ← NEW (White Glove)
(cross-game front)   (per-game hubs: Store,         help centre · chat · tickets · My SuperX
                      Collection, Tasks…)                 │   widget.js (iframe)
   │   ▲ widget on every page ────────────────────────────┘
   │   │
   └───┴── one SuperX session (cookie on .superx.gg)
                            │
             ┌──────────────┴───────────────┐
        SuperX (Supabase)             SupportBot (Railway)  ── game backends (Mongo per game)
        accounts · game ids ·         tickets · chats · KB ·
        orders · rewards              agent · partner API
                                             │
                                     ops.superx.gg  ← reviews responder becomes the White Glove Desk
```

| Surface | Audience | Colour (identity) | Hosted |
|---|---|---|---|
| `superx.gg`, `webstore.superx.gg`, `<game>.superx.gg` | players | In the Pink | Vercel (unchanged) |
| `support.superx.gg` + widget | players | White Glove | SupportBot on Railway (custom domain) |
| `ops.superx.gg` | staff | White Glove (Desk), ink mode | responder on Railway (custom domain) |

---

## 3 · Identity and sign-in (one account, many games)

### 3.1 Model

- **SuperX account** — the person. Supabase `auth.users` + `profiles`.
- **Game identity** — one row per (account, game): `game_identities(account_id, game, sid,
  user_id, linked_via, linked_at)`. Unique on (game, sid). Matches the
  `game_identities` table proposed in `PRIME-RUSH-CATALOG-SPEC.md §5`.
- Guests are first-class: a guest SID gets a SuperX account the first time it signs in (the
  synthetic `{SID}@…` pattern in the catalog spec; domain still open — Q4).

### 3.2 How a player arrives signed in

| Entry | Mechanism |
|---|---|
| From the game (Support button) | Existing `/ingame?sessionToken=<JWT>` → SuperX verifies, mints the Supabase session, **then** redirects to `support.superx.gg/<game>/chat?ctx=…` (SPEC-04 context payload rides along) |
| From a SuperX store page | Already signed in; cookie on `.superx.gg` is visible to `support.superx.gg` |
| Directly | Sign in with SID + OTP (to the in-game inbox), Google, or email; guest browsing needs no sign-in |
| Store on a non-superx domain (`primerushgame.com`, MENA) | Third-party cookies are blocked (Safari, in-game webviews), so the widget gets a **short-lived signed handoff token** via `postMessage` from the host page, exchanged server-side |

**Required SuperX change:** set the Supabase SSR cookie domain to `.superx.gg` (SameSite=Lax,
Secure). Host-only cookies (the default) would force a second sign-in on `support.`. If the
deep-link route still only forwards `?userid=` (catalog spec gap), it must create a real session
first — support can't trust an unsigned id.

### 3.3 How support trusts the session

SupportBot verifies the Supabase JWT on every player request (JWKS from the SuperX Supabase
project, cached), reads `account_id`, and resolves game identities through a new SuperX
server-to-server endpoint. **All account-scoped reads key off the verified identity** — the
SPEC-08 cross-player guarantee now rests on a real session instead of "the SID the player
typed". Typing a SID is still allowed for guests, but only unlocks KB answers and ticket filing,
never purchase or account detail, until the SID is proved (OTP or game deep link).

| Trust level | How | Unlocks |
|---|---|---|
| Anonymous | none | KB, search, chat on KB topics |
| Claimed SID | typed | file a ticket, generic answers |
| Verified | SuperX session with linked identity | purchases, collection, ban status, tickets, offers |
| Staff | Google SSO on `ops.` | everything, audited |

### 3.4 Staff sign-in

`ops.superx.gg` keeps the responder's Google sign-in, restricted to staff domains, with existing
roles. Every staff action already writes `ticket_events`; extend actor to the Google email
(already forwarded as `X-Staff-Email`).

---

## 4 · Multi-game support (Prime Rush, Tower Conquest, MaskGun)

SupportBot is single-game today. Changes:

- **`game` everywhere:** add `game` to `conversations`, `chat_sessions`, `kb_articles`,
  `canned`, `suggestions` (default `primerush`; backfill existing rows).
- **Player-context adapters:** `player_context` becomes an interface with one adapter per game.
  Prime Rush = `brx_main` (done). Tower Conquest and MaskGun adapters need their schemas
  (Q6) — until then those games run KB-only + ticketing.
- **KB per game, shared articles allowed:** account, payments and SuperX-store articles are
  `game='all'`; gameplay articles are per game.
- **Routing:** `support.superx.gg/<game>/…` sets the game; the widget sets it from
  `data-game`; the chat's "Which game?" step is skipped whenever the game is known.
- **Per-game SKUs:** Prime Rush has LatAm (`primerush.gg`), Global and MENA SKUs. Model these as
  game identities of the same game with a `sku` column, not separate games.

---

## 5 · support.superx.gg — the player service

### 5.1 Pages

| Route | Content |
|---|---|
| `/` | Pick a game · search across all games · if signed in: your open tickets and a "continue chat" card |
| `/<game>` | Game help centre: categories, top articles, chat CTA (SPEC-02 layout, per game) |
| `/<game>/a/<slug>` | Article · helpful vote · related · chat CTA |
| `/<game>/chat` | Full-page chat (the SPEC-08 agent, now authenticated) |
| `/tickets`, `/tickets/<public_id>` | All your tickets across games · thread · status timeline · reply |
| `/me` | **My SuperX** — §6 |
| `/widget` | The iframe target for widget.js |

### 5.2 Serving

SupportBot already serves the help-site sample with host routing (`app/web_support.py`). Change
`SUPPORT_SITE_HOST` to accept a list (`support.superx.gg,support.primerush.gg`), add the `game`
path segment, and add the Railway custom domain. The existing design package
(`templates/web/`) is restyled to the White Glove identity (§9) — same templates, new tokens.

### 5.3 Chat, authenticated

Same engine, three changes: (1) identity comes from the session, so the SID step disappears for
signed-in players; (2) the purchase intent can show **store orders** (SuperX) alongside in-game
purchases (game backend) — one list, labelled by where it was bought; (3) escalations create a
ticket the player can see in `/tickets` and in My SuperX immediately.

---

## 6 · My SuperX — one place for the player

A signed-in account page shared by the store and support (built once, in the SuperX app, and
linked from both; support renders the Tickets tab itself).

| Tab | Source | Shows |
|---|---|---|
| Profile | SuperX + game backend | name, linked games and SIDs, member since, highlights (SPEC-05 percentiles — never spend) |
| Collection | game backend `owned[]` + catalog | owned items by series and rarity, with what's missing from each series |
| Purchases | SuperX orders + game `user.transaction` | completed purchases, labelled App Store / Google Play / SuperX store; "something missing?" opens chat with that order as context |
| Tickets | SupportBot partner API | open and resolved tickets, replies, ratings |
| Rewards | SuperX tasks | tasks, claimable rewards |

Rules: player-safe serialization only (SPEC-10 §2) — no priority, assignee, internal notes or
suggestions ever leave SupportBot. Money stays invisible in highlights and recognition.

---

## 7 · The store widget

### 7.1 Embed

```html
<script src="https://support.superx.gg/widget.js" data-game="primerush" async></script>
```

- Renders a launcher (White Glove mark) bottom-right; opens an iframe of `/widget`.
- **Context in:** the host page posts `{page: 'item'|'store'|'checkout'|'collection', item_id,
  order_id, error_code}` so the agent opens on the right topic ("Problem with this purchase?").
- **Identity in:** same-site → the `.superx.gg` cookie is already there; cross-site → handoff
  token (§3.2).
- **Events out:** `open`, `resolved`, `offer_click(item_id)` → the host page can add to cart or
  navigate.
- **Budget:** loader ≤ 6 KB gzipped; iframe loads only on first open. No layout shift.
- **Webview:** the in-game store runs in a webview — test cookies, storage and `postMessage`
  there first (§12 Phase B gate).

### 7.2 Security

Store pages: CSP `frame-src https://support.superx.gg; script-src … https://support.superx.gg`.
Support: `frame-ancestors https://*.superx.gg <allow-listed store domains>`. `postMessage`
origin-checked both ways. Widget never receives a session token in the URL.

### 7.3 Contextual triggers (opt-in per page)

| Where | Trigger | Agent opens with |
|---|---|---|
| Checkout failure | payment error code | "That payment didn't go through — want me to check your account?" |
| Item page | dwell + "Help" tap | item-aware answers (what's in it, how to equip) |
| Collection | missing-item report | owned vs. purchased reconciliation |

---

## 8 · Selling inside support (the upsell, done carefully)

Extends SPEC-06 with the store now on the same account.

- **When:** only after a resolved conversation with CSAT ≥ 4 stars or 👍; never during payment
  disputes, refunds, bans, or for minor-flagged accounts; at most one offer per player per 14
  days.
- **What:** collection-aware — items that complete a series the player is collecting, or the
  current featured item for a game they play. Prices and items come only from the SuperX
  catalog; the agent never generates a price.
- **How it looks:** an In-the-Pink card inside the White Glove chat ("From the store"); one tap
  opens the store item (or adds to cart via widget event).
- **Measured:** agent-attributed purchases are tracked apart from store revenue and graded
  against a holdout by default (SuperX one-pager). Dashboard: offers shown → opened → bought,
  CSAT with vs. without offers.

---

## 9 · Look and voice — the SuperTuned identity

### 9.1 Tokens

| Token | Value | Use |
|---|---|---|
| `--ink` | `#0A0A0A` | text, rules, dark bands, ops desk background |
| `--paper` | `#F7F5F1` | player-facing background |
| `--signal` | `#FF5B2E` | the only accent; ≤5% of a screen (live dots, focus) |
| `--glove` | `#FFFFFF` with 1.5px ink outline | White Glove dot (support): logo dot, headline period |
| `--pink` | `#F5308C` | In the Pink (store): store links, offer cards, the store's headline period |
| Display / body | Geist | 18px body, tight display tracking |
| Labels | JetBrains Mono | 11–12px, uppercase, 0.12em |

No gradients, no glassmorphism, 1px rules. Every page headline ends in a period set in the
product colour: white-with-outline on support, pink on store moments.

### 9.2 Game colour

Game art (characters, weapon renders, series banners) carries the game's colour inside
image tiles and hero bands. Chrome stays Paper/Ink. Inside the game webview the support pages
switch to an ink background (same tokens, inverted) to sit naturally inside the game.

This supersedes the dark SuperGaming monochrome direction in SPEC-02a for SuperX surfaces; the
Claude Design package's templates are reused with the new tokens.

### 9.3 Copy rules (and one fix needed now)

- **No payment-vendor names** in player copy. The live bot says "36 purchase(s) via Apple,
  XSolla" — change player-facing labels to **App Store · Google Play · SuperX store**
  (`app/player_context._PAYMENT_LABELS`). Raw values stay in the DB and on the ops desk.
- Calm, specific, no hype; money never appears in praise or recognition.

---

## 10 · The ops desk on SuperX (reviews responder → ops.superx.gg)

| Step | Change |
|---|---|
| 1 · Domain | Add `ops.superx.gg` as a Railway custom domain on the responder; add it to the Google OAuth redirect URIs; keep the old URL working |
| 2 · Multi-game | `game` filter across Reviews, Ticket Review, Support Chat, SupportKB; per-game app config for store reviews (`APPS_CONFIG` already holds several apps) |
| 3 · Unified inbox | One queue across channels: Chat, Discord, Email, Freshdesk, **store reviews** — same priority/SLA/assignee model (SPEC-09), review replies drafted by the agent and approved by staff |
| 4 · Player card | Every item shows the linked SuperX account: games, collection value band, open tickets, store orders (staff can see vendors and amounts) |
| 5 · Reskin | White Glove Desk theme (ink mode). Game-ops tools (Cheaters, Match Analyzer, Weapon Meta/Config) stay in the same app under a "Game ops" group, staff-only |

Live takeover, ratings, outreach and recommendations carry over unchanged.

---

## 11 · Before build: what must be verified in SuperX code

| Check | Where | Why |
|---|---|---|
| Session creation in `/ingame` | `primerush-creators` (`membership-live`) | §3.2 assumes a real Supabase session; the catalog spec says it only forwards `?userid=` |
| Cookie domain + `@supabase/ssr` setup | same | `.superx.gg` sharing (§3.2) |
| `game_identities` (or equivalent) | Supabase schema | §3.1 |
| Order model + webhook | `global-store` / `market-place` | store orders in Purchases (§6) and chat (§5.3) |
| How the 3 game hubs are deployed (one project + middleware, or three) | Vercel `superx-community` | widget `data-game` defaults, CSP per project |
| Existing CSP / headers | `next.config` / middleware | widget embed (§7.2) |
| `superx-tc` contents | repo | scope unknown — terms/conditions or a separate service |

---

## 12 · Phases

| Phase | Ships | Done when |
|---|---|---|
| **A · Domains (≈1 week)** | `support.superx.gg` serving today's help site for Prime Rush; `ops.superx.gg` alias; game hubs' SUPPORT link → `support.superx.gg/primerush` instead of Discord | both domains with certificates; no regression on `support.primerush.gg`; vendor-name copy fix (§9.3) |
| **B · One sign-in + widget v1** | `.superx.gg` session trusted by SupportBot; widget on `primerush.superx.gg/store` | signed-in player chats with no SID step; webview test passes (cookie, iframe, postMessage) |
| **C · My SuperX** | Profile, Collection, Purchases (store + in-game), Tickets | a player sees one order list and every ticket across channels in one place |
| **D · All games** | `game` dimension; KB-only + ticketing for Tower Conquest and MaskGun; adapters as schemas arrive | each game hub's widget opens in the right game |
| **E · Selling in support** | collection-aware offers with holdout | attributed revenue and CSAT reported per offer cohort |
| **F · White Glove Desk** | unified inbox incl. store reviews, multi-game filters, reskin | one queue for every channel and game |

---

## 13 · Open questions

1. **Domains:** confirm `support.superx.gg` + `ops.superx.gg`; is `webstore.superx.gg` a new
   cross-game front, or a rename of an existing hub?
2. **Repo access:** add the SuperX repos to a folder I can read (or reconnect GitHub) for §11.
3. **`superx-tc`:** what is it?
4. **Guest accounts:** domain for synthetic guest emails (catalog spec item 10).
5. **Ops desk name:** "White Glove Desk" on `ops.superx.gg`, or keep the current name?
6. **Tower Conquest and MaskGun:** which backends and schemas hold their players and purchases?
7. **Discord:** keep the Discord server as a channel feeding the same inbox (recommended), or
   retire it once `support.superx.gg` is live?
8. **Domain renewal:** `superx.gg` auto-renew is off (expires 2027-06-11, per the SuperTuned
   domain doc) — turn it on before support runs on it.
