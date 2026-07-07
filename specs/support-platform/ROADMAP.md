# PrimeRush Support Platform — Master Roadmap & Spec Pack

*Last updated: 2026-07-07. Audience: coding agents + PrimeRush support/engineering.*
*Prerequisite reading: `PROJECT_HANDOFF.md`, `SHADOW_BACKFILL_SPEC.md`, `SID_FIRST_INTAKE.md`, `PHASE_6_7_SPEC.md` (repo root).*

## 0. What this pack is

The existing roadmap (Stages 1–6 in `SupportBot_Overview_and_Roadmap.md`) ends at "real-time
channels + personalization + guardrails." This pack turns that into concrete, agent-executable
specs, and extends it with the webstore/sales dimension (SuperX) and the cost-efficiency
dimension (SuperTuned). It is a **lightweight Fin** (Intercom) for PrimeRush: Fin for Service →
our support chat; Fin for Sales/Ecommerce → our coupon + Prime Market sales agent — built on
the SupportBot tiered router instead of a live frontier-LLM agent per message.

## 1. Ground truth (what exists, do not re-invent)

- **SupportBot** (`PrimeRush-Bot` repo → `primebot.up.railway.app`): FastAPI + offline Discord
  bot, single SQLite DB on a Railway volume. Tables: `conversations` (has `player_id` = SID,
  `origin` (live|backfill), `status`), `messages`, `suggestions` (immutable
  `suggested_answer`, separate `edited_answer`, `tier`, `status`, and the channel column
  `source` (discord|freshdesk|email — extend with `web`)), `kb_articles` (108 published), `canned`, `answer_cache`,
  `tone_cache`, `ticket_translations`, `kb_translations`.
- **Tiered router** (`app/router.py`): Tier 0 canned → Tier 1 approved answer cache → Tier 2
  Haiku RAG over published KB (fastembed local embeddings + sqlite-vec, cosine thresholds
  `tau_canned` / `tau_answer_cache` / `tau_retrieval_confidence` in `config.yaml`) → Tier 3
  escalate. ~94% of historical tickets answerable at Tier 2.
- **SID resolution** (`app/sid_lookup.py`): validate claimed SID or resolve email → Mongo
  `account.email.id` → `account.shortId`. Admin link `admin.brx.indusgame.com/player/<SID>`.
  Mongo env vars not yet set on Railway.
- **Ops Dashboard** (`play-review-responder`, Flask + Google OAuth): calls
  `/api/dashboard/*` with a Bearer key. Ticket Review, SupportKB, Support Settings live here.
- **Safety design**: shadow mode toggle, approve-to-send guards, immutable suggestion corpus,
  Discord token unset = kill switch. **All of it stays.**
- **SuperX Webstore** (`SuperXWebstore`): Next.js 16 + Supabase + Xsolla. Auth flows: in-app
  deeplink `/ingame?sessionToken=<JWT>`, SID + OTP via in-app inbox, email/password. Phases:
  Catalog → Prime Market (personalized "night market") → Transfer (Xfer) Market. Creator
  codes exist in code; entitlement grants via `IndusGrantRequest`; profile via `/users/me`.
  Known gap: no full inventory read per SID yet.
- **SuperTuned** (`SuperTuned`): per-studio LoRA adapters (80–120 MB) on Qwen3-30B-MoE served
  at Fireworks (~14 ms, ~1–2% of frontier token cost), SFT → DPO pipeline via Understudy,
  on-device ONNX micro-models (~200 KB) via Unity Sentis. Player data: Amplitude + SuperPlatform
  (session shape, D1/D7 retention, churn risk, spend cohort, skill tier).

## 2. Phase plan

Phases are ordered by dependency and risk. Each has its own spec file; each spec ends with
acceptance criteria and agent execution notes. P0 and the existing pending items
(deploy latest work, rotate secrets, Mongo env vars, DB re-sync per `BACKFILL_RUNBOOK.md`)
come first — nothing below works well without SIDs.

| Phase | Spec | Delivers | Maps to request | Depends on |
|-------|------|----------|-----------------|------------|
| P0 | `SPEC-01-sid-intake.md` | SID asked + "find your SID" helper on every surface; ingestion-time resolution | Item 1 | Mongo env vars |
| P1 | `SPEC-02-support-site.md` | `support.primerush.gg`: mobile-first Helpshift-lite KB + login/guest + chat entry, served by SupportBot FastAPI | Items 2, 5 | P0 |
| P2 | `SPEC-03-chat-runtime.md` | Cost-efficient chat brain: scope gate + tiered router + budgets; SuperTuned adapter as later Tier-2 swap | Item 3 | P1 |
| P3 | `SPEC-04-in-app-deeplink.md` | In-app Support button → deeplink with signed context; agent identifies the problem; every chat persists as a ticket | Item 4 (+3) | P1, SuperX JWT |
| P4 | `SPEC-05-player-recognition.md` | Player-profile context: encouragement, recognition, milestones — guarded | Item 6 | P2, P3 |
| P5 | `SPEC-06-offers-sales-agent.md` | Post-resolution coupons/rebates (SuperX), later Prime Market / Xfer Market sales agent | Item 7 | P4, SuperX coupons API |
| P6 | `SPEC-07-fin-lite.md` | The Fin-lite frame: resolution taxonomy, handoff rules, automation-rate dashboard, preview harness | Item 8 (spans all) | P2 |

**Recommended execution order:** P0 → P1 → P2 (launch web chat in shadow/preview) → P3 →
P6 metrics → P4 → P5. SuperTuned Tier-2 migration (in P2, Phase B) whenever the training
corpus and eval bar are met — it is a swap, not a rewrite.

## 3. How this composes with the existing Stage 1–6 roadmap

- Stage 1 (approve-to-send) and Stage 2 (assisted auto-reply): unchanged, proceed in parallel.
  Web chat launches **read-only-equivalent**: the bot answers Tier 0/1/2 live in chat (that's
  the point of chat), but every exchange is persisted as a suggestion row for review, so the
  correction corpus keeps growing. Sensitive categories always escalate.
- Stage 3 (agentic actions): P3's context payload + P4's player-context service are the
  read-only tool layer. Guarded writes (restore purchase, ban appeal) remain behind the
  dashboard's reserved action buttons.
- Stage 4 (real-time channels): P1 + P2 + P3 are it.
- Stage 5 (context/language/personalization): P4 + the existing translation pipeline
  (`ticket_translations`, `kb_translations`, pt/es/ar) reused for chat.
- Stage 6 (measurement/guardrails): P6.

## 4. Global invariants (apply to every spec)

1. **Human-reviewable always**: every bot chat answer is stored as a `suggestions` row
   (`source='web'` — new value on the existing channel column), immutable, visible in
   Ticket Review.
2. **Kill switches**: a single `web_chat_enabled` toggle in Support Settings gates the whole
   chat runtime; per-feature toggles for recognition (P4) and offers (P5).
3. **Never invent**: no policy, price, account state, or compensation is generated. Facts come
   from the KB, the router's grounded tiers, or deterministic server-side lookups.
4. **Sensitive categories** (payments/refunds, bans, account deletion, minors) never get
   Tier-2 generation on the public chat — Tier 0/1 or escalate.
5. **Cost ceilings**: per-session and daily global token budgets enforced in code, not policy.
6. **SID-first**: every surface asks for SID (or registered email) before or during chat;
   resolved `player_id` persists on the conversation at intake.
