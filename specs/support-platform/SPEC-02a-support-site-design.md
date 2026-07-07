# SPEC-02a — support.primerush.gg: Design & Build Brief (for Claude Design)

*Companion to `SPEC-02-support-site.md` (functionality, backend, routes) — this document
covers everything visual and interactive. Deliverable: production front-end, not mockups.*

---

## 1. What you are building

The player-facing support site for **Prime Rush**, SuperGaming's mobile battle-royale /
extraction shooter (lineage: Indus → Prime Rush). Model: `support.supercell.com`'s
browse-first calm, plus a chat entry Supercell doesn't have. Three layers: **Browse KB →
Chat with the support agent → Ticket**. Most players arrive from inside the game on a
low-end Android phone, often frustrated, often in Portuguese or Spanish. The site's job is
to feel like the game's world — premium, dark, confident — while being faster and simpler
than any game UI: one column, one action per screen, nothing decorative that costs bytes.

### Deliverables

1. **Jinja2 templates** under `templates/web/` (base + one per page, §5) with template
   variables/blocks named per SPEC-02 routes. Plain semantic HTML — no React/build step.
2. **One CSS file** `static/web/support.css` built entirely on the token set in §2
   (CSS custom properties). Target < 30 KB uncompressed.
3. **One JS file** `static/web/chat.js` for the chat screen only (§7). Vanilla ES6,
   < 40 KB uncompressed, no dependencies. All other pages must work with JS disabled.
4. **Asset set**: favicon, logo lockup, "find your SID" helper illustration placeholder,
   empty/error state illustrations (simple line-art in brand style, SVG).
5. A `DESIGN-NOTES.md` recording any decisions taken where this brief was silent.

---

## 2. Brand foundation (non-negotiable)

Source of truth: `SuperXWebstore/SuperX-Marketplace-Design-Package/brand/source/supergaming-site.css`
and `01-design-brief.md`. Reuse the tokens verbatim:

| Token | Value | Use |
|---|---|---|
| `--black` | `#0A0A0A` | Page background |
| `--surface` | `#141414` | Cards, panels, chat bubbles (bot) |
| `--surface-2` | `#1B1B1B` | Raised panels, sticky elements |
| `--white` | `#FFFFFF` | Primary text, the only accent |
| `--muted` | `#9B9B9B` | Secondary text |
| `--muted-2` | `#6E6E6E` | Eyebrows, tertiary |
| `--hairline` | `#2A2A2A` | All borders/dividers (1px) |
| `--hairline-soft` | `#1F1F1F` | Soft dividers |
| `--good` | `#3ddc84` | Resolved/success states only |
| `--bad` | `#ff5b6b` | Errors only |
| `--warn` | `#f5c518` | Pending/waiting states only |

**Rules** (from the SuperGaming design principles — repeat them in code comments):

1. **Monochrome chrome.** The accent color is white. Emphasis comes from weight, scale,
   and hairline rules — never from added color. No gold UI accents, ever.
2. **Zero border-radius.** Everything is square. No shadows; hairline borders carry depth.
3. **Dark only.** No light theme.
4. **Status colors are functional, not decorative** — ticket status, success/error toasts,
   nothing else.
5. **Buttons**: transparent bg, 1px white border, white Space Mono uppercase label; hover =
   inverted (white bg, black text); disabled = 35% opacity. Easing
   `cubic-bezier(.22,.61,.36,1)`, 150–200ms.
6. Sticky header may use `backdrop-filter: blur(14px)` over `rgba(10,10,10,.72)` — the only
   glass allowed.

### Typography

Google Fonts: `Archivo` (display), `Inter` (body), `Space Mono` (labels/mono).
Load with `display=swap`, preconnect, and subset to latin+latin-ext.

- **Display / H1**: Archivo 900, font-stretch 125%, uppercase, letter-spacing −.02em,
  line-height .9. Sizes: clamp(28px, 7vw, 48px) — support pages are more modest than the
  store's hero scale.
- **H2 / section**: Archivo 800, stretch 112%, clamp(20px, 4.5vw, 28px).
- **Eyebrow**: Space Mono 11–12px, .22em tracking, uppercase, `--muted-2`.
- **Body**: Inter 16px (17px ≥ 768px), line-height 1.55.
- **Chat text**: Inter 15px, line-height 1.5 (density matters in chat).
- **SID / codes / numbers**: always Space Mono (SIDs, ticket ids `PR-7F3K2`, coupon codes,
  timestamps).

### Logo

SuperGaming hexagon badge (`brand/favicon.svg`: white-stroke polygon + "SG") — never
recolored or stretched, clear space respected. Header lockup: hexagon + wordmark
**PRIME RUSH SUPPORT** — "PRIME RUSH" Archivo 900, "SUPPORT" Space Mono eyebrow beneath or
beside. **[Placeholder: a Prime Rush game logo may replace the hexagon later — build the
lockup as a swappable partial `_logo.html`.]**

---

## 3. Layout system

- Single column, max-width **720px** for content pages (reading width), **480px** for the
  chat column, centered. The store's 1440px editorial canvas is wrong for support — this
  site is a tool.
- Page padding `clamp(16px, 4vw, 32px)`. Vertical rhythm on an 8px scale.
- Touch targets ≥ 44×44px. Interactive rows get full-width tap areas.
- Sticky elements: header (56px) and, on `/chat`, the composer pinned to bottom with
  `env(safe-area-inset-bottom)` padding.
- Breakpoints: one at 768px (spacing/typography step-up). Nothing structural changes —
  desktop is just a comfortable phone.

---

## 4. Shared components

Build as Jinja2 partials/macros in `templates/web/_components.html`:

1. **Header**: logo lockup left; right side = language picker (globe icon + `PT/ES/EN/AR`)
   and identity chip. Identity chip states: *guest* → outlined "ADD SID" chip; *identified*
   → Space Mono SID with a small check glyph; tapping opens the identity sheet (§6).
2. **Search bar**: full-width, hairline box, Space Mono placeholder "SEARCH HELP…",
   magnifier glyph. Submits GET `/search` (works without JS).
3. **Category tile**: full-width row — icon (line-art SVG, 24px, white), category name
   (Inter 600), article count (`--muted`), chevron. 8 categories from the KB: Account &
   Login, Payments & Purchases, Gameplay & Progression, Bans & Fair Play, Technical
   Issues, Updates & Patches, Rewards & Events, General. Hairline separators between rows,
   no card boxes (list > grid on mobile).
4. **Article row**: title (Inter 500) + one-line snippet (`--muted`, truncated), chevron.
5. **CTA banner "Still need help?"**: hairline-boxed strip with "CHAT WITH US" button
   (primary style) + subline "Usually replies instantly". Appears at the bottom of every
   KB page. When `web_chat_enabled=false`, swaps to "Email us" mailto + note.
6. **Helpful vote**: "Was this helpful?" + 👍/👎 as two square outline buttons; on vote,
   swap to "Thanks for the feedback" (and on 👎 also show the chat CTA inline).
7. **Ticket status pill**: Space Mono uppercase — OPEN (`--warn`), ANSWERED (`--good`),
   ESCALATED (`--warn`), RESOLVED (`--good`), CLOSED (`--muted`). Dot + label.
8. **Toast**: bottom-anchored above safe-area, `--surface-2`, hairline border, auto-dismiss.
9. **Footer**: minimal — links (Privacy, Terms, `store.primerush.gg`), language picker
   repeat, © SuperGaming. Space Mono 11px, `--muted-2`.

---

## 5. Pages

### 5.1 `/` — Home
Order, top to bottom: eyebrow ("PRIME RUSH — PLAYER SUPPORT") · H1 "How can we help?" ·
search bar · category list (8 rows) · "Popular articles" (top 5 article rows by views) ·
chat CTA banner · footer. First screenful on a 360×640 viewport must show: header, H1,
search, and ≥ 2 category rows.

### 5.2 `/kb/<category>` — Category
Breadcrumb (Space Mono eyebrow: `HELP / PAYMENTS & PURCHASES`), H2 category name, article
rows, chat CTA banner.

### 5.3 `/kb/article/<slug>` — Article
Breadcrumb · H1 title · body (rendered from KB `symptom` + `answer`; style `h3`, `p`, `ol`,
`ul`, `strong`; images full-bleed within column) · helpful vote · "Related articles" (3
rows) · chat CTA banner. If a cached translation exists for the session language, serve it
with a small "translated · view original" toggle; else English body with a "TRANSLATE"
outline button (POSTs to the translate action, per SPEC-02).

### 5.4 `/search?q=` — Results
Search bar (pre-filled) · result count eyebrow · article rows with match snippet ·
empty state: line-art illustration + "No results for '<q>'" + chat CTA.

### 5.5 `/chat` — Chat (the centerpiece — see §7)

### 5.6 `/ingame` — Deeplink landing
Never shows an error page. Valid token → instant redirect to `/chat` (at most a 300ms
brand flash: hexagon pulse on black). Invalid/expired → identity sheet (§6) pre-filled
with any SID from `ctx`, headline "Confirm your player ID".

### 5.7 `/ticket/<public_id>` — Ticket status
Header · ticket id in Space Mono (`PR-7F3K2`) + status pill · vertical thread timeline:
each message a block with author label (YOU / PRIME RUSH SUPPORT), timestamp (Space Mono,
relative), body; staff replies get a 2px white left rule. Bottom: reply composer if ticket
open, or "This ticket is closed — start a new chat" CTA.

### 5.8 Error/edge templates
`404` (lost-in-the-drop-zone line art, "Back to help" button), `500`, offline banner
(chat.js detects `navigator.onLine`), and the chat-disabled state (§4.5).

---

## 6. Identity sheet (guest → identified)

A bottom sheet (full-screen on mobile) reachable from the header chip, chat, or `/ingame`
fallback:

- Headline "Link your player account" · SID input (Space Mono, centered, auto-uppercase)
  · "or registered email" input · CONTINUE button · **"Continue without SID"** text link
  (always present, `--muted`, never hidden).
- Embedded **"Where's my SID?"** helper: the SPEC-01 partial — illustration placeholder
  (game Settings → Profile screenshot) + 3 numbered steps. Collapsed behind a disclosure
  row on small screens.
- Validation states: inline, `--bad` text under field, never a browser alert. Success:
  sheet closes, header chip updates, toast "Account linked".

---

## 7. Chat UI (`/chat` + `chat.js`)

Layout: header (56px, with ticket-id eyebrow once created) · scrollable transcript ·
pinned composer (input + send). Column max 480px centered.

**Bubbles.** Bot: `--surface`, hairline border, left-aligned, full-square corners; label
row above first bubble in a group: hexagon glyph 16px + "PRIME RUSH SUPPORT" Space Mono
11px + tier-invisible (never show tiers to players). Player: white border on transparent,
right-aligned. Max width 85%. Timestamps: Space Mono 10px `--muted-2`, shown on tap and on
group boundaries. System notes (escalation, resolution) render as centered hairline-ruled
one-liners, not bubbles.

**Composer.** Single-line input growing to 4 lines; send button = square outline with
arrow glyph, inverts when input non-empty; disabled + spinner while awaiting reply.
Character cap 1,000 with quiet counter after 800.

**States & message kinds** (all server-driven; chat.js renders by `type`):

1. `typing` — three-dot pulse in a bot bubble skeleton, min 400ms display.
2. `text` — markdown-lite (bold, lists, links; links underlined white).
3. `chips` — tappable quick replies (clarify-or-answer, Yes/No triage): outline pills,
   Space Mono 12px uppercase, horizontal wrap; disabled after selection, chosen chip
   inverts. Chips also echo as a player bubble.
4. `context_card` — the "we know" card (SPEC-04): compact `--surface-2` panel listing
   device · app version · SID with an EDIT link. Shown once at session start when deeplinked.
5. `sid_prompt` — inline card version of the identity sheet trigger: "Add your SID to
   unlock account help" + LINK ACCOUNT button. Dismissible; if dismissed, a persistent
   small chip stays under the header.
6. `article_ref` — when the bot cites KB: a mini article row inside the bubble (title +
   chevron, opens the article in a new sheet/tab). Fin-style grounding, visible.
7. `escalation_card` — "We've passed this to a human" panel: ticket id (Space Mono, large),
   status pill OPEN, "We'll reply here and at `/ticket/<id>`", optional email capture field
   if session has none.
8. `csat` — session close: "Did this solve it?" 👍/👎 squares; on 👎 offer escalation if
   not already escalated.
9. `offer_card` (SPEC-06, behind toggle) — coupon panel: campaign line, code in Space Mono
   with COPY button, expiry, "REDEEM IN STORE" button (deeplink). Visually calm — same
   monochrome chrome; **no** gold, no confetti.
10. `recognition` (SPEC-05, behind toggle) — plain text bubble; no special styling
    (recognition must read as human warmth, not a reward popup).
11. `unavailable` — budget/kill-switch state: system note "Chat is busy — browse help
    articles or leave a ticket" + both CTAs.

**Behavior.** Optimistic player-bubble render; POST to `/api/web/chat/message`; poll or
SSE per SPEC-02 backend choice (build for fetch-poll at 1.5s with backoff; abstract the
transport in one function). Scroll pinned to bottom unless user scrolled up (then show a
"↓ new reply" chip). Session restore on reload from the server (transcript re-fetch — no
localStorage persistence of message content). Offline: composer disabled + banner.

---

## 8. Language & RTL

- All UI strings in one Jinja i18n dict (`en`, `pt-BR`, `es`, `ar`) — no hardcoded copy in
  templates. English fallback.
- **Arabic = RTL**: `dir="rtl"` on `<html>`, logical CSS properties throughout
  (`margin-inline-start`, not `margin-left`) so the layout mirrors for free. Space Mono
  eyebrows stay LTR (codes/SIDs/ticket ids always LTR with `dir="ltr"` spans).
- Tone of voice (all languages): calm, specific, zero exclamation marks in UI chrome;
  the game's swagger lives in the type, not the copy. Player-facing microcopy examples —
  empty search: "No results. Try the category list, or just ask us." · escalation: "A human
  will take it from here." · resolved: "Glad that's sorted."

---

## 9. Performance & accessibility budgets (acceptance-gating)

- Lighthouse mobile ≥ 90 (Performance & Accessibility) on `/`, an article page, and `/chat`.
- Total transfer for `/` < 150 KB (fonts included, images excluded); JS on non-chat pages: 0.
- Works on Android WebView (the in-game browser) and iOS Safari 15+.
- WCAG 2.1 AA: contrast (the token set passes on `--black`; verify `--muted-2` usage ≥ 18px
  or decorative only), focus-visible outlines (2px white offset), full keyboard path through
  chat (chips are buttons), `aria-live="polite"` on the transcript, labels on all inputs,
  `prefers-reduced-motion` kills the typing pulse and transitions.
- No layout shift from font swap on the H1 (size-adjust fallback metrics for Archivo).

---

## 10. Build & handoff notes

- Templates must consume the SPEC-02 context contracts; where a backend endpoint isn't
  ready, code against a fixture JSON checked into `static/web/fixtures/` and leave a
  `{# TODO(backend) #}` comment — do not invent alternate contracts.
- Every state in §7 gets a demo entry in a hidden gallery page `/dev/components` (staff-only
  flag) — this doubles as the SPEC-07 preview harness surface and the review artifact.
- Ship screenshots (360px + 768px) of every page/state in `DESIGN-NOTES.md` for John's
  review round.

## 11. Acceptance checklist

1. All pages in §5 + components in §4 built as specified, tokens only from §2, zero
   border-radius, no non-status color anywhere in chrome.
2. Chat renders all 11 message kinds from fixtures; transcript accessible; transport
   abstracted in one function.
3. Guest → identified flow works end-to-end with the identity sheet; "Continue without
   SID" never more than one tap away.
4. pt-BR and es fully translated; ar renders RTL correctly with LTR code spans.
5. Budgets in §9 met and evidenced (Lighthouse reports committed alongside screenshots).
6. `/dev/components` gallery complete.
