# SPEC-01 — SID request + "find your SID" helper on every support surface

*Phase P0. Extends `SID_FIRST_INTAKE.md`. Depends on: Mongo env vars set on Railway
(`MONGO_URI`, `MONGO_ACCOUNT_COLLECTION`, `MONGO_EMAIL_FIELD`, `MONGO_SID_FIELD`).*

## 1. Problem

Only ~7% of historical email tickets auto-resolve a SID; Discord tickets have no email at
all. Every downstream capability (deeplinks, personalization, offers, admin lookups,
approve-to-send) needs `conversations.player_id`. The fix is at intake: ask every player for
their SID or registered email, on every surface, with a visual helper showing where to find it.

## 2. The "find your SID" helper (shared asset)

Build once, reuse everywhere.

- **Content**: 2–3 step instruction with screenshots: open Prime Rush → Settings (gear) →
  Profile/Account → the SID is shown under the player name → tap to copy.
  **[TODO John: confirm exact in-game path + provide 2 screenshots (logged-in and guest);
  guests also have a SID visible there — confirm.]**
- **Formats produced**:
  - KB article `how-to-find-your-sid` (published, translated pt/es/ar via existing
    `kb_translations` flow) — canonical URL `support.primerush.gg/kb/how-to-find-your-sid`.
  - A compact HTML partial (image + 3 bullets) for embedding in the web widget (SPEC-02).
  - A plain-text version for email auto-reply and Freshdesk.
  - A Discord embed version (image attachment + text).
- **SID format validation**: single regex constant shared across surfaces
  (`app/sid_lookup.py::SID_PATTERN`). **[TODO John: confirm shortId format — length,
  alphanumeric?]** Client-side validation is cosmetic only; server always re-validates
  against Mongo.

## 3. Per-surface changes

### 3.1 Discord (Ticket King form)
Already asks "Qual é o ID da sua conta?" — keep. Changes:
- Add the helper image + one line ("Não sabe seu ID? Veja aqui: <link>") to the ticket
  form message. Localize per server language.
- `_parse_ticket_king_card()` in `discord_bot/bot.py` already extracts the claimed SID; on
  live ingestion call `resolve_sid(email=None, claimed_sid=...)` and persist `player_id`.
- If SID invalid/missing → bot's first (approved) reply template asks for it, embedding the
  helper. Ticket is not blocked — it lands as Tier 3 with `player_id NULL`.

### 3.2 Email auto-reply
- New: auto-acknowledgement on inbound support email (Gmail filter → autoresponder, or via
  the ingestion job) containing: ticket received + "Reply with your Player SID (Settings →
  Profile) or the email registered on your account" + plain-text helper.
- Ingestion (`scripts/load_email_tickets.py` + live path): run `resolve_sid(email=sender)`;
  additionally regex-scan body for `SID_PATTERN` and validate. First valid wins; store which
  method resolved it in `conversations.sid_source` (`claimed|email_match|scan`) — new column.

### 3.3 Freshdesk
- Add a required custom field **Player SID** to the Freshdesk ticket form, with the helper
  link in the field description. **[Manual admin task — document in runbook.]**
- `scripts/load_freshdesk_tickets.py` and live sync: read the custom field first, then
  existing regex fallback; validate via `resolve_sid`.

### 3.4 Web chat widget (SPEC-02)
- Identify step before chat: logged-in via deeplink → SID known; guest → one screen asking
  SID or registered email, with inline helper partial and a prominent **"Continue without
  SID"** link (never hard-block; unresolved chats can still answer informational questions
  but show a persistent "add your SID to unlock account help" chip).

## 4. Backend changes

- `conversations.sid_source TEXT NULL` (migration; values: `claimed`, `email_match`,
  `scan`, `deeplink`, `manual`).
- `resolve_sid()` unchanged in behavior; add a counter metric per source for the dashboard.
- Dashboard: Ticket Review already shows SID; add a "SID coverage" number to
  `/api/dashboard/metrics` (`% of conversations in window with player_id`).

## 5. Acceptance criteria

1. All four surfaces ask for SID with the helper visible; pt/es translations live.
2. New Discord/email/Freshdesk/web tickets carry `player_id` when the player supplied a
   valid SID or matching email; `sid_source` recorded.
3. SID coverage metric visible in Support Settings; baseline captured pre-launch.
4. No surface hard-blocks ticket creation on missing SID.

## 6. Agent execution notes

- Touch: `app/sid_lookup.py`, `app/db.py` (migration), `discord_bot/bot.py`,
  `scripts/load_email_tickets.py`, `scripts/load_freshdesk_tickets.py`,
  `app/dashboard_api.py` (metrics), new KB article via existing KB flow.
- Do not rename existing env vars (hard constraint from `SHADOW_BACKFILL_SPEC.md`).
- Screenshots are a blocking input from John; everything else can ship with a placeholder
  image and text-only helper.
