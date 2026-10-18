# SuperX — 01 · SuperX ID (one sign-in for every game)

## 1 · Today: three ways in, no sharing

| | Prime Rush (`primerush-creators`) | Tower Conquest, MaskGun (`superx-tc`) |
|---|---|---|
| Sign-in | Supabase: Google OAuth; SID + code to the in-game inbox → user `{sid}@superingame.com` (`app/auth/ingame/*`) | Short ID / Player ID + inbox code (`/api/portal/otp/*`); MaskGun launch token `?lt=` (`/web/v1/launch/exchange`); TC `?sid=`; Google (MaskGun) |
| Session | `@supabase/ssr` defaults: host-only cookie, so hub, shop and stores each sign in separately | HMAC-signed cookie `tc_portal` / `mg_portal`, host-only, 3 days |
| Account | `auth.users` + `game_accounts(user_id, game_sku latam\|global, long_id, short_id)` | `{gid, nk, sid, auth}` per game; no cross-game account |
| From the game | brx-store `/ingame?sessionToken=` **decodes the JWT without verifying it** → `?userid=` (anyone can act as anyone) | MaskGun `?lt=` exchange is sound; TC `?sid=` signs in with a bare SID and marks it unproven |

What's reusable: Supabase already does Google and inbox-OTP sign-in, and the SuperX API
already accepts its access tokens. The Prime Rush JWT already carries an `xId` claim
(`components/providers/auth-provider.tsx:45-83`). MaskGun already has a safe launch exchange.

## 2 · Target

```
                       ┌─────────────── id.superx.gg ───────────────┐
 game client ──lt──▶   │ SuperX ID (Supabase auth project)          │
 Google / Apple ──▶    │  accounts · linked game players · sessions │
 SID + inbox code ──▶  └────────────┬───────────────────┬───────────┘
                                    │ cookie .superx.gg │ redirect (code + PKCE)
             *.superx.gg stores, support, ops      primerush.gg / primerushgame.com /
                                                   primerushmena.com stores
```

### 2.1 The account

- A **SuperX account** is a Supabase `auth.users` row in the Prime Rush auth project (Q1).
- `superx_links(account_id, app_id, player_id, short_id, nickname, linked_via, proven_at)` —
  one row per game player linked to the account; unique on (app_id, player_id). Migrate
  `game_accounts` into it (`latam` → `prime-rush-latam`, `global` → `prime-rush-global`).
- The `xId` claim becomes the SuperX account id carried in every token.
- Guests: a player who first arrives from the game gets an account automatically, keyed to
  that game player. Adding Google or Apple later makes it portable across devices.

### 2.2 Ways to sign in

| Method | How | Proof |
|---|---|---|
| **From the game** (main path) | The client asks its backend for a one-time **launch code** (60 s, single use) and opens `https://<game>.superx.gg/<page>?lt=<code>`. The store server exchanges it with the game backend, then with SuperX ID: find-or-create the account for (app_id, player_id), set the session | `game` |
| SID / Player ID + inbox code | The flow that already exists in both repos, moved to SuperX ID | `otp` |
| Google, Apple | Supabase providers; link games afterwards by inbox code | `google`, `apple` |

Retire: brx-store `?sessionToken` decoding without verification and TC `?sid=` bearer
sign-in. Both are replaced by launch codes (Q2 in `00`: TC and Prime Rush backends need a
launch exchange like MaskGun's).

### 2.3 Sessions across sites

- **On `*.superx.gg`** (primerush, towerconquest, maskgun, support, id): the SuperX ID
  session cookie is set with `Domain=.superx.gg`, `Secure`, `HttpOnly`,
  `SameSite=Lax`. Signing in on any of them signs you in on all of them.
- **On other domains** (`hub.primerush.gg`, `shop`/`loja.primerush.gg`, `store.primerushgame.com`,
  `store.primerushmena.com`): standard redirect sign-in — the store sends the player to
  `id.superx.gg/authorize`, gets a code back, exchanges it server-side. If the player is
  already signed in at id.superx.gg there's no prompt; it's a quick bounce.
  *Build note:* use Supabase's OAuth server support if the project's plan has it; otherwise a
  thin Next.js layer on id.superx.gg issues the codes on top of Supabase sessions.
- Each store keeps its own game session (`tc_portal`, Supabase cookie on its host) **minted
  from** the SuperX ID session, so store code changes are small.
- **Embedded on a non-superx domain** (the concierge iframe on a primerush.gg store): the
  store's server signs a 5-minute **player assertion** and hands it to the iframe by
  `postMessage`. Never via URL.

### 2.4 Proof levels (what each unlocks)

| Level | From | Support can |
|---|---|---|
| Anonymous | — | KB answers, general chat |
| Claimed | a typed SID | file a ticket |
| Proven | `game`, `otp`, `google`, `apple` with a linked player | purchases, collection, ban status, tickets, offers, actions |
| Staff | Google, allowed domains (GameGateway pattern) | everything, audited |

### 2.5 API (id.superx.gg)

| Route | Purpose |
|---|---|
| `POST /v1/launch/exchange` | server-to-server: store sends `{app_id, lt}` → SuperX session for that player |
| `GET /authorize`, `POST /token` | redirect sign-in for other domains |
| `GET /v1/me` | account + linked players (used by support and ops) |
| `POST /v1/links/otp/send`, `/verify` | link another game |
| `POST /v1/assertion` | short-lived player assertion for embeds |

### 2.6 Acceptance

- From inside MaskGun, tapping Support lands on `maskgun.superx.gg/support` signed in, no
  typing, under 3 s on a mid-range phone.
- Then opening `towerconquest.superx.gg` or `support.superx.gg` in the same webview is
  already signed in.
- A player with Prime Rush and MaskGun linked sees both on one account.
- No route anywhere accepts an unverified token or a bare SID as proof.
