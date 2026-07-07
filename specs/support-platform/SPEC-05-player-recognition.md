# SPEC-05 — Player-aware support: recognition, encouragement, personalized context

*Phase P4. Depends on SPEC-03/04 (identified sessions). This is roadmap Stage 3 (read-only
tools) + Stage 5 (personalization) applied to chat, plus the "make the player feel
recognized" layer. Gated by a `recognition_enabled` toggle in Support Settings.*

## 1. Player context service (read-only tool layer)

New `app/player_context.py` — deterministic lookups, cached per session (TTL 10 min):

| Source | Fields | Notes |
|--------|--------|-------|
| Game Mongo (read-only creds) | account age, level/progress, ban state, platform, guest/registered | same connection as `sid_lookup`; read-only user (rotate per pending task) |
| Amplitude (SuperPlatform) | days played, current/best streak, sessions last 7d, milestones (level-ups, wins), churn-risk band, spend cohort band | query via existing Amplitude project; cache aggressively |
| SuperX (Supabase) | recent purchases/orders, entitlement grant status (`IndusGrantRequest` results), creator code used | known gap: full inventory per SID not yet exposed — start with orders only |

Output: a typed `PlayerContext` dict; also rendered in Ticket Review detail so staff see
exactly what the bot saw.

## 2. How context is used (two distinct uses, different rules)

### 2.1 Accuracy (personalized answers)
Inject relevant facts into Tier-2 retrieval-augmented prompts as **data, not prose**:
purchase state for payment questions, ban state for account questions, platform/version for
bug questions. This is the Fin "personalized" resolution category: "Did my payment clear?"
becomes answerable. Sensitive categories remain escalate-only on public chat (SPEC-03), but
the escalated ticket now carries the context so the human resolves it in one touch.

### 2.2 Recognition (feel-good layer)
- Server-side **recognition fact selector** picks at most **2 facts** from a whitelist:
  account tenure ("4 years with us"), streaks, recent milestone, comeback ("good to see you
  back"). Facts are computed deterministically; the LLM never invents or embellishes them.
- Delivery points (templates first, Tier-2 phrasing optional): greeting suffix on chat
  open, and resolution close ("Sorted! Nice work on that 12-win streak, by the way.").
- **Hard rules**:
  - Never reference spend, purchases, or churn risk in recognition (creepy/manipulative).
  - Skip entirely when: category is payments/refund/ban/deletion, detected sentiment is
    negative (reuse language-detect module's heuristics + simple lexicon), player is a
    minor-flagged account, or session is a repeat contact about the same open ticket.
  - Frequency cap: once per session, max twice per week per SID (`recognition_log` table).
  - Tone: brief, specific, no superlatives; localized.
- A/B measure (Amplitude): CSAT (👍/👎 on close) and return-to-game rate with/without
  recognition before making it default-on.

## 3. Acceptance criteria

1. `PlayerContext` resolves for a test SID from all three sources with graceful partial
   degradation (any source down → context omits it, chat still works).
2. Payment-status question in an identified session produces a personalized, grounded
   answer (fixture test with stubbed sources).
3. Recognition never fires on the excluded categories/sentiment (test set), respects caps,
   and is toggleable off at runtime.
4. Staff-visible context card matches bot-visible context exactly.

## 4. Agent execution notes

- New: `app/player_context.py`, `recognition_log` table, config block `recognition:`
  (enabled, fact whitelist, caps), Amplitude query wrapper.
- Blocked inputs: read-only game-DB credentials (rotation task), Amplitude project/API key,
  SuperX Supabase read scope for orders (coordinate with W).
- Keep every lookup read-only. Guarded write actions (restore purchase, appeal) stay in the
  dashboard per roadmap Stage 3 — not in public chat in this phase.
