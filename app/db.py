"""SQLite schema + connection helpers. One DB file: kb_articles, canned, conversations,
messages, feedback, metrics_daily -- per the spec's 'one database' rule."""
import sqlite3
import threading
from contextlib import contextmanager

from app.config import DB_PATH

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS kb_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    symptom TEXT NOT NULL,
    answer TEXT NOT NULL,
    tags TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',   -- draft | published
    category TEXT DEFAULT '',                -- one of app/config.py KB_CATEGORIES; '' = not yet categorized
    source TEXT DEFAULT '',                  -- e.g. freshdesk ticket ids, comma-separated
    embedding BLOB,                          -- fallback brute-force store (always kept, cheap insurance)
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Cached machine translations of a kb_articles row, keyed by (article_id, lang).
-- Generated on-demand the first time the SupportKB tab asks for a given language
-- (see app/llm.py translate_article() + the /kb/{id}/translate/{lang} endpoint),
-- then served from here after that. Invalidated (deleted) whenever the source
-- article's title/symptom/answer is edited, so a stale translation is never shown.
CREATE TABLE IF NOT EXISTS kb_translations (
    article_id INTEGER NOT NULL REFERENCES kb_articles(id),
    lang TEXT NOT NULL,             -- 'pt' | 'es' | 'ar'
    title TEXT NOT NULL,
    symptom TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (article_id, lang)
);

CREATE TABLE IF NOT EXISTS canned (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_text TEXT NOT NULL,     -- representative question this canned entry answers
    answer TEXT NOT NULL,
    source_article_id INTEGER REFERENCES kb_articles(id),
    embedding BLOB,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS answer_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_text TEXT NOT NULL,
    answer TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,   -- only approved (positive-feedback) answers get reused
    send_count INTEGER NOT NULL DEFAULT 0,
    positive_count INTEGER NOT NULL DEFAULT 0,
    negative_count INTEGER NOT NULL DEFAULT 0,
    embedding BLOB,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel TEXT NOT NULL,          -- discord | web
    external_id TEXT,               -- discord thread id / web session id
    status TEXT NOT NULL DEFAULT 'open',  -- open | escalated | resolved | paused
    context TEXT DEFAULT '',        -- json: page_url, order_id, etc.
    player_id TEXT,                 -- parsed from Ticket King's "ID da sua conta" field, if present
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL,             -- user | bot | human
    tier_used INTEGER,              -- 0,1,2,3 (null for user/human messages)
    text TEXT NOT NULL,
    retrieved_chunks TEXT DEFAULT '', -- json
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    signal TEXT NOT NULL,           -- thumbs_up | thumbs_down | reasked | human_takeover
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS metrics_daily (
    date TEXT PRIMARY KEY,
    tier0_count INTEGER DEFAULT 0,
    tier1_count INTEGER DEFAULT 0,
    tier2_count INTEGER DEFAULT 0,
    tier3_count INTEGER DEFAULT 0,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd_micros INTEGER DEFAULT 0,  -- store as micros to avoid float drift
    thumbs_up INTEGER DEFAULT 0,
    thumbs_down INTEGER DEFAULT 0
);
"""


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.commit()
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_conn():
    """Thread-local connection -- safe under uvicorn's threadpool and discord.py's asyncio loop."""
    if not hasattr(_local, "conn"):
        _local.conn = _connect()
    return _local.conn


def get_vec_status():
    """None = not yet attempted on this thread's connection, True/False otherwise.
    sqlite3.Connection objects don't support attribute assignment or weakrefs, so the
    'has this connection had the sqlite-vec extension loaded' flag has to live here,
    keyed to the same thread-local as the connection itself (see app/vectorstore.py --
    extension loading is per-connection, not process-wide, so a naive global flag would
    wrongly skip re-loading it on every new thread's fresh connection)."""
    return getattr(_local, "vec_loaded", None)


def mark_vec_status(loaded: bool):
    _local.vec_loaded = loaded


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)


def _migrate(conn):
    """Small in-place migrations for columns added after the initial deploy --
    CREATE TABLE IF NOT EXISTS above doesn't add columns to an already-existing
    table, so new columns need an explicit, idempotent ALTER TABLE here. Not
    worth a full migration framework for a single-file SQLite app this size."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(conversations)").fetchall()}
    if "player_id" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN player_id TEXT")
        conn.commit()
    # source/origin dimension for the unified ticket store (Discord backfill,
    # Freshdesk + email import). 'live' rows come from the running bot/web widget;
    # 'backfill' rows are imported history the live bot must never act on.
    if "origin" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN origin TEXT DEFAULT 'live'")
        conn.commit()

    msg_cols = {row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()}
    if "author_name" not in msg_cols:
        # display name for backfilled staff/player messages (live rows leave it '')
        conn.execute("ALTER TABLE messages ADD COLUMN author_name TEXT DEFAULT ''")
        conn.commit()

    kb_cols = {row["name"] for row in conn.execute("PRAGMA table_info(kb_articles)").fetchall()}
    if "category" not in kb_cols:
        conn.execute("ALTER TABLE kb_articles ADD COLUMN category TEXT DEFAULT ''")
        conn.commit()

    # Persistent, never-regenerated store of bot-generated responses (backfill
    # replay + Freshdesk/email replay + Phase-6 live shadow). See SHADOW_BACKFILL_SPEC
    # §4. suggested_answer is IMMUTABLE once written (constraint 6): edits go in
    # edited_answer; a regeneration is a NEW row with supersedes_id set, never an
    # UPDATE. Deliberately kept out of messages/metrics_daily/answer_cache so
    # replay/pending drafts never pollute the live pipeline.
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id),
            source TEXT NOT NULL DEFAULT 'discord',   -- discord | freshdesk | email
            question TEXT NOT NULL,
            suggested_answer TEXT NOT NULL,           -- IMMUTABLE once written
            edited_answer TEXT,                       -- display/send uses COALESCE(edited, suggested)
            tier INTEGER,
            retrieved_chunks TEXT DEFAULT '',         -- json
            staff_answer TEXT,                        -- actual historical human reply (NULL for live until sent)
            status TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | sent | rejected
            approved_at TEXT,
            sent_at TEXT,
            discord_message_id TEXT,                  -- set after a Phase-6 send
            supersedes_id INTEGER REFERENCES suggestions(id),
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_suggestions_convo ON suggestions(conversation_id);
        CREATE INDEX IF NOT EXISTS idx_suggestions_source_status ON suggestions(source, status);

        -- Future-proofing for action buttons (design only; nothing builds actions
        -- yet). Lets "Restore purchase" etc. slot in later -- manual trigger first.
        CREATE TABLE IF NOT EXISTS suggestion_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            suggestion_id INTEGER NOT NULL REFERENCES suggestions(id),
            action_type TEXT NOT NULL,
            payload_json TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            executed_at TEXT
        );

        -- Cached machine translations of a ticket (PROJECT_HANDOFF §4C), mirroring
        -- the kb_translations pattern above. Keyed by (suggestion_id, target_lang):
        -- much support content is Portuguese/Spanish/etc and the Ticket Review pane
        -- offers a "translate" button, so each ticket is translated ONCE with Haiku
        -- and served from here after that (never per-view). `source_lang` records the
        -- detected original language so an English ticket is cached as a no-op skip.
        -- Rows translate the reviewer-facing fields: the player's question, the
        -- historical staff_answer, and the bot's final_answer.
        CREATE TABLE IF NOT EXISTS ticket_translations (
            suggestion_id INTEGER NOT NULL REFERENCES suggestions(id),
            target_lang TEXT NOT NULL,          -- e.g. 'en'
            source_lang TEXT DEFAULT '',        -- detected original; '' if unknown
            question TEXT DEFAULT '',
            staff_answer TEXT DEFAULT '',
            final_answer TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (suggestion_id, target_lang)
        );
        """
    )
    conn.commit()


@contextmanager
def tx():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def bump_metric(date: str, field: str, delta: int = 1):
    with tx() as conn:
        conn.execute(
            f"INSERT INTO metrics_daily (date, {field}) VALUES (?, ?) "
            f"ON CONFLICT(date) DO UPDATE SET {field} = {field} + excluded.{field}",
            (date, delta),
        )
