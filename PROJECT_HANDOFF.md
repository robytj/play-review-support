# PrimeRush SupportBot — Project Handoff

Last updated: 2026-07-06. This is the single import-me doc for continuing the project
in another session/account. Pairs with `BACKFILL_RUNBOOK.md` (operational commands)
and `SHADOW_BACKFILL_SPEC.md` (the phased Discord plan).

## 0. Goal

Unify all support channels (Freshdesk, email, Discord) into one local ticket store and
build an automated support agent + KB + agentic response workflows trained on prior
support history. Every generated answer is reviewable/approvable by John; nothing is
auto-sent yet. The ticket DB is the training/reference corpus.

## 1. Two repos / two Railway services

- **PrimeRush-Bot** (this folder, `/Users/roby1/Documents/Claude/Projects/PrimeRush-Bot`)
  = the **SupportBot** service → deploys to `https://primebot.up.railway.app`.
  FastAPI + (offline) Discord bot in one Railway service. SQLite at `/data/supportbot.db`
  on volume `web-volume`. Serves `/api/dashboard/*`.
- **play-review-responder** (`/Users/roby1/github/robytj/play-review-responder`)
  = the **Ops dashboard** (`play_reviewer.py`, one big Flask file with inline HTML).
  Proxies to SupportBot's `/api/dashboard/*` using `SUPPORTBOT_API_URL` +
  `SUPPORTBOT_API_KEY` (must equal SupportBot's `SUPPORT_SERVICE_API_KEY`).

Sandbox note: the Claude sandbox has **no network to Discord/Freshdesk** and can't
download the embedding model — all fetch/replay/build-KB steps run on John's machine
or the Railway console. The sandbox CAN read/write the mounted repo folders (incl. the
local `data/supportbot.db`, which is how progress was inspected here).

## 2. What's DONE (live on primebot after 2026-07-06 deploy + DB sync)

**Data pipeline**
- Email KB export: 2,733 support threads since Oct 2024 → `support_emails/` + `support_emails.csv`
  (Gmail filter `to:(help@ OR support@ OR primerush@ OR indusgame@ OR primerushsupport@) after:2024/09/30 in:anywhere`).
- Classifier (`scripts/classify_support_emails.py`): kept 2,622 real support; moved 111
  marketing/internal/noise/automated to `support_emails_excluded/`.
- Unified ticket store in `data/supportbot.db` (all `status='resolved'`, `origin='backfill'`):
  **email 2,622 + freshdesk 203 + discord 30** conversations. Loaders:
  `scripts/load_email_tickets.py`, `scripts/load_freshdesk_tickets.py`.
- Discord backfill: `scripts/backfill_discord_tickets.py` (`discover`/`peek`/`sample`/`fetch`/`replay`,
  multi-category via `--category`). Only ~30 surviving tickets (Ticket King deletes closed
  ones; `《 TICKETS 》` category is 403/no-bot-access). Ticket categories:
  `1423320403253657752,1519485091666071712,1519485217927073872,1519485302513733785,1519485373619634326`.

**KB + replay**
- KB: 108 published articles (99 from Freshdesk export + 9 from Phase-5 gap distillation
  via `scripts/build_kb_from_tickets.py --gaps-only`). `build_kb.py` builds from freshdesk_export.json.
- Pure `router.suggest()` (no side effects) replays each ticket. `replay --tier3-only`
  re-evaluates gaps after publishing KB (new rows w/ `supersedes_id`, originals kept).
- Final coverage: **2,677 tier-2 / 149 tier-3** (latest-per-ticket) = **94%**. Residual gaps
  are mostly non-actionable (no staff reply — diamond-begging, one-liners).
- `suggestions` table: ~5,801 immutable rows (agent-vs-staff corpus), 205 strong staff-agreement matches.

**Review UI (Phase 4)** — in play-review-responder:
- Page `/ticket-review` (nav "Ticket Review"): source tabs (All/Discord/Freshdesk/Email),
  tier+status filters, grid, click-to-expand detail (question, staff reply, immutable
  suggestion, editable `edited_answer`, Approve/Reject, status chip, SID→admin link).
- Proxy routes `/api/support/suggestions[/summary,/<id> PATCH,/approve,/reject]`.
- Grid + badges show only the **latest** suggestion per ticket (superseded rows hidden).

**Backend API (SupportBot, `app/dashboard_api.py`)**
- `/feed?channel=&status=`, `/channels` (per-source counts), `/suggestions` (+summary,
  PATCH edited_answer-only, approve, reject). Immutability enforced (constraint 6).
- Migrations in `app/db.py _migrate()`: `conversations.origin`, `messages.author_name`,
  `suggestions` + `suggestion_actions` tables (idempotent).

**Deploy state**: both repos' code deployed; local DB uploaded to primebot volume
(`railway volume files upload ./data/supportbot.db /data/supportbot.db --overwrite`).
`/api/dashboard/suggestions/summary` returns real counts. Ticket Review is populated.

## 3. Key facts & gotchas
- **No SID on most tickets.** This server's Ticket King "Ticket Aberto" card has empty
  fields — no SID/question form. Email/Freshdesk tickets mostly lack a SID field too.
  So the SID→`https://admin.brx.indusgame.com/player/<SID>` link is usually blank today.
- **Dates shown are import dates.** Conversations got `created_at` from message dates where
  available, but the grid currently renders `suggestions.created_at` (the replay time =
  today), not the original ticket date. See Pending #4.
- **Rotate `SUPPORT_SERVICE_API_KEY`/`SUPPORTBOT_API_KEY`** — it was pasted in chat.
- **DB location**: work happens on local `data/supportbot.db`; Railway has its own volume
  copy. Re-sync after local changes (BACKFILL_RUNBOOK §C.5).
- **PII**: `support_emails/`, `support_emails_excluded/`, CSVs, `backfill_out/`, `*.db`
  are gitignored — real player emails, never commit.
- Verify SQL counts with the csv/sqlite modules, not `wc -l` (bodies contain newlines).

## 4. PENDING — next series of steps (from John's 2026-07-06 request)

### 4A. Add 4 columns to the Ticket Review grid (all sources)
1. **To** — recipient of the ticket. Freshdesk: the support email address it was sent to;
   Email: the `to` address; Discord: the channel name + ticket ID (e.g. `bugs / ticket-19`).
   Data: email/freshdesk `to` is in `messages`/`conversations.context`; Discord channel
   name + id are in `context.channel_name` + `external_id` (fetch stores these).
2. **From** — the player identity. Email/Freshdesk: sender email (already prefixed into the
   stored message text `[email] ...`; better: parse to a dedicated field). Discord: the
   ticket submitter's **discord username** — NOTE current fetch stores `author_name` on
   messages but the card author is Ticket King; the real player is the first non-bot
   author. May need a fetch tweak to capture/display the submitter username per ticket.
3. **SID** — use the extracted SID if present; otherwise resolve via the player's **email →
   MongoDB lookup**. Must be efficient: batch/dedupe emails, one bulk Mongo query (or a
   cached map), run as part of a one-time ticket-verification pass, not per-render or
   per-row. Persist resolved SID onto `conversations.player_id` so it's not re-queried.
   OPEN: confirm Mongo access/credentials + the players collection + the email/username →
   SID field mapping (see §5). Do NOT invent a SID format.
4. **Date** — show the **original message date** (first message's date) instead of the
   import/replay date. Store/derive from `conversations.created_at` or the first message's
   `created_at`; fall back to a "reported date" label if unknown.

### 4B. SID-first support flow (design principle)
Every support interface (bot, web, review→future send) must **ask for / determine the
player's SID before any support action**. Bake this into the router/agent flow and the
future Phase-6 send path. For backfill review it's informational; for live it's a gate.

### 4C. Translation (Haiku, cost-controlled)
- Much content is Portuguese/Spanish/etc. Add a **translate option** in the Ticket Review
  detail (and later the agent) using a **Haiku** API key to keep costs low.
- For existing DB tickets: translate **once** and cache (e.g. a `translations` table keyed
  by (conversation_id/message_id, lang) — mirror the existing `kb_translations` pattern in
  `app/db.py`), not per-view. Batch the one-time pass; detect source language and skip
  English. Reuse `app/llm.py` translate helpers where possible.

### 4D. Remaining spec phases (SHADOW_BACKFILL_SPEC)
- **Phase 6** go-live approve-to-send (the only Discord-write path; admin-gated; token
  restore checklist; `POST /suggestions/{id}/send` guarded to live+discord+approved only).
- **Phase 7** tone-learning loop: inject correction pairs (edited vs suggested) + strong
  staff answers as style examples into `app/llm.py answer_with_rag()`.

## 5. Open questions for the next session
- **MongoDB for SID resolution**: what connection/credentials exist, which DB/collection
  holds players, and what field maps email/username → SID? (John raised MongoDB lookup;
  the admin panel `admin.brx.indusgame.com/player/<SID>` is the only confirmed surface.)
  Needed before 4A #3 and 4B can be built.
- Discord submitter username capture: confirm whether fetch already retained it (author_name
  on the first non-bot message) or needs a re-fetch.
- Haiku key: which key/env var to use for translation.

## 6. Where the code lives (changed/added this project)
PrimeRush-Bot: `app/db.py`, `app/router.py`, `app/dashboard_api.py`,
`scripts/{classify_support_emails,load_email_tickets,load_freshdesk_tickets,build_kb_from_tickets}.py`,
`scripts/backfill_discord_tickets.py`, `BACKFILL_RUNBOOK.md`, `SHADOW_BACKFILL_SPEC.md`, this file.
play-review-responder: `play_reviewer.py` (nav link, `/ticket-review` page + `TICKETREVIEW_HTML`,
`/api/support/suggestions*` proxy routes).
