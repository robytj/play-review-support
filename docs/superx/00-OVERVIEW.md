# SuperX — platform spec · 00 · Overview

**Owner:** Roby · **Written:** 18 Oct 2026 · **Status:** draft v1 for review ·
**Supersedes:** `docs/SPEC-12-superx-support-integration.md` · **Mocks:** `outputs/superx-mocks/`

SuperX (superx.gg) is our web store and rewards platform. This spec adds the three things it's
missing so that every game's players and operators work in one place:

| Piece | Who | One line |
|---|---|---|
| **SuperX ID** | players | One sign-in across every game and every store, starting from inside the game |
| **support.superx.gg** | players | A concierge chat that knows the player and can get things done, in every store and from the game |
| **ops.superx.gg** | staff | The other side: every ticket and live chat, every game's store operations, and reports on what players want |

## The documents

| Doc | Covers |
|---|---|
| `01-SUPERX-ID.md` | single sign-in, game launch, linking games, sessions across domains |
| `02-SUPPORT-CONCIERGE.md` | the player experience: where support appears, the conversation style, per-game personalities, actions the concierge can take, resolution notifications |
| `03-OPS.md` | ops.superx.gg: inbox, live monitoring and takeover, store ops per game, reviews, reports |
| `04-PLATFORM.md` | architecture: game APIs, the support engine, where chats are stored, intent reports, OpenPing monitoring, OpenPush notifications, security |
| `05-ROADMAP.md` | fix-first list, phases, acceptance |

## What exists today (verified 18 Oct 2026)

| Domain | What | Code |
|---|---|---|
| `www.superx.gg` | landing | `LeeCory/superx.gg` (Vercel: community-tools) |
| `primerush.superx.gg`, `hub.primerush.gg` | Prime Rush Hub (collection, tasks, teams, creators) | `JuneSoftware/primerush-creators@main` |
| `shop.primerush.gg`, `loja.primerush.gg` | Prime Rush LATAM store | `primerush-creators@brx-store` |
| `store.primerushgame.com`, `store.primerushmena.com` | Prime Rush global and MENA stores | `primerush-creators@global-store`, `@mena-store` |
| `towerconquest.superx.gg`, `maskgun.superx.gg` | TC and MaskGun stores, one codebase, `SUPERX_GAME_ID` | `JuneSoftware/superx-tc` |
| `game-gateway.superx.gg` | backend availability status for game clients, Edge Config, Google-protected admin | `JuneSoftware/GameGateway` |
| `primebot.up.railway.app` | the support engine: chat agent, KB, tickets, takeover, ratings | `robytj/play-review-support` (PrimeRush-Bot) |
| responder (Railway) | ops dashboard: reviews, tickets, live chat, KB, cheaters, weapon meta | `robytj/play-review-responder` |

Support today: Prime Rush Hub's SUPPORT link goes to Discord. TC has `/support` with an FAQ
and a chat that calls our engine **anonymously, and gets Prime Rush answers** (05 · F1).
MaskGun has `/support` with an FAQ and email only.

## App ids

One set of ids everywhere (from GameGateway): `prime-rush-latam`, `prime-rush-global`,
`prime-rush-mena`, `tower-conquest`, `maskgun`. "Game" means the family (`prime-rush`);
"app" means one of the five builds.

## Decisions

| # | Decision |
|---|---|
| D1 | **SuperX ID** is new, built on the Prime Rush Supabase auth project (it already has Google, SID + inbox OTP, and the SuperX API trusts its tokens). No `xid-login` repo exists to build on |
| D2 | Every store on `*.superx.gg` shares one SuperX ID session. Stores on other domains sign in through `id.superx.gg` by redirect |
| D3 | The game opens support signed in: the client mints a one-time launch code and opens `<game>.superx.gg/support`; no typing a SID |
| D4 | Support appears in three places with one engine: a concierge button on every store page, a `/support` page in every store, and the hub at `support.superx.gg` |
| D5 | The support engine stays the PrimeRush-Bot service (FastAPI), made multi-game. The player UI is Next.js on Vercel next to the stores |
| D6 | Game data and actions go through the **same APIs the stores use**, moved behind one service (GameGateway v2) so stores, support and ops share them and store ops are configured once per game |
| D7 | The responder becomes **ops.superx.gg** |
| D8 | Chats move from SQLite to Postgres; every player message gets an intent record; an LLM writes a daily per-game report of what players want |
| D9 | **OpenPing** monitors support (site, widget, engine, a safe test conversation per game) |
| D10 | **OpenPush** (with in-game inbox mail and email) tells the player when their issue is resolved |
| D11 | One concierge, five personalities: shared rules, a per-game voice learned from each game's own players |
| D12 | Branding: "SuperX Support". The White Glove name is dropped |

## Open questions

1. Which Supabase project is the Prime Rush auth project — `kqzyvanoevklcipnzxzj` or
   `uqqagabepyqsquxvrvnf` — and does `www.superx.gg` use the same one?
2. Can the TC and Prime Rush backends add a launch-code exchange like MaskGun's
   `/web/v1/launch/exchange`? (Needed for D3.)
3. Who owns GameGateway (sreejitj per the last commit)? D6 grows its scope.
4. Persona characters for each game — proposals in `02` §4; Tower Conquest and Prime Rush
   MENA need a named character from their rosters.
5. `superx.gg` auto-renew is off (expires 2027-06-11).
