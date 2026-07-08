# SPEC-10 — Player-visible tickets & resolutions on the SuperX platform

*Requested 2026-07-08. Players see their escalated tickets and resolutions inside the
SuperX webstore account area (store.primerush.gg), reusing SuperX's SID identity.
SupportBot stays the system of record; SuperX renders.*

## 1. Shape

SuperX (Next.js + Supabase) already authenticates players three ways (in-app deeplink
`/ingame?sessionToken=JWT`, SID+OTP, email/password) and knows the SID. A new
**"Support tickets"** section in the SuperX account page lists the player's tickets
from SupportBot and their resolutions. No new login surface, no data duplication.

## 2. API (SupportBot side — new, server-to-server)

New key-gated namespace for platform partners: `/api/partner/*` with its own bearer
key `PARTNER_API_KEY` (never the dashboard key; scope: read-only, SID-bound).

| Route | Returns |
|---|---|
| `GET /api/partner/players/{sid}/tickets?limit&offset` | `[{public_id, created_at, status (player-safe mapping), channel, subject (first 80 chars of question, blob-clipped), resolved_at, has_staff_reply}]` |
| `GET /api/partner/players/{sid}/tickets/{public_id}` | thread: player messages + **approved/sent staff replies only** (never suggestions, never internal notes/events), status timeline (created → in progress → resolved) |

Rules: 404 unless the ticket's `player_id == sid` (no cross-player reads, same
guarantee as chat); statuses map player-safe (`open/in_progress` → "In progress",
`waiting_player` → "Waiting for you", `resolved/closed` → "Resolved"); internal
fields (assignee, priority, SLA, events, suggestions) are **never** serialized.

## 3. SuperX side

- Server route (Next.js API) calls SupportBot with `PARTNER_API_KEY` + the
  session's SID — the key never reaches the browser.
- UI: account page → "Support" card: ticket list (status pill, date, subject),
  detail view with the thread + "Reply" (optional v2: POST reply → appends a player
  message + flips status to open; v1 read-only with a "continue in chat" deeplink to
  support.primerush.gg/chat).
- Notification hook (v2): when a ticket gains a staff reply, SuperX can badge the
  account icon (poll or Supabase edge cron calling the list endpoint).

## 4. Rollout

1. SupportBot: partner API + tests (ship now — same deploy as everything else).
2. SuperX repo: account section (W's side; the API contract above is stable).
3. v2: player replies from SuperX; push/badge notifications; unify with the
   `/ticket/<public_id>` page on support.primerush.gg (same data, two skins).

## 5. Acceptance

SID-bound reads only (cross-SID test), player-safe serialization (no internal
fields in any response, fuzz test over all columns), suggestions/notes never leak,
key separation enforced (dashboard key rejected on partner routes and vice versa).
