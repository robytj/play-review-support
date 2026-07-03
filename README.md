# PrimeRush SupportBot

Discord + web-chat support agent for PrimeRush. Built from `support-bot-simple-spec.md`.
See that spec for the full design rationale — this README is just "how to run it."

Separate service from `play-review-responder` (that repo handles Play Store review
replies + cheater detection — unrelated product surface, same brand).

## Architecture

One FastAPI backend, hit by two thin channel adapters (Discord bot, web widget) that
both call the same `app.router.answer()` function. One SQLite DB (+ sqlite-vec for
similarity search). Local `fastembed` for embeddings (free, no API calls). Claude
Haiku only for the genuine long-tail (Tier 2) — everything else is $0.

```
Discord bot ──┐
              ├──▶ FastAPI (/chat /feedback) ──▶ router.answer() ──▶ SQLite + sqlite-vec
Web widget ───┘                                        │
                                                         ▼
                                                  Claude Haiku (Tier 2 only)
```

## Local setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY at minimum
```

## Bootstrap the KB (Phase 1)

```bash
# smoke-test the pipeline with fake data, no API key needed:
python scripts/build_kb.py --dummy

# real run, once you have a Freshdesk export:
python scripts/ingest_freshdesk.py --domain your-subdomain --out data/freshdesk_export.json
python scripts/build_kb.py --in data/freshdesk_export.json
```

New articles land with `status='draft'`. Nothing is live until you flip a row to
`status='published'` (the dashboard, once built, does this with one click — for now,
`sqlite3 data/supportbot.db "UPDATE kb_articles SET status='published' WHERE id=1"`).

## Try it without Discord or the widget

```bash
python scripts/cli_test.py
```

## Run the server

```bash
uvicorn app.main:app --reload
curl -X POST localhost:8000/chat -H 'content-type: application/json' \
  -d '{"channel":"web","external_id":"test-session","text":"how do I reset my password"}'
```

## Status

- [x] Phase 1 — KB pipeline, tiered router, `/chat` `/feedback` `/health`. Smoke-tested
      (schema, sqlite-vec, router tiers 0/1/3, FastAPI request cycle all verified).
      Tier 2 (Haiku RAG) and real `fastembed` model download need real network egress
      to Anthropic/HuggingFace — untested in the build sandbox, expected to work as-is
      on Railway or your local machine.
- [ ] Phase 2 — Discord bot adapter
- [ ] Phase 3 — Dashboard
- [ ] Phase 4 — Web widget + nightly learning job
- [ ] Deploy to Railway
