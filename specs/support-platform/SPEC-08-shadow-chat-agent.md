# SPEC-08 — Shadow Chat Agent (internal testing tab)

*Approved by John 2026-07-07. Scope: primerush.gg (LatAm SKU) only. English only. All
logged-in dashboard users. Deploy: straight to Railway. Full SPEC-03 pipeline from day 1.*

## 1. Shape

- **Brain**: SupportBot (PrimeRush-Bot), new key-gated endpoints under
  `/api/dashboard/chat/*`. Same engine later powers support.primerush.gg.
- **Skin**: new "Support Chat" tab in the Ops Dashboard (play-review-responder), proxied
  via the existing `_supportbot_request` pattern (`/api/support/chat/*`).
- **Shadow semantics**: every session persists (`chat_sessions` + `chat_messages`,
  `shadow=1`) for training/exploit review; excluded from tone learning and metrics_daily.

## 2. Conversation state machine

`GREET → ASK_GAME → ASK_SID → CONFIRM_NAME → RECOGNITION → ISSUE_LOOP → (RESOLVED | ESCALATED | EXPIRED | ENDED)`

1. **GREET**: bot speaks first on open. Warm 1-liner + ask which game
   (chips: PrimeRush.gg (LatAm) · PrimeRushGame (Global) · Prime Rush MENA).
   Non-LatAm choice → note "this test supports PrimeRush.gg" and continue. Choice is
   conversational only; stored on the session.
2. **ASK_SID**: ask for SID. Validate → Mongo `account.shortId` lookup. Fail → re-ask, max
   **3 attempts**, then offer **image upload** (screenshot of profile/settings); Haiku
   vision extracts a SID-shaped string (max 2 images/session), re-validate. Still nothing
   → continue in degraded mode (KB-only answers, no account data) with a system note.
3. **CONFIRM_NAME**: show `nickname` + SID + email (masked) — "You're <nickname>, right?"
   Yes/No chips. **No** → "I couldn't find you — can you share your SID again?" (returns
   to ASK_SID, attempts counter continues).
4. **RECOGNITION**: thank for playing since `createTime` (month year) + `matchesPlayed`
   games, then one highlight picked deterministically by priority:
   `matchMvpCount > longestKillStreak > totalWins > totalTimeSpent` (from aggregated
   `user.stats`). Facts computed server-side; **one** Haiku call phrases them (strict
   prompt: only the provided facts, ≤ 2 sentences, warm, specific, no invention);
   template fallback on LLM failure. Everything is fair game while shadow testing.
5. **ISSUE_LOOP**: "What can I help you with?" Then per message:
   scope gate → tiered router / data lookups → reply. Exits: resolved (CSAT 👍) /
   escalated / timeout / manual end.

**Timeout**: idle 5 min → "Still there?" nudge; idle 10 min → session auto-closes
(`end_reason='timeout'`) with a goodbye + "start a New Chat anytime". Enforced lazily
server-side (on next request + list sweeps); frontend shows the nudge via its own timer.

## 3. Per-message pipeline in ISSUE_LOOP (SPEC-03, full)

1. **Scope gate** (`app/scope_gate.py`, local fastembed centroids, $0):
   classes = 8 KB categories + `smalltalk`, `human_request`, `abuse`, `out_of_scope`.
   Category centroids seeded from published KB articles (title+symptom embeddings);
   out_of_scope/smalltalk/human_request from handwritten seed lists. `out_of_scope`/`abuse`
   → canned deflection, zero tokens, 3 strikes → polite end. `human_request` → escalate.
2. **Cross-player guard (hard)**: any SID-pattern token in the message ≠ session SID →
   refusal template ("I can only help with the account we verified"). All Mongo lookups
   are keyed to the session's resolved `userId` — there is no code path that queries
   another player. Prompt-level rule as backstop.
3. **Data intents** (before generic RAG):
   - **Purchases** (category Payments & Purchases or keyword match): summarize
     `user.transaction` for the session userId — real-money count, first/last purchase
     dates, payment systems, up to 5 recent entries with status where fields exist
     (succeeded/failed shown; tolerant `.get()` fallbacks — exact per-item fields to be
     confirmed by the probe, see §6). Bot states **summaries only**, no raw records.
   - **Ban/appeal**: if `account.state` ∈ BANNED_STATES (`Locked,Suspended,Banned`) or
     chatBanned — assemble a staff-facing **ban assessment card**: state, report count
     (90d, `user.reported`), banned-device overlap, payer tier (ACTIVE/DORMANT/LAPSED/NONE
     from transactions). Bot replies to the "player" only from an approved-message set
     (new canned category `ban_response` — seeded with 4 drafts for the team to
     review/approve in SupportKB). It never promises an unban; the card + genuineness
     signals are for the human tester to evaluate. (Hacker-score from the responder's
     local DB is a noted follow-up, not v1.)
4. **Tiered router**: `router.suggest()` (pure, no side effects) — Tier 0 canned → Tier 1
   answer cache → Tier 2 Haiku RAG (max_tokens 400, top_k per config) → Tier 3.
   Clarify-or-answer: retrieval confidence in [tau_clarify, tau_retrieval] → chips from
   top-2 article titles, one round max.
5. **Tier 3 / human_request** → **escalation**: create a real ticket — `conversations`
   row (origin='live', `public_id`) + player/bot `messages` + a tier-3 `suggestions` row
   with **`source='chat'`** carrying issue summary + SID + ban/purchase context in the
   question body. Shows in Ticket Review under a new **Chat** source filter. Chat renders
   an escalation card with the ticket id.
6. **Budgets**: 8 Tier-2 calls/session (then Tier 0/1/escalate only), 30 messages/session,
   daily global Tier-2 cap (config `chat_budgets.daily_tier2_calls`, default 300) →
   breach = deflect-and-escalate mode. Counters in `chat_usage`.

## 4. API (all Bearer service-key, `/api/dashboard` prefix)

| Route | Purpose |
|---|---|
| `POST /chat/sessions` | new session → `{session_id, messages[]}` (greeting) |
| `POST /chat/sessions/{id}/messages` `{text}` | advance → `{messages[], state, budget}` |
| `POST /chat/sessions/{id}/image` (multipart) | SID extraction from screenshot |
| `POST /chat/sessions/{id}/end` `{reason}` | close (manual / timeout) |
| `GET /chat/sessions/{id}` | full transcript + state (restore) |
| `GET /chat/sessions?limit&offset` | list sessions for review |

Bot messages are typed: `text | chips | context_card | recognition | ban_card |
escalation_card | csat | system`. Chips echo back as user text on tap.

## 5. Storage (SupportBot SQLite)

- `chat_sessions(id, created_at, last_activity_at, state, game_choice, sid, player_name,
  mongo_user_id, shadow DEFAULT 1, tier2_used, msg_count, sid_attempts, image_attempts,
  strikes, escalated_conversation_id, ended_at, end_reason)`
- `chat_messages(id, session_id, role, type, content, meta_json, created_at)`
- `chat_usage(day, tier2_calls, sessions, escalations)`
- Shadow sessions are **excluded** from `metrics_daily` and the tone corpus (guard in
  code, not convention).

## 6. Player context (`app/player_context.py`) — code-confirmed Mongo schema

Read-only, projection-only, keyed to one userId; every source degradable to None.
Fields confirmed from the responder's cheater/payments modules (brx_main):

- `account`: `_id`(int), `shortId`, `nickname`, `state` (Active|Guest|+BANNED_STATES),
  `level`, `matchesPlayed` (fallbacks `matchesCount`, `stats.matchesPlayed`),
  `createTime`, `location`, `buildVersion`, `chatBanned`, `email.id`,
  `userDevices[].device.{deviceId,type}`.
- `user.stats` (rows per mode/season): totalKills, totalWins, totalLosses, totalDamage,
  totalHeadshotKills, longestKillStreak, matchMvpCount, totalTimeSpent → aggregate.
- `user.transaction`: `userId`, `pricingOption.paymentSystem` (Google/Apple/Xsolla/…;
  set = real money), `purchasedTime`; per-item product/status fields **to be confirmed**
  via probe. Collections `purchase.aggregated`, `topspender.*` exist (webstore purchases
  possibly there — probe will tell).
- `user.reported`: count by `reportedUser` since cutoff. `banned.device`: `_id` overlap
  with the player's deviceIds.
- Env: `MONGO_URI` (same read-only user as the responder's cheater module — **copy the
  env var to the SupportBot Railway service at deploy**), existing
  `MONGO_ACCOUNT_COLLECTION`/field vars unchanged.
- `scripts/probe_player_context.py`: read-only validation against the 8 sample SIDs
  (EDFXPT5G, 2S6WGTSK, Y3MXP81Y, TEPFTFMN, VAHE3PVK, BSMMQXYM, G32KQ2JH, DX4GW6CS) —
  prints resolved context + unknown-field report; run on Railway or any machine with
  `MONGO_URI` before flipping the tab live.

## 7. Dashboard tab (play-review-responder)

- Nav link **Support Chat** (`/support-chat`) for all logged-in users; inline-HTML page in
  the existing style. Transcript pane + composer + **New Chat** button + session state
  chip (SID/player once confirmed) + budget indicator (n/8) + idle-nudge timer + image
  attach on request. Proxy routes `/api/support/chat/*` → SupportBot 1:1.
- Ticket Review: accept `source='chat'` (filter option + badge); escalated chat tickets
  open with the context summary. (Full ticketing-system buildout — assignees, priorities,
  SLA — is a separate follow-up spec, noted not included here.)

## 8. Non-negotiable guardrails (tested)

1. No answer outside KB + the session player's own data (scope gate + grounded tiers).
2. No cross-SID data access — enforced structurally (all queries session-keyed).
3. No invented policy/price/compensation; ban replies only from approved set.
4. Shadow data never enters tone corpus or metrics.
5. Budgets enforced in code; kill switch: `chat_enabled` in Support Settings.
