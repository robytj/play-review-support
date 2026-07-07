# SPEC-03 — Cost-efficient chat runtime (not a live LLM agent per message)

*Phase P2. Depends on SPEC-02. Phase A ships on the existing stack; Phase B is the
SuperTuned adapter swap. Design goal: most messages cost $0; the rest cost Haiku-with-a-cap;
the bot only answers Prime Rush questions.*

## 1. Principle

Chat is the **same tiered router** the ticket pipeline already uses (`app/router.py`),
wrapped in a conversational shell with a scope gate in front and hard budgets around it.
A live frontier-LLM agent per message is explicitly out of scope.

## 2. Per-message pipeline (Phase A)

```
player msg → (0) normalize + language detect        [$0, offline heuristic, exists]
           → (1) scope & intent gate                 [$0, local embeddings]
           → (2) tiered router                       [Tier 0/1 $0; Tier 2 capped Haiku]
           → (3) clarify-or-answer policy            [$0 template or included in Tier 2]
           → (4) persist (messages + suggestions)    [SPEC-02 §5]
```

### (1) Scope & intent gate — the cost firewall
Local fastembed classification (embed the message, cosine against labeled centroids in
sqlite-vec; no API call):

- Classes: the 8 KB categories, `smalltalk`, `human_request`, `abuse`, `out_of_scope`.
- Seed centroids from existing corpus: 2,855 historical questions are already labeled by KB
  category via retrieval — average their vectors per class; `out_of_scope` seeded from a
  handwritten list (~50 examples: homework, other games, general chatbot bait, jailbreaks).
- Routing: `out_of_scope`/`abuse` → fixed canned deflection ("I can only help with Prime
  Rush…") — zero tokens, counter incremented, 3 strikes → end session politely.
  `smalltalk` → tiny canned set. `human_request` → escalate (Tier 3). Category classes →
  router, with category passed as a retrieval filter hint.
- A `scope_gate` config block in `config.yaml`: on/off, thresholds, strike limit.

### (2) Tiered router in chat mode
- **Tier 0/1 unchanged** — canned + approved answer cache, $0 marginal. Expect these to grow
  fast: every approved web answer seeds Tier 1, so the system gets cheaper with volume
  (Fin-style "resolution reuse").
- **Tier 2 (capped Haiku RAG)**: existing `answer_with_rag()` with chat additions:
  - `max_tokens` ≤ 400 (existing), `top_k` 3 (existing).
  - **Multi-turn context**: last 4 turns verbatim (~1k tokens max); older turns replaced by
    a one-line running summary updated locally (template-based, not LLM).
  - **Anthropic prompt caching** on the static prefix (system + tone `style_block` + safety
    rules) — already the pattern used for tone; extend to the chat system prompt.
  - **Grounding contract** (system prompt): answer only from provided KB chunks; if
    insufficient, say so and offer escalation; never state prices/policies/account actions
    not in the chunks. Sensitive categories (payments, bans, deletion, minors) are
    **excluded from Tier 2 on the public chat** — Tier 0/1 or escalate (config list
    `sensitive_keywords` exists; add `sensitive_categories`).
- **Tier 3**: escalate → ticket per SPEC-02 §5, with a holding reply and the `public_id`.

### (3) Clarify-or-answer (the Fin handoff pattern)
When Tier-2 retrieval confidence is between `tau_retrieval_confidence` and a new lower bound
`tau_clarify`, don't generate an answer — ask a structured clarifying question built from the
top-2 retrieved articles' titles ("Are you asking about A or B?" as tappable chips). One
clarify round max, then answer or escalate. This mirrors Fin's "share partial context, ask
clarifying questions, or escalate" and costs a template, not tokens.

### Budgets (enforced in code)
- Per session: max **8 Tier-2 calls**; after that, Tier 0/1 or escalate.
- Per session: max 30 messages / 30 minutes idle timeout.
- Global: daily Tier-2 token budget (config; e.g. 2M tokens/day) — breach flips chat to
  "Tier 0/1 + escalate only" mode and alerts (dashboard banner).
- All counters in a `chat_usage` table; surfaced in `/api/dashboard/metrics`.

## 3. Phase B — SuperTuned adapter as the Tier-2 brain

When the corpus and eval bar are met, swap the Tier-2 generator; nothing else changes.

- **Model**: LoRA adapter on Qwen3-30B-MoE served at Fireworks (SuperTuned stack:
  ~14 ms, ~1–2% of frontier per-token cost, adapter hot-swappable).
- **Training data (already accumulating by design)**:
  - SFT pairs: `question + retrieved KB chunks → approved final_answer` from the
    suggestions corpus (approved + sent, including web chat), plus correction pairs
    (`suggested_answer → edited_answer`) which encode tone and policy.
  - DPO pairs: approve/reject signals and 👍/👎 chat feedback as chosen/rejected.
- **Gate to switch** (evaluated with the existing replay harness):
  1. ≥ 3,000 approved answer pairs including ≥ 500 from live web chat;
  2. Adapter ≥ Haiku on a held-out replay set (similarity-to-staff-answer metric already
     used for tone measurement, plus human spot-check of 100);
  3. Grounding/refusal behavior verified on a red-team set (out-of-scope, injection,
     sensitive categories).
- **Rollout**: `rag.backend: haiku | supertuned` config switch; shadow-run the adapter on
  N% of Tier-2 calls first (log both, serve Haiku), then flip. Haiku remains the fallback
  path on adapter serving errors.
- **Optional micro-models** (SuperTuned ONNX pattern): distill the scope/intent gate into a
  ~1 MB ONNX classifier that can also run inside the game client to pre-route before the
  deeplink (SPEC-04) — nice-to-have, not gating.

## 4. Cost model (order-of-magnitude, for the dashboard)

- Target steady state: ≥ 60% of messages resolved at $0 (gate + Tier 0/1 + templates);
  Tier-2 Haiku ≈ $0.002–0.004/answer at 400 out / ~2k in with prompt caching; Phase B cuts
  Tier-2 by ~50–100×. Track real numbers via `chat_usage` — the dashboard shows
  cost/session and cost/resolution, the Fin-style headline metric.

## 5. Acceptance criteria

1. Out-of-scope prompts (test set of 50) are deflected with zero model calls; Prime Rush
   questions route to the correct tier ≥ 90% on a labeled test set of 100.
2. Session/budget caps demonstrably enforce (integration tests).
3. Sensitive-category questions never produce Tier-2 generations on `/api/web/*`.
4. Every bot answer visible in Ticket Review with tier + `source='web'`.
5. Phase B ships behind the `rag.backend` switch with shadow-compare logs.

## 6. Agent execution notes

- New: `app/scope_gate.py`, `app/chat.py` (session loop, budgets, clarify policy),
  `chat_usage` + centroid tables, config additions (`scope_gate`, `tau_clarify`,
  `sensitive_categories`, `chat_budgets`, `rag.backend`).
- Reuse: `app/router.py` (call it, don't fork it), `app/llm.py`, `app/tone.py`,
  `app/vectorstore.py`.
- Phase B integration lives behind an interface (`app/generators/{haiku,supertuned}.py`);
  coordinate serving details (Fireworks endpoint, adapter id) with W / SuperTuned side.
