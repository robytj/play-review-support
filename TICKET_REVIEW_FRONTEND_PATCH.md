# Ticket Review grid — frontend patch (apply in `play-review-responder`)

The SupportBot backend now serves the To / From / Date columns and a per-ticket
translation. This repo (`play_reviewer.py` → `TICKETREVIEW_HTML` + the
`/api/support/suggestions*` proxy routes) needs the matching UI. `play-review-responder`
wasn't mounted in the session that built the backend, so apply these snippets by hand.

## 1. New fields on each `/api/support/suggestions` row

The proxied grid rows now include (no proxy change needed — it's a pass-through):

| field               | meaning                                                        |
|---------------------|----------------------------------------------------------------|
| `to_display`        | **To**: email→recipient support address; freshdesk→support inbox; discord→`ticket-19 / <id>` |
| `from_display`      | **From**: email/freshdesk→sender email; discord→player's display name (first non-bot author) |
| `reported_date`     | **Date**: original message date (`YYYY-MM-DD`), not the replay/import date |
| `date_is_estimated` | `true` when `reported_date` is an import stamp (freshdesk has no real date) — render softer, e.g. "≈ 2026-07-05" or a "reported" tooltip |

`admin_url` still carries the SID deep link (populated once `scripts/resolve_sids.py`
runs — see PROJECT_HANDOFF §4A #3).

## 2. Grid columns

Add three headers to the grid's `<thead>` (place before the existing status/actions cells):

```html
<th>From</th>
<th>To</th>
<th>Date</th>
```

And the matching cells in the row template (adapt `r` to your row variable):

```js
`<td class="from">${esc(r.from_display || '—')}</td>` +
`<td class="to">${esc(r.to_display || '—')}</td>` +
`<td class="date${r.date_is_estimated ? ' est' : ''}"` +
  `${r.date_is_estimated ? ' title="reported/import date — original unknown"' : ''}>` +
  `${r.reported_date ? (r.date_is_estimated ? '≈ ' : '') + r.reported_date : '—'}</td>`
```

(If the grid builds cells with DOM APIs rather than string templates, set
`textContent` from the same fields — the key point is the three fields above.)

Optional styling:

```css
td.date.est { color: #999; font-style: italic; }
```

## 3. Translate button (detail pane)

New backend endpoint (already live on SupportBot):

```
GET /api/dashboard/suggestions/{id}/translate?target=en
```

Add a proxy route in `play_reviewer.py` mirroring the existing
`/api/support/suggestions/...` proxies:

```python
@app.route("/api/support/suggestions/<int:sid>/translate")
@require_login
def support_translate(sid):
    target = request.args.get("target", "en")
    return _supportbot_get(f"/suggestions/{sid}/translate", params={"target": target})
```

(Use whatever helper the other `/api/support/*` routes already use to attach
`Authorization: Bearer <SUPPORTBOT_API_KEY>` and forward to `SUPPORTBOT_API_URL`.)

Response shape:

```json
{
  "suggestion_id": 123, "target_lang": "en", "source_lang": "pt",
  "skipped": false, "cached": true,
  "question": "...", "staff_answer": "...", "final_answer": "..."
}
```

- `skipped: true` → ticket was already English; fields echo the originals.
- First call translates via Haiku and caches; every later call returns `cached: true` instantly.

Detail-pane button + handler:

```html
<button id="translateBtn" onclick="translateTicket(currentId)">🌐 Translate to English</button>
<div id="translateNote" class="muted"></div>
```

```js
async function translateTicket(id) {
  const btn = document.getElementById('translateBtn');
  btn.disabled = true; btn.textContent = 'Translating…';
  try {
    const res = await fetch(`/api/support/suggestions/${id}/translate?target=en`);
    const t = await res.json();
    if (t.skipped) {
      document.getElementById('translateNote').textContent = 'Already in English.';
    } else {
      // Swap the detail fields to the translated text (keep originals to toggle back if you like).
      setDetailField('question', t.question);
      setDetailField('staffAnswer', t.staff_answer);
      setDetailField('finalAnswer', t.final_answer);
      document.getElementById('translateNote').textContent =
        `Translated from ${t.source_lang || 'source'}${t.cached ? ' (cached)' : ''}.`;
    }
  } finally {
    btn.disabled = false; btn.textContent = '🌐 Translate to English';
  }
}
```

Wire `setDetailField(...)` to whatever your detail pane uses to render the question /
staff reply / suggested answer. The `edited_answer` textarea should keep editing the
**original** answer — translation is a read-only review aid, not a source edit.

## 4. Pre-warming (optional)

Running `python -m scripts.translate_tickets` on SupportBot pre-translates every
non-English ticket into the cache, so the button is instant for reviewers on first
click. See PROJECT_HANDOFF §4C.
