# Unified Support Store + Discord Backfill — Runbook

Status as of 2026-07-05. Covers the email/Freshdesk ingestion already done, and the
Discord backfill code (SHADOW_BACKFILL_SPEC.md) now built and ready for you to run.
The Claude sandbox has **no network path to Discord/Freshdesk and can't download the
embedding model**, so every network/LLM step below runs on **your machine or Railway** —
the sandbox only wrote code + local DB rows.

Repo: `/Users/roby1/Documents/Claude/Projects/PrimeRush-Bot`

---

## A. Already done (local, safe, reversible)

1. **Email KB export** — 2,733 support threads since Oct 2024 in `support_emails/` + `support_emails.csv`.
2. **Classifier** — `scripts/classify_support_emails.py` kept 2,622 real player-support threads; moved 111 partnership/marketing/internal/automated to `support_emails_excluded/` (with `manifest.csv`). Backup of the pre-filter CSV: `support_emails_all.csv`. Reversible: move files back and re-run loaders.
3. **Local ticket DB** (`data/supportbot.db`) now has, as CLOSED tickets:
   - `channel='email'` — 2,622 (`origin='backfill'`)
   - `channel='freshdesk'` — 203 (`origin='backfill'`)
   Loaders (idempotent, re-runnable): `scripts/load_email_tickets.py`, `scripts/load_freshdesk_tickets.py`.
4. **Schema migrations applied** (`app/db.py _migrate()`): `conversations.origin`, `messages.author_name`, `suggestions` table, `suggestion_actions` sketch.
5. **Pure `router.suggest()`** added (no side effects) — replay uses it; `answer()` behavior unchanged (shared pure lookups).
6. **Dashboard API** (`app/dashboard_api.py`): `/feed?channel=&status=`, `/channels` (section counts), plus the Ticket Review backend `/suggestions` (list/filter), `PATCH /suggestions/{id}` (edited_answer only — `suggested_answer` is immutable), `/suggestions/{id}/approve|reject`, `/suggestions/summary`.

Reversal SQL if ever needed:
```sql
DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE origin='backfill');
DELETE FROM conversations WHERE origin='backfill';
```

---

## B. Before you start the Discord phases — gate questions

1. **Regenerate `DISCORD_BOT_TOKEN`** in the Discord developer portal and update local `.env` (the old one was exposed in a transcript). Nothing on Railway depends on it (still unset there).
2. If Phase 0 finds a **transcript/log channel**, decide whether to include it in the fetch (`--include-transcript`).
3. Phase 2 will show whether **Freshdesk KB ingestion** actually populated the live DB — no need to guess.

`DISCORD_BOT_TOKEN` stays **UNSET on Railway** until Phase 6. All Discord vars are read from local `.env` only.

---

## C. Run these on your machine (from the repo dir)

```bash
cd /Users/roby1/Documents/Claude/Projects/PrimeRush-Bot
python3 -m venv .venv && source .venv/bin/activate   # if not already
pip install -r requirements.txt                       # discord REST via requests, embeddings model, etc.
```

### Phase 0 — discover (read-only, no messages fetched)

**Confirmed 2026-07-05 via `peek`:** this server routes tickets into FIVE topic
categories (all children named `ticket-N`). Use this exact set:
```
1423320403253657752  《 TICKETS 》     (48, historical; most closed tickets deleted)
1519485091666071712  dúvidas-gerais    (12)
1519485217927073872  bugs              (8)
1519485302513733785  reivindicar-premio(4)
1519485373619634326  financeiro        (1)
```
The `🎟️┃tickets` panel channel (id 1519489368220368968) is NOT a ticket and is auto-skipped by `fetch`.
**Deletion finding:** Ticket King deletes closed tickets (numbers reach ticket-3086, only ~72 survive) — Discord backfill recovers only surviving tickets; the historical corpus is the already-loaded email (2,733) + Freshdesk (203).

```bash
python scripts/backfill_discord_tickets.py peek --category <ids>      # list channel names (optional re-check)
python scripts/backfill_discord_tickets.py discover --category 1423320403253657752,1519485091666071712,1519485217927073872,1519485302513733785,1519485373619634326
```
`--category` overrides `DISCORD_TICKETS_CATEGORY_ID` (or set it in `.env` and omit the flag). Writes `backfill_out/channels_audit.json` + summary, then STOPS.

**Phase 0 gate decisions (2026-07-05, from `sample`):**
- **Transcript channels: EXCLUDED.** `logs-tickets` holds only Ticket-King open/close *event* embeds (metadata: ticket name, opener, closer, close reason, staff msg count) — NO conversation content, so nothing to recover. `┃closed-bugs` and `┃logs` return 403 (bot has no read access). Deleted tickets are unrecoverable on Discord; email+Freshdesk remain the historical corpus.
- **No SID/question form fields.** This server's Ticket King "Ticket Aberto" card has empty fields — players type freely. So Discord tickets carry no player SID (admin link will be blank for them) and the "question" is the player's first message. `fetch` handles this (falls back to first player message; `replay` derives the question from it). Resolving SID by username/email lookup is a separate future task.

### Phase 1 — fetch history (REST GET only; ingests tickets)
```bash
python scripts/backfill_discord_tickets.py fetch --confirm-category 1423320403253657752,1519485091666071712,1519485217927073872,1519485302513733785,1519485373619634326
# add --include-transcript only if you approved a transcript channel in Phase 0
```
Refuses unless `--confirm-category` exactly matches the category set in the audit. Writes raw dumps to `backfill_out/raw/<channel>.json`, ingests `channel='discord', origin='backfill', status='resolved'`, dedupes on `external_id`. Sample the dumps + dashboard feed, then continue.

### Phase 2 — KB audit (verify Freshdesk ingestion landed)
```bash
sqlite3 data/supportbot.db "SELECT status,COUNT(*) FROM kb_articles GROUP BY status;"
sqlite3 data/supportbot.db "SELECT category,COUNT(*) FROM kb_articles GROUP BY category;"
```
Tier 2 only retrieves `status='published'` articles — publish the drafts you trust in the SupportKB tab before replay, or the bot can't use them.

### Phase 3 — replay (persistent suggestions + learnings; pay-once)
```bash
# BACK UP FIRST:
cp data/supportbot.db data/supportbot.db.bak-$(date +%Y%m%d)
python scripts/backfill_discord_tickets.py replay --limit 20            # sample
python scripts/backfill_discord_tickets.py replay --limit 0             # full run
python scripts/backfill_discord_tickets.py replay --limit 0 --source email   # also replay email tickets
```
Writes one immutable `suggestions` row per ticket (skips any that already have one) and `backfill_out/replay_learnings.md`. Does NOT touch `messages`/`metrics_daily`/`answer_cache`/statuses.

**IMPORTANT ordering:** publish KB drafts (Phase 2) BEFORE replay, or every suggestion is tier-3 (no published KB to retrieve). If you replayed too early, re-evaluate just the gaps after publishing — creates new rows via `supersedes_id`, originals kept:
```bash
python scripts/backfill_discord_tickets.py replay --tier3-only --limit 0   # redo tickets whose latest suggestion is tier 3
```
Learnings report counts only the latest suggestion per ticket, so superseded rows don't distort the tier distribution.

### Phase 4 — review in the dashboard  ✅ BUILT (2026-07-06)
Backend endpoints live in this service. The UI is now built in `play-review-responder/play_reviewer.py`:
- New page **`/ticket-review`** (nav link "Ticket Review") — 3 source tabs (All/Discord/Freshdesk/Email with counts), tier + status filters, a grid, and a click-to-expand detail panel showing the player question, the actual staff reply, the immutable bot suggestion, an editable `edited_answer`, Approve/Reject, status chip, and the SID→`admin.brx.indusgame.com/player/<SID>` link.
- Proxy routes: `/api/support/suggestions`, `/api/support/suggestions/summary`, `PATCH /api/support/suggestions/<id>` (edited_answer only), `.../approve`, `.../reject`. `@require_login`; Approve does NOT send (Phase 6).
- Requires `SUPPORTBOT_API_URL` + `SUPPORTBOT_API_KEY` set on the play-reviewer service, pointing at the SupportBot service whose DB holds this data. **Note:** the suggestions live in the *local* `data/supportbot.db` — the deployed play-reviewer will only show them once that DB is on the SupportBot Railway volume (or you run both services locally against it).

### Phase 5 — enrich KB from tickets
```bash
cp data/supportbot.db data/supportbot.db.bak-$(date +%Y%m%d)   # backup
python scripts/build_kb_from_tickets.py --limit 20     # sample clusters
python scripts/build_kb_from_tickets.py --limit 0      # all
```
Creates `status='draft'` articles from ticket Q/A (old closed tickets + approved suggestions), idempotent by source id. Review/publish in SupportKB.

### Phase 6 — Go Live via shadow (token, gateway, approve-to-send)
Not yet built (deliberately — it's the only path that writes to Discord and is gated behind everything above). Build after Phases 0–5 have a track record. Requires: the `bot.py` shadow branch to also insert a live `suggestions` row, a guarded `POST /suggestions/{id}/send`, the Settings card, and the token-restore checklist in the spec §5 Phase 6.

---

## C.5 Sync the local DB to the primebot Railway volume

The tickets/suggestions/KB live in the LOCAL `data/supportbot.db`. Railway's primebot
has its own volume DB (`/data/supportbot.db` on volume `web-volume`) — it stays empty
until you upload. `/api/dashboard/suggestions/summary` returning `{"by_source":[],"by_tier":[]}`
means "wired correctly, no data yet" — this is the fix.

> ⚠️ **DB volume runs in WAL mode — a bare upload corrupts it.** Uploading `supportbot.db`
> alone leaves the volume's old `-wal`/`-shm` sidecar files in place; on restart SQLite
> replays that stale WAL onto the new image and you get
> `sqlite3.DatabaseError: database disk image is malformed` (seen live 2026-07-06 —
> `/api/dashboard/suggestions` 500'd while smaller reads still worked). ALWAYS upload a
> `VACUUM INTO` copy (which is WAL-free) AND clear the volume's `-wal`/`-shm`. Follow the
> steps below exactly.

```bash
cd /Users/roby1/Documents/Claude/Projects/PrimeRush-Bot

# 0. Make a clean, WAL-free, integrity-checked copy of the LOCAL db.
#    rm first — VACUUM INTO refuses to overwrite an existing file (silent skip = you
#    upload a stale copy).
rm -f data/supportbot_clean.db
sqlite3 data/supportbot.db "PRAGMA integrity_check;"                  # must print: ok
sqlite3 data/supportbot.db "PRAGMA wal_checkpoint(TRUNCATE);"
sqlite3 data/supportbot.db "VACUUM INTO 'data/supportbot_clean.db';"
sqlite3 data/supportbot_clean.db "PRAGMA integrity_check;"           # must print: ok
# sanity — confirm the copy has what you expect before uploading, e.g.:
sqlite3 data/supportbot_clean.db "SELECT count(*) FROM conversations WHERE player_id!='';"

# 1. BACK UP Railway's current DB first (your undo).
railway link            # select the SupportBot service (project supportbot-service / service web)
railway volume files download web-volume /data/supportbot.db ./railway-supportbot-backup.db

# 2. Upload the CLEAN copy over the volume DB, THEN wipe the stale WAL/SHM sidecars.
railway volume files upload data/supportbot_clean.db /data/supportbot.db --overwrite
printf '' > /tmp/empty
railway volume files upload /tmp/empty /data/supportbot.db-wal --overwrite
railway volume files upload /tmp/empty /data/supportbot.db-shm --overwrite

# 3. Restart primebot so it reopens the clean DB (dashboard "Restart", or)
railway redeploy

# 4. Verify (should show real counts, not empty arrays, and NOT 500)
curl -s -H "Authorization: Bearer $SUPPORT_SERVICE_API_KEY" \
  https://primebot.up.railway.app/api/dashboard/suggestions/summary
curl -s -o /dev/null -w "suggestions: %{http_code}\n" \
  -H "Authorization: Bearer $SUPPORT_SERVICE_API_KEY" \
  "https://primebot.up.railway.app/api/dashboard/suggestions?limit=1"   # want 200, not 500
```
Notes:
- Step 2 REPLACES the Railway DB entirely — step 1's backup is your undo. If the volume
  already held rows you care about (e.g. live shadow-test rows), merge instead of overwrite.
- Build the `VACUUM INTO` copy on your own machine, not inside the Claude sandbox — sqlite
  errors with "disk I/O error" over the Cowork mount.
- The `ticket_translations`/enrichment columns can't regenerate on Railway (the CSV +
  `backfill_out/raw/` inputs are gitignored), so this upload is the ONLY way To/From/Date/SID
  data and cached translations reach live — a code-only deploy leaves them blank.

## D. Remaining build items (not done here)

- **Phase 6** go-live send path + Settings card (the only Discord-write path; admin-gated, token restore checklist).
- **Phase 7** tone-learning loop (`app/llm.py` style-block injection from the suggestions corpus).
- **Freshdesk/Discord SID resolution** (optional): most email/Discord tickets have no SID, so the admin link is blank for them. Resolving SID from email/username via a player lookup is a future task.
- **Phase 4 UI is DONE** (see §C above): `/ticket-review` page + proxy routes in play-review-responder.

---

## E. Commit (you push — sandbox can't)

```bash
cd /Users/roby1/Documents/Claude/Projects/PrimeRush-Bot
git status                    # check for stale lock/staged index first
git add app/db.py app/router.py app/dashboard_api.py \
        scripts/classify_support_emails.py scripts/load_email_tickets.py \
        scripts/load_freshdesk_tickets.py scripts/backfill_discord_tickets.py \
        scripts/build_kb_from_tickets.py BACKFILL_RUNBOOK.md
git commit -m "Unified ticket store: email+freshdesk import, classifier, suggestions schema/API, backfill fetch/replay, KB-from-tickets"
git push
```
`support_emails/`, `support_emails_excluded/`, `*.csv`, and `data/supportbot.db` — decide per your `.gitignore` whether the corpus/DB belong in git or ship via the Railway volume (the DB is large; the spec uses `railway volume files` for it).
