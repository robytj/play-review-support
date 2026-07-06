# Spec: Discord Ticket Backfill + Shadow Review with Manual Approval

**Status: SPEC ONLY — do not execute until John approves each phase gate.**
Written 2026-07-05 (rev 3, per John's review) for a Sonnet agent working in this repo (`PrimeRush-Bot`).

## 1. Goal

Read **every existing ticket channel/thread under the Discord tickets category** (history, not just live messages), bring each into the support dashboard as a ticket, and for each one generate **what the bot's KB-based response would have been** — shown side-by-side with what staff actually replied, **editable and approvable by John** before anything is ever sent. All generated suggestions are **persisted forever** (never regenerated) and double as a **tone-training corpus**: agent-generated vs human-edited vs actually-sent, so the bot learns to replicate the support voice. The review UI is organized by **source — Discord, Freshdesk, Email** — with a consistent player-SID → game-admin link throughout. Finally, a settings-gated "Go Live via shadow" mode where the bot reads live tickets but **only posts responses John has individually approved** — never auto-replies.

Shadow mode (`config.yaml → discord.shadow_mode`, live-toggleable from the Support tab) is the permanent read-only design — **never remove the toggle or the live-reply code path** (see incident history, §3).

## 2. Hard constraints — non-negotiable

1. **Start REST-only.** Phases 0–5 use only Discord REST **GET** endpoints via plain `requests` — no `discord.py` gateway. Posting is structurally impossible and the bot never shows online. Only Phase 6 (Go Live, John-gated) reintroduces the gateway.
2. **`DISCORD_BOT_TOKEN` stays UNSET on Railway until Phase 6**, and John restores it himself following the Phase 6 checklist. Until then the token is used only by local scripts, loaded from local `.env`. It was removed as a kill-switch after the 2026-07-04 spam incident.
3. **Explicit channel scoping, verified before any fetch.** Only channels whose `parent_id` equals `DISCORD_TICKETS_CATEGORY_ID`, plus their threads. Phase 0 prints the category *name* and full channel list and STOPS for John's confirmation before a single message is fetched.
4. **Each phase produces an audit artifact and stops.** No phase begins until John reviews the previous phase's output and says go.
5. **Nothing is ever sent to Discord without a per-message human approval.** Even in Phase 6 there is no auto-reply path enabled. Auto-reply (`shadow_mode: false` full-live) remains a separate, later decision — out of scope here.
6. **Suggestions are immutable training data.** Once a `suggested_answer` is written it is never overwritten, regenerated, or deleted — edits go in `edited_answer`, regeneration is a *new* row (`supersedes_id`). The corpus of generated-vs-edited-vs-sent is a product asset (tone training, §Phase 7).
7. **No live env-var renames.** Never remove/rename a Railway variable that currently-deployed code reads (root cause #1 of the incident).
8. **Secrets:** token/keys from `.env` only. If John pastes a secret in chat, tell him to rotate it; never store it in code, commits, or docs.
9. Follow repo conventions: single-file scripts OK, `print("[info] ...")`/`[warn]` logging, try/except around I/O, inline WHY comments. Commit locally; John pushes himself (give him exact quoted-absolute-path commands).

## 3. Current state (verified 2026-07-05)

- **Repo:** this folder is the SupportBot repo (FastAPI + Discord bot in one Railway service, `https://primebot.up.railway.app`, SQLite at `/data/supportbot.db` on volume `web-volume`). Latest commit `5997ea9` (local, unpushed).
- **Bot:** `discord_bot/bot.py` handles only *live* `on_message` events — no historical backfill capability today. Bot is fully offline (token unset on Railway).
- **Shadow mode:** exists and defaults `true`. Live shadow flow: ingest → `router.answer()` → dashboard feed + 👀 reaction, no reply.
- **Ticket structure:** Ticket King creates one **private channel per ticket** under one category (`DISCORD_TICKETS_CATEGORY_ID`). The ticket is an embed from Ticket King's bot account with Portuguese fields — "Qual é o ID da sua conta?" (player SID) and "…sua dúvida ou problema?" (question). Parser exists: `_parse_ticket_king_card()` in `discord_bot/bot.py`; scoping rule is `_in_tickets_scope()`. Reuse both — don't duplicate the regexes.
- **Router:** `app/router.py answer()` = tier 0 canned → tier 1 answer_cache (approved only) → tier 2 Haiku RAG over **`status='published'`** kb_articles → tier 3 holding reply + `escalated`. Side effects: logs `messages`, bumps `metrics_daily`, tier 2 seeds `answer_cache` (unapproved), tier 3 marks conversation escalated.
- **KB:** John reports Freshdesk ingestion has now been run. **Verify, don't assume** — first action of Phase 2 is counting `kb_articles` by status/category on the live DB. Tier 2 only retrieves `status='published'` articles; drafts are invisible to the router.
- **Local `.env`: complete (updated 2026-07-05).** All Discord vars now set locally, copied from Railway's service variables (John provided them): `DISCORD_GUILD_ID`, `DISCORD_TICKETS_CATEGORY_ID`, `DISCORD_STAFF_ROLE_ID` (two comma-separated role ids — the existing `_STAFF_ROLE_IDS` parsing already handles this), `DISCORD_ESCALATION_CHANNEL_ID`, `DISCORD_BOT_TOKEN`, `FRESHDESK_DOMAIN`/`FRESHDESK_API_KEY`. Railway's copies are untouched (constraint 7). Note: the bot token was exposed in a session transcript on 2026-07-05 — John should regenerate it in the Discord developer portal and update `.env` before Phase 0; nothing depends on the old one (unset on Railway).
- **SID → admin link convention (keep consistent everywhere):** the player SID parsed from a ticket links to `https://admin.brx.indusgame.com/player/<SID>` — already used by the dashboard's Discord Tickets grid via `_discord_url`/enrich helpers in `app/dashboard_api.py`. Every new grid/section in this spec must render the same link wherever a SID is known, regardless of source.
- **Dashboard:** Support tab + SupportKB tab live in `play_reviewer.py` in the *other* repo (`/Users/roby1/github/robytj/play-review-responder`), calling this service's `/api/dashboard/*` with the shared service key. New UI goes there; new API endpoints go in `app/dashboard_api.py` here.
- **Network:** the Claude sandbox cannot reach Discord (verified 2026-07-05: connection reset by egress allowlist) or Freshdesk, nor download the fastembed model. **All scripts in this plan run on John's machine (or Railway console), not in the sandbox.** Agent writes code + runbook; John executes fetch/generation steps.

## 4. Design overview

```
Phase 0  discover      -> channels_audit.json + Ticket King deletion check   (GATE: John confirms)
Phase 1  fetch         -> raw JSON dump + DB ingest (source=discord)         (GATE: John reviews samples)
Phase 2  KB audit      -> coverage report: what KB can answer                (GATE: John reviews gaps)
Phase 3  replay        -> persistent suggestion per ticket + learnings report (GATE: cost approval first)
Phase 4  review UI     -> "Ticket Review" grid, tabs Discord|Freshdesk|Email,
                          edit + Approve                                     (GATE: John uses it)
Phase 5  KB enrich     -> draft KB articles FROM ticket data (all sources)   (GATE: John publishes drafts)
Phase 6  go live       -> settings "Go Live via shadow": token restore,
                          approve-to-send, one ticket at a time              (GATE: checklist, quiet window)
Phase 7  tone loop     -> generated-vs-edited-vs-sent corpus feeds style
                          examples into the RAG prompt                       (GATE: John A/B eyeballs)
Later    action buttons-> e.g. "Restore purchase" (manual then auto) — design room now, build later
```

New scripts: `scripts/backfill_discord_tickets.py` (`discover`, `fetch`, `replay`), `scripts/build_kb_from_tickets.py`. Plus dashboard endpoints + grid, approve-to-send path, tone-example injection in `app/llm.py`.

### Data model (migrations in `app/db.py _migrate()`, idempotent ALTERs like existing ones)

- `conversations.channel` gains new values: existing `discord | web`, plus **`freshdesk` | `email`** — this is the source dimension the UI filters on. `external_id` = Discord channel id / Freshdesk ticket id / email message-id.
- `conversations.origin TEXT DEFAULT 'live'` — backfilled rows get `'backfill'`. Backfilled conversations are created `status='resolved'` (staff already handled them; the live bot can never act on them).
- `messages.author_name TEXT DEFAULT ''` — display name for backfilled staff/player messages.
- New table `suggestions` — **the persistent, never-regenerated store** (lives in the same SQLite on the Railway volume; see backup note below). Used by backfill replay, Freshdesk/email replay, AND Phase 6 live shadow:
  ```sql
  CREATE TABLE IF NOT EXISTS suggestions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      conversation_id INTEGER NOT NULL REFERENCES conversations(id),
      source TEXT NOT NULL DEFAULT 'discord',   -- discord | freshdesk | email (denormalized from conversations.channel for cheap filtering)
      question TEXT NOT NULL,
      suggested_answer TEXT NOT NULL,      -- what the router generated. IMMUTABLE once written (constraint 6)
      edited_answer TEXT,                  -- John's edit; display/send uses COALESCE(edited, suggested)
      tier INTEGER,
      retrieved_chunks TEXT DEFAULT '',    -- json
      staff_answer TEXT,                   -- actual historical human reply (backfill; NULL for live until sent)
      status TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | sent | rejected
      approved_at TEXT, sent_at TEXT,
      discord_message_id TEXT,             -- set after a Phase-6 send, traceability
      supersedes_id INTEGER REFERENCES suggestions(id),  -- regeneration = new row pointing at the old one, never an overwrite
      created_at TEXT DEFAULT (datetime('now'))
  );
  ```
  Replay is idempotent by checking for an existing suggestion per conversation — **generation cost is paid once, ever**. No UPDATE path may touch `suggested_answer`; PATCH endpoints whitelist `edited_answer`/`status` fields only.
  Suggestions deliberately do NOT go into `messages`/`metrics_daily`/`answer_cache` — replay and pending drafts must not pollute the live pipeline.
- **Backup before big runs:** the runbook must include downloading a copy of `/supportbot.db` from the Railway volume (`railway volume files download`, same mechanism used for the 2026-07-04 upload) before Phases 3 and 5 the first time — the corpus is too valuable to risk.
- Future-proofing for action buttons (design only, **do not build actions now**): a `suggestion_actions(id, suggestion_id, action_type, payload_json, status, executed_at)` table sketch + an extensible `actions: []` field in the review-grid API response, so "Restore purchase" etc. can slot in later — manual trigger first, automation after.

## 5. Phases

### Phase 0 — Discover (read-only, no message fetching) + Ticket King deletion check

`python scripts/backfill_discord_tickets.py discover`

0. Pre-flight: local `.env` already has all Discord vars (done 2026-07-05, §3) — John just regenerates the bot token first (§3 note). Script still aborts with a clear error naming the missing var if any is unset — never fall back to "all channels".
1. `GET /guilds/{guild_id}/channels` → find the category, print its **name and id**; list every channel with `parent_id == category`, plus `GET /guilds/{guild_id}/threads/active` and archived threads of those channels.
2. **Deletion check — does Ticket King delete closed tickets?** (sandbox can't reach Discord; this runs on John's machine as part of `discover`):
   - Print the channel `created_at` distribution (Discord ids are snowflakes → creation time is free). If the server has months of ticket history but only recent channels exist under the category, closed tickets are being deleted.
   - Scan ALL guild channels (names only, no messages) for a Ticket King **transcript/log channel** (name matches `transcript|log|arquivo|fechado|closed`) — Ticket King-style bots typically post a transcript embed or attachment there when a ticket closes. If found, report it: that's where deleted-ticket history lives, and a follow-up fetch of *that one channel* (added to `channels_audit.json` under a separate `transcript_channel` key, with John's explicit OK) recovers older tickets.
   - `GET /guilds/{guild_id}/audit-logs?action_type=12` (CHANNEL_DELETE) — confirms deletion behavior directly, though Discord only retains ~45 days.
   - Also remind John to check the Ticket King bot's own dashboard/config for a "delete on close" vs "archive/transcript" setting — that's authoritative.
   - If tickets ARE deleted and no transcript channel exists: the Discord backfill covers only surviving channels; older history comes from Freshdesk (Phase 4's Freshdesk section) — state this plainly in the audit output.
3. Write `backfill_out/channels_audit.json`: category name/id, per-channel id/name/created_at, counts, deletion-check findings. Print a summary table.
4. **STOP.** John confirms: "yes, that's the tickets category, those are ticket channels" + decides whether to include the transcript channel.

Accept: audit file exists, category name matches, deletion behavior answered (or explicitly unknown with next step named), zero `/messages` requests made in the discover path.

### Phase 1 — Fetch history

`python scripts/backfill_discord_tickets.py fetch --confirm-category <id>`

1. Refuses to run unless `channels_audit.json` exists and `--confirm-category` matches it.
2. For each channel in the audit file only (plus the transcript channel if John opted in): `GET /channels/{id}/messages` paginated (100/page, honor 429 `retry_after`, sleep between pages). Same for threads. Transcript-channel messages get parsed back into per-ticket records from Ticket King's transcript embeds/attachments (best-effort; unparseable ones logged and skipped, never guessed).
3. Parse Ticket King embed per channel → `player SID`, `question`. Classify remaining messages: Ticket King/other bots → skip; staff = author has a `DISCORD_STAFF_ROLE_ID` role (fetch member roles; uncertain → `role='human'`, keep `author_name`).
4. Write raw dump first (`backfill_out/raw/<channel_id>.json`) — the audit artifact — then ingest into SQLite: one `conversations` row per ticket (`channel='discord'`, `origin='backfill'`, `status='resolved'`, `external_id`, `player_id`), `messages` rows for player (`role='user'`) and staff (`role='human'`). **Dedupe** on existing `external_id` (live shadow rows from 2026-07-04 testing).
5. Print summary: N channels, N with SID, N with a question, N with a staff reply, N recovered from transcripts, N skipped/empty.
6. **STOP.** John samples raw dumps + dashboard feed and approves.

Accept: every ticket channel under the category is in the DB exactly once; no Discord write occurred; raw dumps match DB rows on spot-check.

### Phase 2 — KB audit: what can we answer today?

John says Freshdesk ingestion has run — verify and report rather than re-run:

1. Query the live DB: `kb_articles` counts by `status` (draft/published) and `category`; `canned` count; `answer_cache` approved count. If zero articles → ingestion didn't actually land; run `FRESHDESK_INGESTION_RUNBOOK.md` and stop here.
2. Produce `backfill_out/kb_audit.md`: articles per category vs the 8 `KB_CATEGORIES`, thin/empty categories flagged, drafts awaiting publish (tier 2 ignores drafts — remind John to publish in SupportKB).
3. **STOP.** John reviews coverage and publishes whatever drafts he trusts before replay.

Accept: written report with real counts; John knows which categories the KB can and cannot answer yet.

### Phase 3 — Replay + learnings report (persistent, pay-once)

`python scripts/backfill_discord_tickets.py replay [--limit N] [--source discord|freshdesk]`

1. **Backup first** (§4 backup note), then **dry-run:** ticket count, published-KB count, estimated cost (≤1 Haiku call/ticket at ~400 max_tokens; embeddings local). Default `--limit 20` sample; full run only after John eyeballs the sample.
2. For each backfilled conversation with a question and **no existing suggestion** (persistence check — never regenerate): run the **tier cascade without side effects**. Do NOT call `router.answer()` (it bumps metrics, writes messages, seeds answer_cache, flips status). Add `router.suggest(question) -> {tier, text, chunks}` — same cascade, pure, sharing the tier helpers so logic can't drift; inline comment on why it must stay pure. Insert into `suggestions` with `source`, `staff_answer` = first staff reply.
3. **Learnings report** (`backfill_out/replay_learnings.md`) — the point of the exercise:
   - Tier distribution (tier 0/1/2 = KB had something; tier 3 = KB gap).
   - **Strong responses:** tier 0–2 where the suggestion substantially agrees with `staff_answer` (embed both, cosine similarity; report top/bottom).
   - **Needs human training / intervention:** tier 3s (no KB coverage) and tier 0–2s that *disagree* with staff (KB wrong or stale). Grouped by KB category so John sees *which topics* need work.
4. **STOP.** John reviews the report and the grid (Phase 4).

Accept: exactly one live suggestion row per ticket, immutable; re-running replay generates nothing new; `metrics_daily`, `answer_cache`, live statuses untouched (verify with before/after row counts).

### Phase 4 — "Ticket Review" grid: source tabs, edit + Approve, SID link

- **This repo (`app/dashboard_api.py`, all behind `require_service_key`):**
  - `GET /api/dashboard/suggestions?source=discord|freshdesk|email&origin=&tier=&status=` — joins `conversations` + `suggestions`; columns: created_at, **player SID linked to `https://admin.brx.indusgame.com/player/<SID>`** (same convention as the existing grid — one place to view/edit that player's support state), question, staff_answer, suggested_answer, edited_answer, tier, status, source, discord/Freshdesk link, plus empty `actions: []` (future buttons, §4).
  - `PATCH /api/dashboard/suggestions/{id}` — accepts **only** `edited_answer` (constraint 6: `suggested_answer` is untouchable).
  - `POST /api/dashboard/suggestions/{id}/approve` and `/reject` — set status + `approved_at`. **Approve does NOT send** in this phase; for backfill rows it marks "this is the answer I'd have wanted" — which feeds Phase 5 KB enrichment and Phase 7 tone training.
- **play-review-responder repo:** "Ticket Review" section in the Support tab of `play_reviewer.py`, proxying those endpoints. `@require_login` (SupportKB precedent). **Three tabs: Discord Tickets | Freshdesk Tickets | Email Tickets** (source filter; Email tab renders "no email source ingested yet" until an email ingestion exists — the filter/schema support it now so it's just data later). Clicking a row opens an edit panel: question + staff answer + editable bot response, Approve/Reject buttons, status chip, SID admin link. Filters: tier, status, has-staff-answer.
  - **Freshdesk tickets as reviewable rows:** extend the ingestion path (small addition to `scripts/ingest_freshdesk.py` or a flag) to ALSO write each pulled ticket as a `conversations` row (`channel='freshdesk'`, `origin='backfill'`, `status='resolved'`, `external_id`=ticket id) + `messages` (requester → `user`, public agent replies → `human`), so `replay --source freshdesk` and this grid work identically to Discord. **Freshdesk SID: best-effort extraction, not a field mapping.** John confirmed Freshdesk may not carry the SID as a separate field — so: check custom fields first if any look like an account id, otherwise regex-scan the ticket subject/description for SID-shaped values (derive the pattern from real SIDs in the Discord backfill — same ids Ticket King's "ID da sua conta" field carries — don't invent a format). No match → `player_id` NULL, row renders without the admin link; never guess a SID.
- Leave visual/DOM room in the edit panel for a future action-button row ("Restore purchase" etc.) — render from the API's `actions` array, empty for now.

Accept: John can switch source tabs, open a ticket from any source, edit the response, Approve, see status change, and jump to the player's admin page from the SID; nothing touches Discord.

### Phase 5 — Enrich the KB from ticket data (old closed tickets + live, all sources)

The data is already in our DB after Phases 1/4 — local script, no new external access:

1. New `scripts/build_kb_from_tickets.py`, modeled on `scripts/build_kb.py` (embed → greedy-cluster → one Claude call per cluster → draft article):
   - **Source A — old closed tickets** (Discord backfill + Freshdesk rows): conversations with both a question and a `staff_answer`/human reply — staff text is ground truth.
   - **Source B — approved suggestions:** `status='approved'` rows, using `COALESCE(edited_answer, suggested_answer)` (John's curated answers).
   - **Source C — ongoing live data:** same query naturally picks up `origin='live'` conversations with staff replies as shadow mode accumulates them — re-running later ingests new material. Idempotent via `kb_articles.source` ids (`discord:<id>` / `freshdesk:<id>` prefixes), already-used ones skipped.
2. Articles land as `status='draft'`, categorized by the existing keyword classifier — John reviews/publishes in SupportKB. Nothing auto-publishes.
3. Cost gate: print cluster count + estimated Claude calls before running; `--limit` flag. Backup DB first (§4).
4. After John publishes a batch, re-run Phase 3 replay with `--tier3-only` to measure improvement — learnings report becomes before/after. (Re-runs create *new* suggestion rows with `supersedes_id` set — the originals stay, per constraint 6.)

Accept: drafts visible in SupportKB sourced from tickets across sources; re-runnable as live data grows; nothing published without John.

### Phase 6 — "Go Live via shadow": manual approve-to-send, one ticket at a time

The bot starts reading **live** tickets (gateway, shadow mode ON) and John sends individually approved responses from the dashboard. Still no auto-reply.

1. **Code first, token later:**
   - Live shadow path (`bot.py` shadow branch) additionally inserts a `suggestions` row (`source='discord'`, `origin='live'`, `staff_answer` NULL) so live tickets appear in the same Ticket Review grid, status `pending`.
   - `POST /api/dashboard/suggestions/{id}/send` — only valid on `status='approved'` rows whose conversation is `origin='live'`, `channel='discord'`, and channel still exists; posts `COALESCE(edited_answer, suggested_answer)` via REST `POST /channels/{external_id}/messages`, sets `status='sent'`, `sent_at`, `discord_message_id`, logs a `messages` row (`role='bot'`). This is the **single** place in the entire system that writes to Discord, and it takes two explicit clicks (Approve, then Send) on a specific message. Guards: refuse if `shadow_mode` is false, refuse backfill rows, refuse non-discord sources.
   - Settings: a "Go Live via shadow" card in the Support tab settings — bot connection status + the checklist below. The `shadow_mode` toggle stays untouched and stays ON.
2. **Token restore checklist (John performs, in order — from the 2026-07-04 incident notes):**
   1. All this work pushed AND confirmed deployed on Railway (deployments page shows success).
   2. `shadow_mode: true` confirmed via Support tab.
   3. Quiet window — explicitly NOT during World Cup watch-party traffic.
   4. Restore `DISCORD_BOT_TOKEN` on Railway; watch logs for category-scoping + escalation-gating messages and gateway connect.
   5. **One-on-one test:** John opens a test ticket himself via Ticket King → sees it in Ticket Review → edits/approves → Send → verifies exactly one message in exactly that channel. Repeat with a sensitive-keyword ticket (expect tier-3 behavior, no send until approved). This is where John manually creates and tests responses before the bot ever touches a real player ticket.
   6. Only then let it watch real tickets — still approve-to-send only.
   7. Rollback: unset `DISCORD_BOT_TOKEN` (proven kill-switch); web service stays up by design.
3. Flipping `shadow_mode: false` (true auto-reply) is **out of scope** — a separate future decision after approve-to-send has a track record.

Accept: live tickets flow into the grid; a send happens only for an approved live suggestion; kill-switch documented; no auto-reply path enabled anywhere.

### Phase 7 — Tone learning loop (replicate the support voice)

The `suggestions` table now holds exactly the training signal John wants: what the agent generated vs what a human actually said/sent.

1. **Corpus queries** (no new tables needed):
   - *Correction pairs:* rows where `edited_answer IS NOT NULL AND edited_answer != suggested_answer` — John's direct tone/content corrections, the strongest signal.
   - *Historical voice:* backfill rows' `staff_answer` — how support has always talked to players (including Portuguese usage, greeting/sign-off habits).
   - *Blessed outputs:* `status IN ('approved','sent')` final texts.
2. **Application — keep it simple, no fine-tuning:** in `app/llm.py answer_with_rag()`, prepend a style block to the prompt: N most recent correction pairs rendered as "draft → how we actually say it" examples + M representative staff answers (selected once, cached, refreshed on demand via a dashboard "refresh tone examples" button — not per-call queries of the whole table). Token budget cap (~1–2k tokens); inline comment explaining selection.
3. **Measure:** re-run replay (`--tier3-only` off, small `--limit`, new rows via `supersedes_id`) and compare old vs new suggestions against `staff_answer` similarity; short before/after report. John eyeballs whether the voice got closer.
4. Later (out of scope): per-source tone (Discord casual vs email formal), automated eval.

Accept: RAG answers demonstrably borrow the support voice; corpus keeps growing from Phases 4–6 usage with zero extra work.

## 6. Explicitly out of scope

- Auto-reply mode (`shadow_mode: false`) — later, after Phase 6 track record.
- Building action buttons (restore purchase etc.) — schema/API leave room (§4), nothing more.
- Email ingestion pipeline — the Email tab, `channel='email'` value, and filters are built now; wiring an actual mailbox source is a follow-up John will scope.
- Removing or bypassing the shadow-mode toggle (permanent design).
- Original spec's web chat widget — still blocked on John supplying `support-bot-simple-spec.md`.
- Freshdesk KB-script changes beyond the small "also write conversations rows" addition in Phase 4.

## 7. Handoff checklist for the agent

1. `git status` first — check for stale lock files / stray staged index (has happened in this repo).
2. Build in phase order; commit locally per phase with clear messages; give John exact `git push` commands with full quoted absolute paths.
3. Everything network-touching (discover/fetch/replay/KB scripts/token restore) is run by **John locally or on Railway**, from commands you print — the sandbox has no Discord/Freshdesk egress (verified).
4. Ask John (don't guess):
   - Regenerate `DISCORD_BOT_TOKEN` in the Discord developer portal and update local `.env` (old one exposed in a transcript, §3) — before Phase 0.
   - Whether to include the Ticket King transcript channel (if Phase 0 finds one) in the fetch.
   - Confirm the Freshdesk ingestion actually populated the live DB (Phase 2 counts show it either way).
   (Env vars: already set locally, §3. Freshdesk SID: best-effort extraction per Phase 4 — no question needed.)
