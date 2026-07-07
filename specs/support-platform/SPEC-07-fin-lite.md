# SPEC-07 — Fin-lite: the operating frame, metrics, and test harness

*Phase P6 (metrics parts can ship right after P2). This spec maps what Intercom Fin offers
to our stack, so the whole platform reads as one coherent product: a lightweight Fin for
Service + Sales + Ecommerce, at a fraction of the cost (Fin charges ~$0.99/resolution;
our Tier-2 marginal cost is ~$0.003, Phase B ~100× less again).*

## 1. Feature map (Fin → ours)

| Fin | Ours | Where |
|-----|------|-------|
| Resolution categories: Informational / Personalized / Tasks / Human-complex | Tier taxonomy: Informational = Tier 0/1/2 KB answers; Personalized = Tier 2 + PlayerContext; Tasks = guarded actions (dashboard-only for now); Human = Tier 3 | SPEC-03/05 |
| Handoff triggers: can't confidently answer / guided to escalate / customer asks | `tau_clarify` clarify-then-escalate; `sensitive_categories` forced escalation; `human_request` intent | SPEC-03 |
| Trained on your help content | KB (108 articles) + approved-answers corpus + tone learning | existing |
| Engage (proactive messenger) | Deeplink triage greeting from `entry`/`error_code` | SPEC-04 |
| Discover → Qualify → Close (Sales) | Catalog KB → deterministic qualify rules → checkout deeplink | SPEC-06 |
| CRM handoff with context | Escalation carries PlayerContext + chat_context into Ticket Review | SPEC-04/05 |
| Automation-rate benchmark ("up to 92% in Gaming") | Deflection dashboard (below); our KB coverage already ~94% at Tier 2 | this spec |

## 2. Metrics & dashboard (Stage 6 of the original roadmap)

Extend `/api/dashboard/metrics` + a new dashboard page "Support Analytics":

- **Automation rate** = sessions resolved with no human / total sessions (the Fin headline
  number), split by Informational / Personalized / Human, weekly trend.
- **Deflection funnel**: KB view → chat opened → resolved in chat → escalated.
- **CSAT**: 👍/👎 at session close (+ optional 1-tap emoji scale), per tier and per category.
- **Cost**: tokens + $ per session/resolution (from `chat_usage`), Tier-2 share trend
  (should fall as Tier 1 grows and Phase B lands).
- **Quality evals**: nightly replay of a fixed 100-question golden set through the router;
  alert on tier-distribution drift or similarity drop (reuses the replay harness +
  tone-measurement similarity metric).
- **SLA/routing**: escalated tickets get priority (payments > bans > bugs > general),
  time-to-first-human-response tracked per priority.
- SID coverage (SPEC-01) and offers funnel (SPEC-06) panels.

## 3. Preview/test harness (Fin's "See Fin in action")

A staff-only page in the Ops Dashboard: pick a scenario tab (Informational / Personalized /
Handoff), a canned question set per tab, and a live sandbox chat that runs the real runtime
against a **staging flag** (`preview=true`: nothing persists to the live corpus, budgets
sandboxed, PlayerContext from a test SID). Used for: regression checks before config
changes, demoing to the team, and red-team prompts. Cheap to build — it is the SPEC-02 chat
UI pointed at a sandbox session.

## 4. Guardrail layer (consolidated policy, one place)

`app/policy.py` — single choke-point every outbound bot message passes through:
1. Category policy (sensitive → escalate templates only);
2. Scope policy (Prime Rush topics only — gate result rechecked);
3. Content lint: no invented prices/policies (regex against currency/percent patterns not
   present in retrieved chunks), no account-action promises, no PII echo;
4. Minors policy: minor-flagged accounts → no recognition, no offers, conservative replies;
5. Audit: every check result logged per message (`policy_log`), queryable from the
   dashboard — the "full audit trail of every automated action" from Stage 6.

## 5. Acceptance criteria

1. Analytics page live with automation rate, funnel, CSAT, cost, SID coverage.
2. Nightly golden-set eval running with alerting (dashboard banner + summary email).
3. Preview harness works in staging mode; nothing leaks into the live corpus.
4. `policy.py` intercepts all outbound paths (chat, future auto-reply, offers) — proven by
   an integration test that a forbidden message is blocked on each path.

## 6. Agent execution notes

- Touch: `app/dashboard_api.py`, dashboard templates in `play-review-responder`,
  `app/policy.py`, `policy_log` migration, `scripts/nightly_eval.py` (cron on Railway).
- The golden set: sample 100 questions stratified across categories/tiers from the
  historical corpus; store as fixture with expected tier + reference answer.
