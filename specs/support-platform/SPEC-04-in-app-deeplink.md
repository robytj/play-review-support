# SPEC-04 — In-app Support button → deeplink with context → problem identification

*Phase P3. Depends on SPEC-02/03; needs game-client work (coordinate with W) and the SuperX
JWT scheme. Model: Supercell's in-game "Help & Support" → web, but landing directly in an
identified chat that already knows who you are and roughly why you came.*

## 1. Deeplink contract

The in-app Support button opens:

```
https://support.primerush.gg/ingame?st=<sessionToken JWT>&ctx=<base64url JSON>&sig=<hmac>
```

- `st` — the same short-lived session JWT SuperX consumes on `/ingame?sessionToken=…`.
  Verification: same signing scheme/keys as SuperX (**[TODO: confirm with W — algorithm,
  key rotation, TTL]**). Carries the SID. Expired token → site falls back to SID-entry
  screen (SPEC-02 §4.2) pre-filled with the `ctx` SID if present.
- `ctx` — client context payload, HMAC-signed alongside the token:

```json
{
  "sid": "ABC123",
  "app_version": "2.14.1",
  "platform": "android",
  "os_version": "13",
  "device": "Redmi Note 12",
  "locale": "pt-BR",
  "entry": "settings | shop | battle_end | crash_banner | purchase_fail",
  "error_code": "IAP_TIMEOUT_408",        // optional, when entry is an error surface
  "order_id": "gpa.1234-5678",            // optional, purchase flows
  "net": "wifi | cellular",
  "guest": false
}
```

- Server stores the whole payload in a new `chat_context` table keyed to the
  `web_sessions` row and `conversations.id`; nothing from `ctx` is trusted for account
  actions (display + routing only) — SID authority comes from the verified JWT.

## 2. Problem identification (what "the agent uses the deeplink" means)

On chat open, before the player types:

1. **Deterministic triage from `entry` + `error_code`** (a routing table in config, not an
   LLM): e.g. `purchase_fail` → payments category, greet with "Looks like a purchase didn't
   go through on <device>. Want help with that?" with Yes/No chips. `crash_banner` → known
   crash KB for that `app_version` if one exists.
2. **Version-aware KB**: retrieval filter boost for articles tagged with the current
   `app_version`/platform (add optional `tags` use in KB — tags field already exists).
3. **Locale**: greet and answer in `locale` language using the existing translation layer
   (KB translations for pt/es/ar; Tier-2 generation prompted to reply in the player's
   language — this is roadmap Stage 5, scoped here to chat).
4. The identified context renders as a small "we know" card (device, version, SID) with an
   "edit" link — transparency, and staff see the same card in Ticket Review detail.

## 3. Ticket logging (persistence)

Same mechanism as SPEC-02 §5 — chats **are** conversations. Additions:

- `conversations` gains `entry_point` and `app_version` (denormalized from `chat_context`)
  so Ticket Review can filter "all purchase_fail tickets on 2.14.1".
- Dashboard detail view shows the context card + `admin.brx.indusgame.com/player/<SID>`
  link (already wired via `admin_url`).
- Analytics event to Amplitude on chat open/resolve/escalate (`support_chat_*`) so support
  volume can be joined against the game's behavioral data (SuperPlatform/Amplitude already
  in place on the game side — coordinate event schema with W).

## 4. Game-client work (small, coordinate with W)

- Support button in Settings (and on purchase-failure / crash surfaces) → open URL with
  fresh `st` + `ctx`. Reuse the exact token-minting path the SuperX webstore button uses.
- Fallback if no browser/webview: show SID + `support.primerush.gg` QR/text.
- Optional later (SPEC-03 Phase B): embed the ONNX intent micro-model to set `entry`
  more precisely.

## 5. Acceptance criteria

1. Deeplink with valid `st` lands in an identified chat (SID chip visible) with a
   context-aware greeting; invalid/expired token degrades to SID entry, never an error page.
2. `ctx` persists to `chat_context`; Ticket Review shows the context card.
3. `purchase_fail` and `crash_banner` entries route to the right category with the triage
   greeting (test fixtures for the routing table).
4. Tickets filterable by `entry_point` and `app_version` in the dashboard.

## 6. Agent execution notes

- New: `app/deeplink.py` (JWT + HMAC verification, ctx parsing), `chat_context` table,
  triage routing table in `config.yaml` (`deeplink_triage:`), dashboard filter additions.
- Blocked inputs: JWT scheme + keys (W), list of client surfaces that get the button
  (John), error-code vocabulary (client team).
- Security: rate-limit `/ingame`; HMAC over `st+ctx`; reject `ctx` > 2 KB; log signature
  failures.
