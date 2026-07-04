# Running Freshdesk KB ingestion (from your own machine)

This can't run from the Claude sandbox — its network allowlist blocks
`api.freshdesk.com` (confirmed 2026-07-04: proxy returns `403 blocked-by-allowlist`)
and it can't download the `fastembed` model either. Both scripts are written and
tested for structure, just never run against real data. Run these from your laptop
or Railway's console instead.

## 1. Open a terminal in this folder

This `PrimeRush-Bot` folder on your Mac is the actual git working copy (same
files Claude edits directly) — there's no separate clone to pull first.

```bash
cd /Users/roby1/Documents/Claude/Projects/PrimeRush-Bot
```

## 2. Set up a virtualenv and install deps

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

The first run will download the `fastembed` model (`BAAI/bge-small-en-v1.5`,
~130MB) from Hugging Face — that's the other thing the sandbox couldn't do.

## 3. Set your Freshdesk API key

Your `.env` should already have `FRESHDESK_DOMAIN` and `FRESHDESK_API_KEY` set
(matching what's on Railway). If not, get the key from Freshdesk → profile icon
(top right) → Profile Settings → API Key.

```bash
export FRESHDESK_API_KEY=$(grep FRESHDESK_API_KEY .env | cut -d= -f2)
export FRESHDESK_DOMAIN=$(grep FRESHDESK_DOMAIN .env | cut -d= -f2)
```

## 4. Pull ticket history from Freshdesk

Start small to sanity-check before pulling everything:

```bash
python scripts/ingest_freshdesk.py --domain "$FRESHDESK_DOMAIN" --limit 20 --out data/freshdesk_sample.json
cat data/freshdesk_sample.json | head -50   # eyeball it -- real subjects/bodies, resolutions present?
```

If that looks right, pull everything:

```bash
python scripts/ingest_freshdesk.py --domain "$FRESHDESK_DOMAIN" --out data/freshdesk_export.json
```

This only pulls CLOSED/RESOLVED tickets and strips private agent notes -- only
the player's own message and PUBLIC agent replies feed the KB.

## 5. Build the KB from the export

```bash
python scripts/build_kb.py --in data/freshdesk_export.json
```

This embeds each ticket, greedy-clusters similar ones (cosine sim >= 0.80), and
makes one Claude Haiku call per cluster to draft a KB article. Needs
`ANTHROPIC_API_KEY` set in `.env`. Articles land with `status='draft'` --
nothing is live until you approve them.

## 6. Review and publish drafts

Either via the dashboard (Support tab, once you're logged in as admin -- draft
articles show a "Publish" button), or directly:

```bash
sqlite3 data/supportbot.db "SELECT id, title, status FROM kb_articles;"
sqlite3 data/supportbot.db "UPDATE kb_articles SET status='published' WHERE id=1;"
```

## 7. Get the KB onto Railway

The `data/supportbot.db` you just built is local. Railway's copy is on its own
volume and won't see this automatically. Two options:

- **Easiest:** run steps 3-6 directly in Railway's own shell/console instead of
  locally (`railway run bash` if you have the CLI, or the Shell tab in the
  Railway dashboard) -- then there's nothing to move, it's already the live DB.
- **If you built it locally first:** copy `data/supportbot.db` up via
  `railway run -- cp data/supportbot.db /path/to/volume/` or just re-run steps
  3-6 in Railway's console pointed at the same Freshdesk export file.

Either way, confirm afterward: the Support tab's Knowledge base card should
show your drafted articles (or published ones, once you approve them).
