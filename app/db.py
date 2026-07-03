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
    source TEXT DEFAULT '',                  -- e.g. freshdesk ticket ids, comma-separated
    embedding BLOB,                          -- fallback brute-force store (always kept, cheap insurance)
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
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


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
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
