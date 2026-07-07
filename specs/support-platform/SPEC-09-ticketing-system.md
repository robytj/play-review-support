# SPEC-09 — Ticket Review as a full ticketing system

*Requested 2026-07-08. Upgrades Ticket Review from a suggestion-review grid into the
team's ticketing system: assignees, priorities, SLA, status workflow, action audit log,
KB-driven recommendations, and (wired but inert) player outreach via in-game inbox.
Chat escalations (`source='chat'`) are first-class citizens; all sources get the same
treatment. Storage + API live in SupportBot; UI in the Ops Dashboard.*

## 1. Data model (SupportBot SQLite, idempotent migrations)

`conversations` gains:

| Column | Values / meaning |
|---|---|
| `priority` | `P1` (urgent) `P2` (high) `P3` (normal, default) `P4` (low) |
| `assignee` | staff email (matches the dashboard's Google login), NULL = unassigned |
| `due_at` | SLA deadline, computed from priority (see §3) |
| `first_human_response_at` | set the first time staff sends/approves a reply or posts a note with `notify` |
| `closed_at` | set on `closed` |

New table `ticket_events` — the audit log (mirrors the game admin's remarks+audit model):

```
ticket_events(id, conversation_id, actor TEXT,      -- staff email or 'system'/'bot'
              event TEXT,                            -- created|status|priority|assignee|
                                                     -- note|escalated|reply_sent|
                                                     -- outreach_inbox|sla_breach
              detail_json TEXT, created_at)
```

Every mutation writes an event. The chat engine's escalation writes `created` +
`escalated` events with the chat context. Notes are events (`event='note'`).

## 2. Status workflow

`open → in_progress → waiting_player → resolved → closed` (+ existing values map:
`escalated`→`open` with an `escalated` event; `paused`→`waiting_player`). Transitions
are unrestricted (small team) but every change is logged with actor. `resolved` by
bot (chat CSAT yes) is allowed; `closed` is staff-only.

## 3. Priorities & SLA

- Defaults on creation: payments/refund or ban categories → `P2`; chat escalations
  inherit `P2` if purchase/ban context present else `P3`; everything else `P3`.
  Staff can override any time (logged).
- SLA policy in `config.yaml` (`sla:` block, hours to first human response):
  `P1: 4, P2: 12, P3: 24, P4: 72`. `due_at = created_at + sla[priority]`; recomputed
  on priority change **only if** no `first_human_response_at` yet.
- **Overdue** = `now > due_at` and `first_human_response_at IS NULL` and status not
  in (resolved, closed). A lazy sweep (on list queries) writes one `sla_breach`
  event per ticket. Queue ordering: overdue first, then priority, then due_at.

## 4. Recommendations (deterministic, $0)

`GET /api/dashboard/conversations/{id}/recommendations` returns:

1. **KB matches**: top-3 published articles by embedding similarity to the ticket's
   question (existing fastembed + sqlite-vec; skip when embeddings unavailable).
2. **Suggested actions** — rule table keyed on category/context (from
   `PLAYER_DATA_MAP.md` §5, phrased as staff to-dos with deep links):
   - payments → "Verify transactions for `<SID>` (admin → player → Purchases);
     completed-only — if charged-but-missing, restore via grant/giftables."
   - ban/appeal → "Read ban remarks in the player's audit log (admin) before
     replying; check report count + device-ban overlap in the ticket context."
   - missing item → "Check `owned[]` and `timeLimitedItems` expiry in admin."
   - guest/account loss → "Confirm linked socials; unlinked guests can't be
     recovered — see playbook article."
   - unresolved SID → "Ask for SID (helper text available) or run email match."
3. **Playbook link**: the highest-similarity `playbook`-tagged article, surfaced
   separately ("suggested reply basis").

## 5. Player outreach (wired, inert by default)

New `app/outreach.py`:

- `send_inbox_message(sid, title, body, actor)` → IndusAPI (the admin panel's
  Communication → Inbox System). Requires env `INDUS_API_URL`, `INDUS_API_TOKEN`,
  `INDUS_TENANT_ID` (all unset today) **and** runtime toggle `outreach_enabled`
  (Support Settings, default OFF). Until then the function returns a clear
  "not configured" result; the UI button shows disabled with the reason.
- Every attempt (even refused) logs an `outreach_inbox` event with actor + payload
  summary (never full body in detail_json — title + first 80 chars).
- Push notifications: **no push endpoint exists in the admin UI source** — listed as
  a TODO to confirm with W (likely a different service). The UI reserves a disabled
  "Push" button with tooltip "pending game-server API".
- Exact IndusAPI endpoint/payload for inbox send: **[TODO John/W: confirm from
  IndusAPI — the admin UI uses the Communication module; per-player read is
  `GET /{id}/inbox-message`]**. `outreach.py` isolates this behind one function so
  confirming the contract is a one-file change.

## 6. API additions (all Bearer service-key)

| Route | Purpose |
|---|---|
| `GET /api/dashboard/tickets?status&priority&assignee&channel&overdue&q&limit&offset` | rich list; returns SLA state per row |
| `PATCH /api/dashboard/conversations/{id}` | `{status?, priority?, assignee?}` — logs events; sets closed_at/due_at rules |
| `POST /api/dashboard/conversations/{id}/notes` | `{text}` → note event |
| `GET /api/dashboard/conversations/{id}/events` | audit timeline |
| `GET /api/dashboard/conversations/{id}/recommendations` | §4 |
| `POST /api/dashboard/conversations/{id}/outreach/inbox` | §5 (403 until enabled) |

Staff identity: the responder proxy adds `X-Staff-Email: <google login>` to every
proxied ticketing call; SupportBot records it as `actor`. First staff reply via the
existing approve/send path also stamps `first_human_response_at` + `reply_sent` event.

## 7. Dashboard UI (play-review-responder)

Ticket Review upgrades:
- **Grid**: new columns — priority pill (P1 red/P2 amber/P3 default/P4 muted),
  assignee (initials chip), status, SLA cell (countdown "due 3h" / red "OVERDUE 2h");
  filter bar gains status/priority/assignee/overdue; default sort = queue order (§3).
- **Detail drawer** additions: status/priority/assignee selectors (assignee options =
  dashboard user list the responder already has), notes composer, event timeline
  (actor + event + relative time), recommendations panel (§4) with tappable admin
  deep links, outreach buttons (§5, disabled states honest about why).
- Chat-source tickets show the chat context card + link to the full shadow transcript.

## 8. Acceptance

1. Migrations idempotent against a copy of the real DB; existing rows readable
   (NULL priority renders P3, no events backfilled).
2. Every mutation produces exactly one `ticket_events` row with correct actor.
3. Overdue computation correct across priority changes and first-response stamping.
4. Recommendations return KB matches + correct rule actions for payments/ban/item
   fixtures; degrade cleanly without embeddings.
5. Outreach refuses without env/toggle, logs the refusal, UI reflects it.
6. Full pytest suite green; responder py_compiles; no change to suggestion
   immutability or shadow/tone guards.
