# Shadow Chat — deploy & test runbook

*Companion to `specs/support-platform/SPEC-08-shadow-chat-agent.md`. Both repos are
committed locally; steps below push and verify on Railway.*

## 1. Push (run on your Mac)

```bash
cd ~/Documents/Claude/Projects/PrimeRush-Bot
git push origin master          # → Railway auto-deploys SupportBot (primebot.up.railway.app)

cd ~/github/robytj/play-review-responder
git push origin main            # → Railway auto-deploys the Ops Dashboard
```

Note: `scripts/resolve_sids.py` has pre-existing uncommitted changes in PrimeRush-Bot
(not part of shadow chat — review/commit separately). `outputs/` and the retheme notes
were left uncommitted on purpose.

## 2. Railway env (one-time, SupportBot service)

In Railway → SupportBot (play-review-support) → Variables:

- `MONGO_URI` — copy the value from the responder service (same read-only user its
  cheater module uses). Without it, chat still works but in degraded mode (no player
  data, no recognition, no purchase/ban lookups).
- `BANNED_STATES` — optional, defaults to `Locked,Suspended,Banned`.
- `python-multipart` installs automatically (now in requirements.txt).

DB migrations (chat tables, `conversations.public_id`, 4 `ban_response` canned drafts)
run automatically on boot — no manual DB step, no re-sync needed.

## 3. Validate Mongo field mapping (the probe)

Anywhere `MONGO_URI` is set (Railway shell, or locally):

```bash
# via Railway CLI, from the PrimeRush-Bot repo:
railway run python -m scripts.probe_player_context
# or locally:
MONGO_URI='mongodb+srv://…' python -m scripts.probe_player_context
```

It resolves the 8 sample SIDs (EDFXPT5G, 2S6WGTSK, Y3MXP81Y, TEPFTFMN, VAHE3PVK,
BSMMQXYM, G32KQ2JH, DX4GW6CS), prints each player context (emails masked), and dumps the
shape of one `user.transaction` doc — check the product/status field names it reports; if
they differ from the tolerant defaults in `app/player_context.py`, tell Claude and we
patch the projection.

## 4. API smoke test (optional, before opening the tab)

```bash
KEY=$SUPPORT_SERVICE_API_KEY   # the SupportBot service key (responder calls it SUPPORTBOT_API_KEY)
BASE=https://primebot.up.railway.app

# start a session → expect greeting + game chips
curl -s -X POST $BASE/api/dashboard/chat/sessions -H "Authorization: Bearer $KEY" | python3 -m json.tool

# advance it (use the session_id from above)
curl -s -X POST $BASE/api/dashboard/chat/sessions/1/messages \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"text":"PrimeRush.gg (LatAm)"}' | python3 -m json.tool
```

## 5. Test in the dashboard

Open the Ops Dashboard → **Support Chat** tab (visible to all logged-in users). Suggested
script, in order:

1. **Happy path**: greet → pick game → give `EDFXPT5G` → confirm name → check the
   recognition lines quote real tenure/games → ask "how do I link my account?" → expect a
   KB-grounded answer + CSAT chips.
2. **Purchases**: ask "did my last purchase go through?" → expect a summarized
   transaction reply (no raw records).
3. **Ban path**: use a banned SID → expect the staff-facing ban assessment card + a reply
   drawn only from the `ban_response` canned drafts (edit them in SupportKB).
4. **Guardrails**: mention a different SID in a question → refusal. Ask about another
   game / homework → out-of-scope deflection (3 strikes ends the session). Ask for a
   human → escalation card with `PR-XXXXX`.
5. **Escalation lands**: Ticket Review → source filter **Chat** → open the ticket, check
   context summary and transcript.
6. **SID failure path**: give a junk SID 3× → image-upload offer → screenshot extraction.
7. **Budgets/timeout**: T2 counter in the header chip (n/8); idle 5 min → nudge, 10 min →
   session closes.

## 6. Kill switch

Support Settings → **chat_enabled** off → tab shows "chat switched off"; sessions return
503. The Discord token / shadow-mode arrangement is untouched.

## 7. Public support site sample (SPEC-02) — custom domain + preview

The player-facing site (`app/web_support.py`, Claude Design package in
`templates/web/` + `static/web/`) ships on this same Railway service. Rollout:

1. **Preview first, before any DNS**: the full site is already live on the
   service's default domain under the `/site` prefix —
   `https://primebot.up.railway.app/site` (home, `/site/kb/<category>`,
   `/site/kb/article/<slug>`, `/site/search?q=`, `/site/chat` demo,
   `/site/ticket/<public_id>`). Root-absolute links inside pages are
   307-redirected into `/site/...`, so click-through works end to end.
   The component gallery is at `/site/dev/components?key=<SITE_DEV_KEY>`
   (set the `SITE_DEV_KEY` env var first; unset = the page 404s).
2. **Attach the custom domain**: Railway → the web service → **Settings →
   Networking → Custom Domain** → add `support.primerush.gg`. Railway shows the
   CNAME target; create that CNAME record at the DNS provider for the
   `support` subdomain of `primerush.gg`. Wait for the domain to show
   "Issued certificate".
3. **Set the host env** (already the default, set it explicitly anyway):
   `SUPPORT_SITE_HOST=support.primerush.gg`. Requests arriving with that Host
   header are served the site at ROOT paths (`https://support.primerush.gg/`);
   the API surface (`/api/dashboard/*`, `/chat`, `/health`) does not exist on
   that domain. Every other host (the `primebot.up.railway.app` default)
   keeps all existing API routes untouched at root plus the `/site` preview.
4. **Sample-mode notes for the review round**: `/chat` is DEMO MODE (transcript
   seeded from `static/web/fixtures/chat_demo.json`, labelled "PREVIEW — demo
   transcript"; real chat API = SPEC-02 §5 + SPEC-03), `/ingame` renders the
   invalid-token identity sheet only (JWT verify = SPEC-02 §4), article
   translation serves the `kb_translations` cache only. KB pages, search,
   helpful votes (`kb_votes` table) and `/ticket/<public_id>` run on live data.

## 8. 2026-07-09 — purchase-intent regression (postmortem + fixes)

**What players saw (session #19):** "i cant find my purchse" and "show my
purchases" both answered with the out-of-scope deflection; a human had to take
over. Session #16 (earlier) had answered the same question fine.

**Root cause:** the scope gate builds its in-scope centroids from
`kb_articles WHERE status='published' AND category != ''`. The DB that went up
during the Railway re-sync has no published+categorized KB rows (the SPEC-08-era
Package-B playbook articles are missing/draft), so the gate silently built ZERO
KB centroids and could only classify into its 4 special buckets — purchase
wording sits nearest `out_of_scope` (its seed list contains purchase-flavored
bait like "check my brother's purchase history"). Code never changed; the data
under it did. Two structural bugs made it possible: data intents ran AFTER the
gate, and a degenerate centroid build was silent.

**Fixes (all in this repo, tested):**
1. `app/chat_engine.py` — purchase/ban data intents now run BEFORE the scope
   gate (an explicit human ask still outranks them and escalates).
2. `app/intents.py` (new) — typo-tolerant intent + support-concern lexicons
   (Damerau-Levenshtein ≤ 1 on a curated fuzzy-safe word set: "purchse",
   "suspnded" work; "killed"≠"billed", "change"≠"charge" guarded).
3. `app/scope_gate.py` — refuses special-classes-only centroid math (falls back
   to the keyword classifier, loud `[warn]`), and every out_of_scope/abuse
   deflection is vetoed first by the support-concern lexicons. Explicit red
   flags (other-game names, jailbreak phrasing) always deflect.
4. `GET /api/dashboard/chat/health` now returns `scope_gate` (backend, KB
   centroid count, healthy flag) + `highlight_baselines` — a degenerate gate is
   dashboard-visible, never silent again.

**Ops step still required on Railway (data fix, restores the good centroids):**
```bash
railway run python scripts/seed_support_playbook.py   # idempotent, 14 published+categorized articles
# then verify:
curl -s -H "Authorization: Bearer $SUPPORT_SERVICE_API_KEY" \
  https://<service>/api/dashboard/chat/health | jq .scope_gate
# expect: {"backend": "centroid", "kb_centroids": >=1, "healthy": true}
```
After any future DB replace/re-sync, re-run the seed + health check. (The gate
also self-heals per process start once the articles exist — restart after seeding.)

## 9. Player highlights + PrimeRush flavor (2026-07-09)

While the bot works (purchase lookups, Tier-2 answers) it now drops ONE
"while I pull that up" line: first the player's own precomputed highlights,
then PrimeRush facts/jokes — alternating, no repeats, max 4/session, never two
turns in a row, never on ban replies. Recognition upgrades to percentile brags
("top 1% of all PrimeRush players") when baselines exist.

- Content lives in `app/flavor.py` (EDITABLE starter lists — curate freely).
- Highlight metrics + percentile logic: `app/highlights.py`. Money is invisible
  by design: no purchase/spend metrics can appear in a highlight.
- Population baselines (needed for "top X%" claims; elite-fallback thresholds
  apply until then): `railway run python scripts/build_player_baselines.py
  --sample 2000` — samples real accounts (AI excluded per SPEC-11 id-length +
  isBot), writes `player_baselines`. Re-run weekly-ish or after big meta shifts.
- Kill switches in config.yaml (hot-reload): `chat.flavor_enabled`,
  `chat.highlights_enabled`.
- Future feed: per-weapon/per-mode accuracy from the SPEC-11 match-recorder
  cache would unlock "top 1% accuracy with <gun> in <mode>" — add as new
  metrics in `app/highlights.METRICS` with their own baselines.
