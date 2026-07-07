# SPEC-02 — support.primerush.gg: mobile-first Helpshift-lite support site

*Phase P1. Depends on SPEC-01. Model: `support.supercell.com` (browse-first KB) + a chat
entry that Supercell doesn't have. Served by the existing SupportBot FastAPI service —
same repo, same Railway deploy, same SQLite DB — so it ships together with the rest.*

## 1. Product shape

Three layers, in order of cost (cheapest first — most sessions should end at layer 1):

1. **Browse**: game-branded KB home — search bar, 8 category tiles (existing
   `kb/categories`), popular articles, per-article "Was this helpful?" (👍/👎).
2. **Chat**: "Still need help? Chat with us" — the PrimeRush support agent (SPEC-03 runtime).
3. **Ticket**: when chat can't resolve (Tier 3 / player asks for a human), the session
   converts to a persistent ticket that lands in the existing Ticket Review queue.

## 2. Architecture

- **Serving**: new FastAPI router `app/web_support.py` mounted at `/` on a second Railway
  domain `support.primerush.gg` (Railway custom domain on the same service). Jinja2 templates
  + one small vanilla-JS chat bundle. No new framework, no Node build step. All pages SSR,
  <50 KB JS, works on low-end Android (bulk of the player base).
- **Public API namespace**: `/api/web/*` — separate from `/api/dashboard/*` (which stays
  Bearer-key internal). `/api/web/*` is session-cookie authenticated (see §4) with per-IP and
  per-session rate limits (slowapi or hand-rolled token bucket in SQLite).
- **Mobile-first**: single-column layout, 44px touch targets, bottom-anchored chat input,
  safe-area insets, dark theme matching game branding; instant load (SSR + cached static).
  Lighthouse mobile ≥ 90 as an acceptance gate.
- **i18n**: reuse `detect_language()` + `kb_translations` (pt/es/ar). Language picker in the
  header; article pages serve the cached translation when available, else English with a
  "translate" action that populates the cache via the existing flow.

## 3. Pages

| Route | Content |
|-------|---------|
| `/` | Search, category tiles, top articles, "Chat with us" CTA, login state chip |
| `/kb/<category>` | Article list for category |
| `/kb/article/<slug>` | Article (title/symptom/answer), helpful vote, related articles (sqlite-vec nearest neighbors), "Still stuck? Chat" CTA |
| `/search?q=` | Embedding search over published KB (fastembed, local, zero API cost) |
| `/chat` | Chat UI (guest or identified) |
| `/ingame` | Deeplink landing (SPEC-04): verifies token, sets session, redirects to `/chat` |
| `/ticket/<public_id>` | Player-facing ticket status view (read-only thread + status) |

## 4. Identity: login and guest

Three levels, all leading to the same chat:

1. **In-app deeplink (primary, ~most traffic)**: `/ingame?sessionToken=<JWT>` — same JWT the
   SuperX webstore consumes. Verify signature server-side (shared public key / secret with
   the game backend — **[TODO John: confirm signing scheme + key exchange with W]**), extract
   SID, create a `web_sessions` row, set an HttpOnly cookie. `sid_source='deeplink'`.
2. **SID + verification (web login)**: player enters SID → we validate against Mongo → for
   account-changing topics later, add OTP-to-registered-email (or SuperX's SID+OTP in-app
   inbox flow when available). For v1, SID entry alone identifies but marks the session
   `verified=false` — enough for personalized-read answers of low sensitivity, never for
   account actions.
3. **Guest**: anonymous `web_sessions` row; chat works for informational tiers only;
   persistent chip prompts to add SID (helper from SPEC-01).

New table `web_sessions(id, sid TEXT NULL, verified BOOL, created_at, last_seen_at,
locale, entry ('deeplink'|'web'|'guest'), ua, ip_hash)`.

## 5. Ticket persistence (chat → ticket)

- Every chat session creates a `conversations` row up front: `origin='live'`,
  `status='open'`, `player_id` = resolved SID or NULL, `sid_source` per SPEC-01. Channel:
  the `source` column lives on `suggestions` (values discord|freshdesk|email) — add `web`
  there, and verify how `/api/dashboard/feed?channel=` derives channel to make Web appear
  as a fourth tab (add `conversations.channel` in a migration if the feed needs it). All player
  and bot messages append to `messages`. Web chats are therefore first-class tickets in the
  existing store — Ticket Review gets a fourth source tab **Web** (dashboard change:
  extend the existing source filter; API already supports arbitrary `source`).
- Every bot answer is also written as a `suggestions` row (`source='web'`, tier,
  immutable `suggested_answer`, `status='sent'` since chat is live) — the same corpus feeds
  tone learning and Tier-1 reuse. Rejected-after-the-fact reviews become training signal.
- Escalation (SPEC-03 Tier 3 or "talk to a human") sets `status='escalated'`, generates a
  short `public_id` (e.g. `PR-7F3K2`), shows it to the player with the `/ticket/<public_id>`
  link, and asks for a contact email if the session has none. Escalations appear in the
  existing dashboard queue (`/api/dashboard/queue`).
- Follow-up: when staff reply from the dashboard (approve-to-send for web = posting the
  reply to the ticket thread), the player sees it on the ticket page; optional email
  notification if an address exists.

## 6. Acceptance criteria

1. `support.primerush.gg` serves KB browse/search/article with pt/es working, from the
   existing service, mobile-first (Lighthouse mobile ≥ 90 on `/` and an article page).
2. Guest chat and deeplink chat both function; sessions and messages persist; Web tab in
   Ticket Review shows them with SID where resolved.
3. Escalation produces a ticket with `public_id`, visible at `/ticket/<public_id>`, present
   in the dashboard queue.
4. `/api/web/*` rate-limited; `/api/dashboard/*` untouched and still key-gated.
5. `web_chat_enabled` toggle in Support Settings gates `/chat` (off → "chat unavailable,
   browse the KB or email us").

## 7. Agent execution notes

- New: `app/web_support.py`, `templates/web/*`, `static/web/*`, `app/web_sessions.py`,
  migrations for `web_sessions` + `conversations.public_id`.
- Reuse: `app/embeddings.py` + `app/vectorstore.py` for search/related; `app/llm.py`
  translation; KB read paths (add public read-only queries — do not expose dashboard
  endpoints).
- Keep the SQLite single-writer discipline: chat writes are small and serialized; enable
  WAL mode if not already (check `BACKFILL_RUNBOOK.md` constraints re: the safe re-sync
  procedure before changing journal modes).
- Branding: reuse the new logo already in the repo; game-style dark palette. No pixel
  designs exist — implement clean and simple, screenshots to John for one review round.
