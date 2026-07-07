# DESIGN-NOTES.md — support.primerush.gg

Companion to SPEC-02a. Records decisions taken where the brief was silent, plus the
file map and how to wire this into the SPEC-02 Flask/Jinja backend.

## File map

```
templates/web/
  base.html            document shell: fonts, tokens link, size-adjust fallback, skip-link, toast layer
  _logo.html           logo_badge() + logo_lockup() macros — SWAP the <svg> badge when the game logo lands
  _icons.html          icon(name,size,cls) macro — line-art 24px set, stroke=currentColor
  _components.html     §4 shared macros: site_header, lang_picker, identity_chip, search_bar,
                       category_row, article_row, chat_cta, helpful_vote, status_pill, breadcrumb,
                       site_footer, identity_sheet, empty_state
  _strings.html        the full en / pt-BR / es / ar i18n dict (documentation of every UI key)
  index.html           5.1 Home
  category.html        5.2 /kb/<category>
  article.html         5.3 /kb/article/<slug>  (+ translate / translated toggle)
  search.html          5.4 /search   (+ empty state)
  chat.html            5.5 /chat     (SSR shell + [data-seed]; chat.js hydrates)
  ingame.html          5.6 /ingame   (invalid-token path only: 300ms flash → identity sheet)
  ticket.html          5.7 /ticket/<public_id>
  404.html, 500.html   5.8 errors
  dev_components.html   §10 /dev/components gallery (staff-only)

static/web/
  support.css          all pages; token-only; < 30 KB target (currently ~29 KB uncompressed)
  support.js           non-chat progressive enhancement (identity sheet, vote AJAX, lang, toasts)
  chat.js              /chat only; renders all 11 kinds; transport abstracted in `Transport`
  favicon.svg          SG hexagon on --black
  fixtures/
    chat_demo.json     §7 message-schema contract for chat.js  (TODO(backend): wire /api endpoints)
    kb_demo.json       home / kb / ticket fixtures

preview.html            NOT a deliverable — static render of all pages for review (John's round)
```

## Decisions where the brief was silent

1. **i18n mechanism.** The brief mandates "one Jinja i18n dict" and `t('key')` but not the
   plumbing. Assumed a Python `STRINGS` dict registered as a Jinja global `t(key, **fmt)` with
   English fallback and `{n}`/`{q}`/`{date}` `.format()`-style interpolation. Full dict lives in
   `_strings.html` as the source of truth; move it to `i18n.py` at integration.
2. **Icon set.** No icon library named. Drew a monochrome 1.5px line-art set inline in
   `_icons.html` (no external requests, keeps the JS-zero / transfer budget). Category glyphs map
   1:1 to the 8 KB categories.
3. **Language picker interaction.** Spec shows the control, not the menu. Implemented as a
   cycle-to-next + `?lang=` navigation (server persists to session/cookie). Swap for a listbox
   popover if design wants an explicit menu — the button already carries `aria-haspopup`.
4. **Helpful vote transport.** Enhanced to a `fetch` POST with a no-JS `<form>` fallback to
   `/kb/article/<slug>/vote`. 👎 reveals an inline chat CTA per §4.6.
5. **Chat transport.** Built for fetch-poll at 1.5 s with exponential backoff to 15 s, all inside
   `Transport.send/poll`. To move to SSE (SPEC-02 backend choice), replace only that object.
6. **SSR seed vs. localStorage.** Session restore reads a server-rendered `[data-seed]` JSON block
   then polls; **no** message content is persisted to localStorage (§7 requirement). chat.js removes
   the seed tag after hydrating.
7. **`/ingame` valid-token path** is a server 302 to `/chat`; `ingame.html` renders only on the
   invalid/expired branch (brand flash → identity sheet), so the happy path never touches this template.
8. **`context_card` EDIT** and the `sid_prompt` LINK ACCOUNT both open the same identity sheet
   (single source of truth). Dismissing `sid_prompt` reveals the persistent under-header nudge.
9. **Chat i18n in JS.** chat.js reads localized strings from `data-t-*` attributes the server can
   stamp on `[data-chat]`, with English fallbacks inline — keeps the JS free of a bundled dict.

## Brand / accessibility conformance

- Tokens only from §2; **zero border-radius**; no color in chrome — status colors confined to
  ticket pills and success/error toasts.
- Buttons: transparent + 1px white border, Space Mono uppercase, invert on hover, 35% disabled,
  easing `cubic-bezier(.22,.61,.36,1)` / 170 ms.
- H1 CLS killed via `@font-face` `size-adjust` fallback for Archivo.
- Focus-visible = 2px white offset. Transcript `aria-live="polite"`. Chips are real `<button>`s
  (full keyboard path). All inputs labelled. `prefers-reduced-motion` kills the typing pulse and
  transitions.
- RTL: authored with logical properties throughout; `dir="rtl"` on `<html lang="ar">` mirrors the
  layout for free. SIDs / ticket ids / codes / timestamps forced LTR with `dir="ltr"` spans.
- Chevrons/arrows flip under `[dir="rtl"]`.

## Budgets

- `support.css` ~29 KB uncompressed (target < 30 KB). `chat.js` ~21 KB (target < 40 KB).
- Non-chat pages: `support.js` is deferred progressive-enhancement only — pages fully function with
  it removed (the "JS = 0" transfer intent).
- Fonts: preconnect + `display=swap`, weights subset to what's used (Archivo 800/900, Inter 400/500/600,
  Space Mono 400/700).

## TODO(backend) — integration points

- `url_for('static', …)` calls assume Flask static serving.
- `t()` global + `STRINGS` dict (from `_strings.html`) must be registered on the Jinja env.
- Wire `/api/web/chat/message` and `/api/web/chat/poll` to the SPEC-02 contracts; `chat_demo.json`
  documents the exact message shapes chat.js consumes.
- Guard `/dev/components` behind the staff flag.
- Provide `identity` (`{sid, is_guest, masked_sid}`), `web_chat_enabled`, `lang`, `dir` in the base
  context for every route.

## Screenshots

`preview.html` renders every page/state (360–390 px frames) + the full chat with all 11 kinds.
Open it and capture 360 px + 768 px per page for John's review round.
