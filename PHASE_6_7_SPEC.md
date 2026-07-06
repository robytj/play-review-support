# Phase 6 & Phase 7 — implementation spec (FOR REVIEW)

**Status: SPEC ONLY — do not build until John approves each phase gate.**
Expands `SHADOW_BACKFILL_SPEC.md` §Phase 6/7 into a review-ready plan. Inherits all six
hard constraints from that spec (REST-only until Phase 6; `DISCORD_BOT_TOKEN` unset on
Railway until John restores it; nothing sent without per-message human approval; no
auto-reply; suggestions immutable). Adds the SID-first gate from `SID_FIRST_INTAKE.md` (§4B).

---

## Phase 6 — Go live via shadow: manual approve-to-send, one ticket at a time

### Goal
Let the bot **read live Discord tickets** (gateway on, `shadow_mode` ON) so they appear in
the Ticket Review grid, and let an admin **send an individually approved reply** from the
dashboard. Exactly one Discord-write path in the whole system, behind two explicit clicks.

### Non-goals (explicit)
Auto-reply (`shadow_mode: false`), sending on backfill/email/freshdesk rows, bulk send,
and any action buttons (restore purchase, etc.). All out of scope.

### Preconditions / gates
1. Constraints 1–6 hold. Token stays unset on Railway until the checklist below.
2. **SID-first gate (§4B):** a live suggestion is only sendable when its conversation has a
   resolved `player_id` (SID). No SID → the bot/agent must ask for it first; Send is disabled.
3. All Phase-4 review UI + proxy routes deployed (done).

### Data model
No new tables. Reuse `suggestions` (already has `sent_at`, `discord_message_id`,
`status`, `supersedes_id`). Add one idempotency guard column if not present:

```sql
-- send attempts are logged in suggestion_actions (action_type='send'); the unique
-- guard below makes a double-click / retry a no-op rather than a double-post.
CREATE UNIQUE INDEX IF NOT EXISTS uq_send_once
  ON suggestion_actions(suggestion_id) WHERE action_type = 'send' AND status = 'done';
```

### Live-shadow ingestion (bot side)
- `discord_bot/bot.py` shadow branch: on each **live** ticket, run the router
  (`router.suggest()`), insert a `suggestions` row (`source='discord'`, conversation
  `origin='live'`, `staff_answer` NULL, `status='pending'`), and **resolve the SID at
  ingest** (§4B): validate a player-supplied SID against `account.shortId`, else resolve
  `email.id → shortId`, else leave blank and post the SID-ask. Persist to
  `conversations.player_id`. Direct/indexed Mongo queries only.
- Live tickets then appear in the same `/ticket-review` grid as backfill, tagged `origin=live`.

### The send endpoint (the only Discord write)
`POST /api/dashboard/suggestions/{id}/send` — guards, ALL must pass or 4xx:
1. `shadow_mode` is ON (refuse if false — that would be auto-reply territory).
2. Row `status == 'approved'`.
3. Conversation `origin == 'live'` AND `channel == 'discord'`.
4. Conversation has a non-empty `player_id` (SID-first gate).
5. Target channel/thread still exists (Ticket King deletes closed ones).
6. Not already sent (idempotency index above).

On success: post `COALESCE(edited_answer, suggested_answer)` via REST
`POST /channels/{external_id}/messages`; set `status='sent'`, `sent_at`,
`discord_message_id`; log a `messages` row (`role='bot'`) + a `suggestion_actions`
row (`action_type='send'`, `status='done'`). Rate-limit: refuse a second send to the
same channel within N seconds; respect Discord 429 with backoff.

### Frontend (play-review-responder, admin-gated)
- Proxy route `POST /api/support/suggestions/<id>/send` (mirror the existing
  approve/reject proxies, but `@require_admin`, not `@require_login`).
- Ticket Review detail: a **Send** button that appears only when `origin=='live'`,
  `status=='approved'`, and `player_id` is set; disabled with a tooltip otherwise
  ("needs a SID before sending" / "approve first"). Confirm dialog shows the exact text +
  target channel. After send, chip flips to `sent` and the button disappears.
- "Go Live via shadow" settings card: bot connection status, `shadow_mode` state (stays
  ON, untouched), and the checklist below rendered read-only.

### Go-live checklist (John performs, in order)
1. All Phase-6 code pushed and confirmed deployed (Railway deployments green).
2. `shadow_mode: true` confirmed in the Support tab.
3. Quiet window (NOT during a watch-party / event traffic spike).
4. Restore `DISCORD_BOT_TOKEN` on Railway; watch logs for category-scoping,
   escalation-gating, gateway connect.
5. **One-on-one test:** John opens a test ticket via Ticket King → sees it in Ticket
   Review → provides a SID → edits/approves → Send → verifies exactly one message in
   exactly that channel. Repeat with a sensitive-keyword ticket (expect tier-3, no send
   until approved) and a no-SID ticket (expect Send disabled).
6. Only then let it watch real tickets — still approve-to-send only.
7. **Rollback:** unset `DISCORD_BOT_TOKEN` (proven kill-switch); web service stays up.

### Acceptance criteria
Live tickets flow into the grid with SIDs resolved at ingest; a send happens only for an
approved, live, discord, SID-bearing suggestion; double-click can't double-post; kill-switch
documented; no auto-reply path enabled anywhere.

### Open questions for John
- Rate-limit window N and any per-day send cap for the first live week?
- Should Send require a second admin's approval for sensitive-keyword tickets?
- If a player has no SID and won't provide one, is escalate-to-human the only path (assumed yes)?

---

## Phase 7 — Tone-learning loop (replicate the support voice)

### Goal
Make Tier-2 RAG answers sound like PrimeRush support actually talks, by feeding the
`suggestions` corpus (generated-vs-edited-vs-sent) back into the prompt. No fine-tuning.

### Corpus sources (no new tables)
- **Correction pairs (strongest):** `edited_answer IS NOT NULL AND edited_answer != suggested_answer`
  → "draft → how we actually say it".
- **Historical voice:** backfill `staff_answer` (real human replies, incl. PT/ES habits,
  greetings, sign-offs).
- **Blessed outputs:** `status IN ('approved','sent')` final texts.

### Application (`app/llm.py answer_with_rag()`)
- Prepend a **style block** to the prompt: the N most recent correction pairs rendered as
  examples + M representative staff answers. Keep it in the cached system region so
  Anthropic prompt-caching absorbs it (cost-neutral across calls).
- **Selection is precomputed, not per-call:** a builder picks N+M examples (recency +
  light dedupe/length filter), renders the block, and stores it (e.g. a `tone_examples`
  cache row or a small JSON on disk). `answer_with_rag()` just reads the cached block.
- **Token budget cap** (~1–2k tokens); truncate oldest first. Inline comment on selection.
- Optional later: per-source tone (Discord casual vs email formal) — out of scope for v1.

### Refresh mechanism
Dashboard button "Refresh tone examples" (admin) → rebuilds the cached style block from the
current corpus. No automatic per-call table scans.

### Measurement
Re-run replay on a small `--limit` (new rows via `supersedes_id`, originals kept per
constraint 6); compare pre/post suggestion similarity to `staff_answer`; short before/after
report. John eyeballs whether the voice got closer.

### Acceptance criteria
RAG answers demonstrably borrow the support voice; the corpus keeps growing from Phase 4–6
usage with zero extra work; no per-call full-table queries; token budget respected.

### Open questions for John
- N and M starting values (default proposal: N=8 correction pairs, M=6 staff answers)?
- Language handling: mirror the player's language in the style block, or always English draft?
- Refresh cadence — manual button only, or also nightly?

---

## Suggested build order
1. Phase 7 first (lower risk, no Discord writes, improves suggestions immediately) — **optional reorder, John's call.**
2. Phase 6 behind the full checklist once the SID-first ingestion + gate are in place.
