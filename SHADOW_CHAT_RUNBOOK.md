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
