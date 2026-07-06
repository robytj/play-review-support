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
Backend + data **DONE 2026-07-06** for To/From/Date; SID scaffolded (blocked on Mongo
mapping). Frontend lives in play-review-responder — paste-ready snippets in
`TICKET_REVIEW_FRONTEND_PATCH.md`. Enrichment: `scripts/enrich_ticket_metadata.py`
(idempotent, offline) persisted To/From/original-date into `conversations.context` for
all 2,855 tickets. API `/api/dashboard/suggestions` now returns `to_display`,
`from_display`, `reported_date`, `date_is_estimated` per row (`_ticket_meta()`).

1. **To** — DONE. email→recipient support address (from `support_emails.csv`, matched by
   gmail thread id); freshdesk→support inbox (`FRESHDESK_DOMAIN`); discord→
   `ticket-19 / <external_id>` (from `context.channel_name` + `external_id`).
2. **From** — DONE. email/freshdesk→sender email (`context.from`); discord→player's
   display name = first non-bot author, recovered from `backfill_out/raw/<id>.json` and
   persisted as `context.submitter` (Ticket King bot messages skipped).
3. **SID** — **BLOCKED (scaffolded)**. `scripts/resolve_sids.py` does the efficient
   dedupe→one bulk Mongo `$in` query→persist onto `conversations.player_id` (one-time,
   re-runnable). Needs env vars wired: `MONGO_URI/MONGO_DB/MONGO_PLAYERS_COLLECTION/
   MONGO_EMAIL_FIELD/MONGO_SID_FIELD`. Creds live in **play-review-responder's settings
   variables** (John, 2026-07-06); still OPEN: which DB/collection holds players + exact
   email/username→SID field names (§5). Do NOT invent a SID format. Once it runs,
   `admin_url` populates in the grid automatically.
4. **Date** — DONE. `reported_date` = original message date (real for email & discord;
   the freshdesk export carries no date, so `date_is_estimated=true` and the grid renders
   it softer). Discord dates corrected from import-stamp (2026-07-05) to real (e.g. 2026-06-26).

### 4B. SID-first support flow (design principle)
Every support interface (bot, web, review→future send) must **ask for / determine the
player's SID before any support action**. Bake this into the router/agent flow and the
future Phase-6 send path. For backfill review it's informational; for live it's a gate.
NOT YET BUILT — depends on the 4A #3 Mongo mapping (resolver) being live first.

### 4C. Translation (Haiku, cost-controlled) — DONE 2026-07-06
- `ticket_translations` table (mirrors `kb_translations`), keyed by
  `(suggestion_id, target_lang)`, added in `app/db.py _migrate()`.
- `app/llm.py`: `detect_language()` (offline stopword/codepoint heuristic, skips English
  for free) + `translate_text_fields()` (one Haiku call for all fields, `[[n]]`-delimited).
  Uses the existing `ANTHROPIC_API_KEY` + `RAG_MODEL` (already `claude-haiku-4-5-20251001`)
  — that resolves the old "which Haiku key" open question; no separate key needed.
- API `GET /api/dashboard/suggestions/{id}/translate?target=en`: cache-first; detects
  source lang; skips/echoes if already English; else translates once and caches.
- One-time batch `scripts/translate_tickets.py` (idempotent, resumable, `--limit` to meter
  spend). Run on John's machine / Railway (sandbox has no Anthropic network). Translates the
  latest suggestion per ticket (question + staff reply + final answer).

### 4D. Remaining spec phases (SHADOW_BACKFILL_SPEC)
- **Phase 6** go-live approve-to-send (the only Discord-write path; admin-gated; token
  restore checklist; `POST /suggestions/{id}/send` guarded to live+discord+approved only).
- **Phase 7** tone-learning loop: inject correction pairs (edited vs suggested) + strong
  staff answers as style examples into `app/llm.py answer_with_rag()`.

## 5. Open questions for the next session
- **MongoDB for SID resolution (4A #3 / 4B)**: creds are in play-review-responder's
  settings variables (John, 2026-07-06). STILL NEEDED before running
  `scripts/resolve_sids.py`: which DB name + collection holds players, and the exact field
  names for email→SID (and optionally discord username→SID). Wire them into
  `MONGO_URI/MONGO_DB/MONGO_PLAYERS_COLLECTION/MONGO_EMAIL_FIELD/MONGO_SID_FIELD` and
  `pip install pymongo`. Admin panel `admin.brx.indusgame.com/player/<SID>` remains the
  only confirmed SID surface. Do NOT invent a SID format.
- ~~Discord submitter username capture~~ — RESOLVED: recovered from `backfill_out/raw/`
  (author.global_name/username on the first non-bot message); no re-fetch needed.
- ~~Haiku key~~ — RESOLVED: existing `ANTHROPIC_API_KEY` + `RAG_MODEL`
  (`claude-haiku-4-5-20251001`). No separate key.

## 6. Where the code lives (changed/added this project)
PrimeRush-Bot: `app/db.py`, `app/router.py`, `app/dashboard_api.py`, `app/llm.py`,
`scripts/{classify_support_emails,load_email_tickets,load_freshdesk_tickets,build_kb_from_tickets}.py`,
`scripts/backfill_discord_tickets.py`, `BACKFILL_RUNBOOK.md`, `SHADOW_BACKFILL_SPEC.md`, this file.
2026-07-06 additions: `scripts/enrich_ticket_metadata.py` (To/From/Date enrichment, run),
`scripts/translate_tickets.py` (§4C batch, run on John's machine), `scripts/resolve_sids.py`
(§4A#3 SID scaffold, needs Mongo mapping), `TICKET_REVIEW_FRONTEND_PATCH.md` (frontend snippets).
play-review-responder: `play_reviewer.py` (nav link, `/ticket-review` page + `TICKETREVIEW_HTML`,
`/api/support/suggestions*` proxy routes).
