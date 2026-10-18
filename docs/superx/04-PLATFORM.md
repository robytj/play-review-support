# SuperX — 04 · Platform

## 1 · Shape

```
 game clients ──lt──▶ <game>.superx.gg (stores, Vercel) ──┐
                     support.superx.gg (player UI, Vercel)├──▶ id.superx.gg (SuperX ID)
                     ops.superx.gg (staff, Railway) ───────┘
                              │                    │
                              ▼                    ▼
                  support engine (FastAPI)   GameGateway v2 (game APIs)
                  chat · KB · tickets ·      profile · wallet · orders · grants ·
                  intents · personas         mail · coupons · availability
                        │                          │
                    Postgres                game backends: Prime Rush (SuperX API / brx),
                                            Tower Conquest (game API), MaskGun (/web/v1)
             OpenPing watches all of it · OpenPush + inbox mail notify players
```

## 2 · Game APIs: one service, same calls the stores make

Today each store holds its own copy of the game calls: superx-tc in
`games/{tower-conquest,maskgun}/server/adapter.ts` (TC envelope + `X-Agent-*` HMAC,
MaskGun `X-MG-*` HMAC), Prime Rush in `primerush-creators` (SuperX API with Supabase or
service-role bearer, Indus service-auth). Support and ops need the same calls.

**Move them behind GameGateway** — already "a shared API gateway providing common services
… for all games", already deployed, already keyed by app id:

| Endpoint (server-to-server, service key + player assertion where player-scoped) | Wraps |
|---|---|
| `GET /v2/apps/{app}/players/{id}` profile, wallet, owned | TC `WebProfile`/`WebWallet`; MG `/players/profile`, `/wallet`; PR `/users/me`, `/profile` |
| `GET /v2/apps/{app}/players/{id}/orders` | TC `store_transactions`; MG `/purchases/*`; PR transactions |
| `POST /v2/apps/{app}/players/{id}/orders/{order}/redeliver` | TC `WebFulfil`; MG `/purchases/fulfil`; PR grant |
| `POST …/mail`, `…/coupons`, `…/equip`, `…/claim` | inbox mail, coupon ledgers, equip, free offers |
| `GET /v1/apps/{app}/api-status` | unchanged |

Stores switch to these over time (no rush — the adapters keep working); support and ops use
them from day one. Keys live in one place; each caller gets its own key and scope (support
can't call store-ops endpoints). Rate limits and an audit log per call.

## 3 · Support engine

The PrimeRush-Bot service (FastAPI on Railway), extended:

- `app_id` on every table and every request; per-app KB, persona, tone block, eval set.
- Player identity only from SuperX ID tokens or assertions; the public `/chat` endpoint is
  retired once TC moves to the concierge (until then: keyed and rate-limited, 05 · F2).
- Tools = GameGateway v2 calls (02 §5), each with a proof check, idempotency key and audit.
- Model routing: cheap tiers first (canned → approved answers → KB), Claude for the rest,
  per-app daily budgets; personas add a style block, not a different model.

## 4 · Where chats are stored, and how we learn from them

**Now:** SQLite on the Railway volume — `chat_sessions`, `chat_messages`, `chat_intent_log`,
`conversations`, `messages`, `suggestions`, `ticket_events`, KB with `sqlite-vec`.

**Move to Postgres** (Railway, pgvector — the same stack OpenPush specced). Single writer
SQLite won't take five apps of live chat, and reports need SQL across games.

| Table | Holds |
|---|---|
| `conversations` | one per issue: app, player (SuperX account + game player), channel, status, priority, SLA |
| `messages` | every bubble: role (player/concierge/staff/system), text, reactions, tool calls, model + cost |
| `intents` | **one per player message**: intent, sub-intent, entities (item, order, mode), sentiment, language, confidence, outcome (answered / acted / handed off / unanswered) |
| `actions` | every concierge or staff action: tool, args, result, approver |
| `notifications` | every resolution push/mail/email: channel, delivered, opened |
| `ratings`, `ticket_events` | as today |

Intents are tagged at write time by the cheap classifier that already gates chat (typo-
tolerant intents + scope gate), with an LLM pass in batch for the ones it isn't sure about.
The daily per-game digest (03 §5) reads `intents` + a sample of `messages`.

Retention: messages 18 months, intents kept aggregated after that; no payment card data
ever; PII (emails) masked in reports; players can ask for their history and deletion.

## 5 · Monitoring: OpenPing

OpenPing already checks sites, APIs, jobs and AI agents ("handshake, sign-in, tool list, a
safe test call") and watches Zero. Point it at support:

| Monitor | Check | Every |
|---|---|---|
| support.superx.gg, each store's `/support`, `widget.js` | loads, under 2 s | 5 min |
| engine `/health`, Postgres, GameGateway | up, latency | 1 min |
| **Agent test per app** | a scripted conversation with a test player: "where's my purchase?" → answer mentions the seeded order; "is this game X?" → refuses | 15 min |
| Persona eval | 20 saved conversations per app, graded | daily |
| Notification path | test push + inbox mail to a test player | hourly |
| Intent spikes (03 §5) | alert on 3× baseline | live |

Second region confirms before paging; status page at `status.superx.gg`; alerts to Slack.

## 6 · Notifications: OpenPush + inbox + email

The resolution message (02 §6) goes through one notify call with ordered fallbacks: live chat
→ OpenPush push (MaskGun via OneSignal until it migrates) → in-game inbox mail → email.
Deep link: `https://<game>.superx.gg/support?c=<conversation>` opened in the game's webview.
OpenPush's player inbox is the long-term home for these messages.

## 7 · Security

- No unverified tokens, no bare SIDs as proof (fixes 05 · F3).
- Secrets only in env; rotate the hard-coded service-auth key (05 · F4).
- CSP: stores allow `frame-src https://support.superx.gg`; support sets `frame-ancestors` to
  the store domains; `postMessage` origin-checked.
- Every action audited; money-moving actions beyond re-delivery need a human.
- Rate limits per IP, per account and per app; per-app model budgets.
