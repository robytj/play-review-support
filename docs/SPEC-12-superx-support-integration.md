# SPEC-12 — White Glove on SuperX: support.superx.gg, the store widget, and the ops desk

**Owner:** Roby · **Written:** 18 Oct 2026 · **v2:** same day, rewritten after reading the SuperX
code (`primerush-creators`, `superx-tc`) and the `superx-community` Vercel team ·
**Status:** draft for review · **Mocks:** `outputs/superx-support-mocks/index.html`

> One sentence: a player who comes for help lands inside SuperX, signed in once, with their
> profile, collection, purchases and tickets in one place, and the store one tap away.

Builds on `specs/support-platform/` (SPEC-01…11) and `PLAYER_DATA_MAP.md`. Identity follows
`SuperTuned/docs/colour-system.md`.

---

## 0 · Fix first (found while reading the code)

These are live today and don't wait for this project.

| # | Problem | Where | Fix |
|---|---|---|---|
| F1 | **Our bot is already answering Tower Conquest players with the Prime Rush KB.** `towerconquest.superx.gg/support` posts to `primebot.up.railway.app/chat`; that endpoint ignores the game and the conversations mix into Prime Rush data as channel `web` | `superx-tc/store/app/api/support/chat/route.ts`; `PrimeRush-Bot/app/main.py` `POST /chat` | Short term: SupportBot reads the `[towerconquest:<lang>]` prefix, tags `game`, and answers TC with a TC-only KB (tickets only until it exists). Long term: §5 |
| F2 | Public `/chat` needs no key and has no rate limit — anyone can spend our model budget | `app/main.py` | Require the `SUPPORT_CHAT_SECRET` bearer superx-tc already sends; per-IP + per-`external_id` limits; daily budget applies |
| F3 | **Anyone can act as any Prime Rush player on the LATAM store.** `/ingame` base64-decodes the session JWT without verifying it and redirects to `/?userid=<id>`; the store trusts `?userid` | `primerush-creators@brx-store` `app/ingame/route.ts:3-40`, `useStoreAccount.ts:35-50` | Verify the JWT signature, create a real session, drop `?userid` |
| F4 | A service-auth API key is hard-coded in source | `primerush-creators` `app/api/redeem-code/route.ts:38` | Rotate it; move to env |
| F5 | Player-facing copy names payment vendors ("via Apple, XSolla") | SupportBot `app/player_context._PAYMENT_LABELS` | Show App Store · Google Play · SuperX store (SuperX rule: no payment-vendor names in public copy) |

---

## 1 · What exists (verified)

### 1.1 SuperX on Vercel (`superx-community` team)

| Domain | Vercel project | Repo / branch |
|---|---|---|
| `www.superx.gg` | community-tools | `LeeCory/superx.gg` (Supabase) |
| `primerush.superx.gg`, `hub.primerush.gg` | primerush-creators | `JuneSoftware/primerush-creators@main` — the Hub |
| `shop.primerush.gg`, `loja.primerush.gg` | primerush-creators | `@brx-store` — LATAM store |
| `stage.primerushgame.com` | primerush-creators | `@market-place` — P2P marketplace |
| `store.primerushgame.com` | primerush-store-global | `primerush-creators@global-store` (inferred) |
| `store.primerushmena.com` | mena-store | `primerush-creators@mena-store` (inferred) |
| `towerconquest.superx.gg` | tc-webstore | `JuneSoftware/superx-tc` (`SUPERX_GAME_ID`) |
| `maskgun.superx.gg` | maskgun-webstore | `JuneSoftware/superx-tc` |
| `game-gateway.superx.gg` | game-gateway | `JuneSoftware/GameGateway` — admin with Google SSO for staff domains |
| `market.superx.gg` | web3-marketplace | `SuperGam1ng/web3-marketplace-frontend` |

Most Prime Rush storefronts are **not on superx.gg** (primerush.gg, primerushgame.com,
primerushmena.com). That decides the identity design (§3).

### 1.2 Two identity systems

| | Prime Rush (`primerush-creators`) | Tower Conquest, MaskGun (`superx-tc`) |
|---|---|---|
| Sign-in | Supabase: Google OAuth; SID + OTP delivered to the in-game inbox → Supabase user `{sid}@superingame.com`; Google users link a game account by OTP | Per-game: Short ID / Player ID + inbox OTP; in-game launch (`?lt=` MG, `?sid=` TC); Google (MG) |
| Session | `@supabase/ssr` defaults: host-only cookie per site, no SSO between hub/shop/store | Hand-rolled HMAC token in `tc_portal` / `mg_portal`, host-only, 3-day sliding |
| Account model | `auth.users` + `public.game_accounts(user_id, game_sku latam\|global, long_id, short_id, ingame_name)` | `{gid, nk, sid, auth}` — no cross-game account |
| Proof levels | Supabase session = proven (OTP/Google) | `isProvenOwner()`: otp, game, google, apple = proven; `sid` (bare Short ID) = **not proven** |
| Backend trust | **SuperX API accepts the Supabase access token as Bearer** (`/users/me`, `/profile`) | Signed calls to each game backend (TC `X-Agent-*` HMAC, MG `X-MG-*` HMAC) |

### 1.3 Support that already exists on SuperX

- **superx-tc**: `/support` page with FAQ + `ChatWidget` (inline panel, not an iframe) → server
  proxy → SupportBot `/chat`. Anonymous `web-<uuid>` id; never reads the session; ignores
  `conversation_id`. Enabled for TC, off for MG (capability `supportChat`).
- **primerush-creators@support-announcements** (unmerged, May): a full ticket system — pages
  `/support`, `/support/new`, `/support/tickets/[id]`; Supabase schema `support.tickets` (ids
  `PR-XXXXXXXX`, type games|payments, ~39 sub-categories, statuses, RLS), `support.messages`,
  `support.ai_runs`; a Claude agent; connectors to SuperX `/users/me` and transactions (with a
  bug: player JWT used on admin-only endpoints).
- **SuperX `/users/me`** already returns `Support` info (email, ban flags, devices, last seen,
  matches, build, location).
- Prime Rush hub footer SUPPORT → Discord.

### 1.4 Orders and coupons

- Prime Rush: Xsolla checkout (projects 299285 LATAM/main, 264755 global, 308748 MENA); **no
  webhook in the repo** — fulfilment is SuperX/game-side; orders visible via the SuperX
  transaction webhook into Supabase `public.transactions` and SuperX
  `GET /users/{id}/transactions` (admin policy).
- TC / MG: Xsolla webhook in `superx-tc` (`order_paid`, `refund`, clawback behind
  `REFUND_CLAWBACK`, "flagged for support review"); orders stored by the game backends (TC
  `store_transactions`, MG `/web/v1/purchases/*`); **no player-facing order history**.
- Coupons (TC/MG): thank-you bonus coupons delivered by in-game mail (and push for MG via
  OneSignal), redeemed at checkout — reusable for support offers (§8).

### 1.5 Support platform and ops desk

SupportBot (FastAPI, Railway): SID-first chat agent, tiered router, purchase/ban intents,
menus, player memory, takeover, ratings, ticketing (priority/assignee/SLA/audit), partner API
(SPEC-10), help-site sample. Ops dashboard (Flask, Railway): Reviews, Cheaters, Match Analyzer,
Diagnostics, Support, SupportKB, Ticket Review, Support Chat, Settings, Weapon Meta/Config.

---

## 2 · Decisions

| # | Decision | Recommendation |
|---|---|---|
| D1 | Domains | `support.superx.gg` (players), `ops.superx.gg` (staff). Storefronts keep their domains |
| D2 | Who serves support.superx.gg | **A Next.js app in the `superx-community` Vercel team**, built from the `support-announcements` pages, signed in with the Prime Rush Supabase project. **SupportBot is its backend** (agent, KB, tickets, takeover). Not the FastAPI help-site sample — that stays as the design reference |
| D3 | One ticket store | SupportBot's. The `support.*` Supabase schema on the branch is **not** deployed; its taxonomy (types, ~39 sub-categories) and ticket-id format are adopted into SupportBot |
| D4 | Identity across stores | A **player assertion**: each store's server signs a 5-minute token stating who the player is and how they proved it. Works across every domain; no shared cookie needed (§3) |
| D5 | The SuperX account | The Prime Rush Supabase auth project becomes the SuperX account for support. TC/MG players can link into it later; until then their assertion carries game ids only |
| D6 | Widget | One script from `support.superx.gg`, iframe-based, on every store and hub |
| D7 | Ops desk | The responder moves to `ops.superx.gg` as the *White Glove Desk*; staff sign-in follows the GameGateway pattern (Google, `ADMIN_GOOGLE_ALLOWED_DOMAINS`) |
| D8 | Look | SuperTuned identity: Paper/Ink chrome, White Glove for support, In the Pink for store moments; game art carries game colour |

---

## 3 · Identity: the player assertion

### 3.1 Why not a shared cookie

Storefronts span superx.gg, primerush.gg, primerushgame.com and primerushmena.com, and the
in-game webview blocks third-party cookies. A `.superx.gg` cookie would cover two of ten
domains. So identity travels as a signed token from the store's server.

### 3.2 The token

Minted server-side by each storefront (`POST /api/support/assertion` in each repo), signed
with a per-store key registered in SupportBot (Ed25519, key id per store), 5-minute expiry,
single use (`jti`):

```json
{
  "iss": "superx-tc:towerconquest",        "aud": "support.superx.gg",
  "game": "towerconquest",  "sku": "global",
  "sid": "ABCD-1234",  "gid": "<game account id>",  "nk": "PlayerName",
  "proof": "otp|game|google|apple|supabase|sid",
  "superx_user": "<supabase uuid, if any>",
  "ctx": {"page": "checkout", "order_id": "…", "error": "…", "locale": "pt-BR"},
  "iat": 0, "exp": 0, "jti": "…"
}
```

- `primerush-creators`: mint from the Supabase session (`proof: supabase`), include
  `game_accounts` short ids.
- `superx-tc`: mint from `getSession()`; `proof` = the session's `auth`.
- The widget never sees a long-lived credential; the token goes iframe-ward via `postMessage`
  and is exchanged by support's server for a support session cookie on `support.superx.gg`.

### 3.3 Trust levels

| Level | From | Unlocks |
|---|---|---|
| Anonymous | nothing | KB, search, chat on KB topics |
| Claimed | typed SID, or `proof: sid` | file a ticket, generic answers |
| Proven | `proof` ∈ otp, game, google, apple, supabase | purchases, collection, ban status, ticket history, offers |
| Staff | Google SSO on `ops.` | everything, audited |

TC's `?sid=` launch login sets `auth: "sid"`: **not proven** — the support agent must not
show purchases on it. The SPEC-08 cross-player guarantee now rests on a signed assertion
instead of "the SID the player typed".

### 3.4 Direct visits to support.superx.gg

Sign in with the same Supabase project (Google, or SID + inbox OTP — the code path already in
`primerush-creators` main). TC/MG players use SID + OTP against their game backend through a
SupportBot adapter, or arrive via the widget.

---

## 4 · Multi-game

- `game` (and `sku`) on every SupportBot table that holds player content: conversations,
  chat_sessions, suggestions, kb_articles, canned. Backfill `primerush`.
- Player-context adapters: Prime Rush = brx Mongo (done; SuperX `/users/me` `Support` block is
  a cheaper source for state/bans/devices); TC = game API (`Player/WebProfile`,
  `store_transactions`); MG = `/web/v1/players/profile`, `/web/v1/purchases/*`. Signed calls
  reuse the keys the stores already hold — SupportBot gets its own service keys, never the
  stores'.
- KB per game; account/payments/SuperX articles shared (`game='all'`).
- Prime Rush SKUs (latam, global, mena) are `sku`, not separate games — matches
  `game_accounts.game_sku`.

---

## 5 · support.superx.gg

### 5.1 Build

New Next.js app (or a route group in `primerush-creators` deployed as its own Vercel project)
in `superx-community`. Start from `support-announcements` (pages, i18n en/br/mxn, Supabase
auth plumbing); replace its tables and agent with calls to SupportBot:

| Page | Content |
|---|---|
| `/` | game picker, search, signed-in strip with open tickets |
| `/<game>` | help centre for one game |
| `/<game>/a/<slug>` | article |
| `/<game>/chat` | chat with the SupportBot agent (authenticated) |
| `/tickets`, `/tickets/<id>`, `/tickets/new` | the player's tickets across games |
| `/me` | My SuperX (§6) |
| `/widget` | iframe target |

### 5.2 SupportBot API for it

Extend the SPEC-10 partner API into a player API, called server-side by support.superx.gg
with its service key **plus** the verified player assertion:

- `POST /api/partner/session` — exchange assertion → player context id
- chat: `POST /api/partner/chat/sessions`, `…/messages`, `GET …/messages?after_id` (the
  SPEC-08 engine; SID step skipped when proven)
- tickets: list, detail, create (with taxonomy), reply
- KB: `GET /api/partner/kb?game=&q=`

Retire the public `/chat` once superx-tc moves to the widget (F1/F2 cover the meantime).

---

## 6 · My SuperX

One account page (`support.superx.gg/me`, linked from every store and hub):

| Tab | Source |
|---|---|
| Profile | SuperX `/users/me` + game profile; highlights (never spend) |
| Collection | Prime Rush: SuperX `ownedAttributes` + `collection/items.json` (already used by `/mycollection`); TC/MG: game profile inventory |
| Purchases | Prime Rush: `public.transactions` + SuperX transactions (service-side); TC/MG: game backend orders. Labelled App Store / Google Play / SuperX store. Fills the "no player-facing order history" gap in both repos |
| Tickets | SupportBot |
| Rewards | Prime Rush `rewards.*`; TC/MG coupons ledger |

Player-safe serialization only (SPEC-10 §2).

---

## 7 · The widget

```html
<script src="https://support.superx.gg/widget.js" data-game="towerconquest" async></script>
```

- Launcher (White Glove mark) + iframe of `/widget`, loaded on first open; loader ≤ 6 KB.
- Host page calls `SuperXSupport.identify(fetch('/api/support/assertion'))` when signed in and
  `SuperXSupport.context({page, order_id, error})` on checkout failures and item pages.
- Events out: `resolved`, `offer_click(sku)` → host adds to cart.
- Mounts: primerush-creators inside `AuthProvider` next to the toasters (`app/layout.tsx:86-87`),
  avoid `z-50` (navbar, loader); superx-tc in `SiteChrome`, replacing `ChatWidget`.
- Neither repo sets CSP today, so embedding works; add `frame-src https://support.superx.gg`
  deliberately, and `frame-ancestors` on support for the allow-listed store domains.
  `postMessage` origin-checked both ways.

---

## 8 · Selling inside support

- Only after a resolved chat rated ≥ 4 stars; never during payment disputes, refunds, bans, or
  for minor-flagged accounts; one offer per player per 14 days.
- Collection-aware: complete a series the player is collecting, or the current featured item.
  Items and prices from each store's catalog (`/api/store/featured`, Xsolla catalog), never
  generated.
- Mechanism: reuse the TC/MG coupon system (issue a support coupon via the existing mail/push
  delivery) and Prime Rush creator/redeem codes; deep link with the coupon applied.
- Attributed separately from store revenue, graded against a holdout.

---

## 9 · Look and voice — SuperTuned identity

| Token | Value | Use |
|---|---|---|
| `--ink` | `#0A0A0A` | text, rules, ops desk |
| `--paper` | `#F7F5F1` | player background |
| `--signal` | `#FF5B2E` | ≤5% — live states |
| White Glove | white dot, ink outline | support mark, headline period |
| In the Pink | `#F5308C` | store links, offer cards |
| Type | Geist; JetBrains Mono labels | |

Stores keep their own game themes (Prime Rush amber/Neusharp, TC purple/Grobold, MG navy);
the widget and support site use the White Glove chrome so support looks the same in every
game. In-game webview: ink variant.

---

## 10 · The ops desk (responder → ops.superx.gg)

1. Railway custom domain `ops.superx.gg`; add to Google OAuth redirect URIs; old URL keeps
   working.
2. `game` filter across Reviews, Ticket Review, Support Chat, KB.
3. One inbox: chat, Discord, email, Freshdesk, store reviews; SPEC-09 priority/SLA/assignee.
4. Player card from the assertion / SuperX `/users/me` `Support` block; staff see vendors and
   amounts.
5. White Glove Desk theme (ink). Game ops (Cheaters, Match Analyzer, Weapon Meta/Config) stay,
   staff-only.

---

## 11 · Phases

| Phase | Ships | Done when |
|---|---|---|
| **0 · Fix first** | F1–F5 | TC chats tagged `game=towerconquest` with no Prime Rush answers; `/chat` keyed + rate-limited; brx-store `/ingame` verifies; key rotated; vendor names gone |
| **A · Domains** | `support.superx.gg` (Next.js shell + KB) and `ops.superx.gg` | both live; hub footer SUPPORT → support.superx.gg |
| **B · Assertion + widget** | assertion endpoint in both repos; widget replaces TC `ChatWidget`; on primerush hub | proven player chats with no SID step on TC and Prime Rush; webview test passes |
| **C · Tickets + My SuperX** | partner player API; tickets pages; My SuperX with purchases | one order list and every ticket in one place |
| **D · All games** | TC + MG adapters and KBs; MG `supportChat` on | each store's widget answers for its own game |
| **E · Selling** | support coupons + holdout | attributed revenue and CSAT per cohort |
| **F · White Glove Desk** | unified inbox, multi-game, reskin | one queue for every channel and game |

---

## 12 · Open questions

1. Which Supabase project is the auth project — `kqzyvanoevklcipnzxzj` or
   `uqqagabepyqsquxvrvnf`? (`NEXT_PUBLIC_SUPABASE_URL` is env-only.) And does
   `www.superx.gg` (community-tools) use the same one?
2. Confirm Vercel branches: `primerush-store-global` ← `global-store`, `mena-store` ←
   `mena-store`.
3. `support-announcements` (LeeCory): adopt its pages as the support.superx.gg starting point
   (D2/D3), or was it abandoned for a reason?
4. `webstore.superx.gg`: new cross-game front, or not needed?
5. Ops desk name: "White Glove Desk" on `ops.superx.gg`?
6. Discord: keep as a channel into the same inbox (recommended)?
7. `superx.gg` auto-renew is off (expires 2027-06-11) — turn it on before support depends on it.
8. Several env vars are set in Vercel but never read by the code (`EDGE_CONFIG`,
   `INDUS_AUTH_URL`, `INDUS_API_KEY`, `SUPERX_SERVICE_TOKEN`, `XSOLLA_PROJECT_ID`,
   `XSOLLA_MERCHANT_ID` on primerush-creators) — clean up, or are they read by something
   not in the repo?
