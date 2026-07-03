"""Vector similarity search over kb_articles / canned / answer_cache.

Primary path: sqlite-vec (vec0 virtual tables) -- what the spec calls for and what
Railway will actually run. Fallback: brute-force cosine similarity in numpy over the
`embedding` BLOB column every table already has, used when the sqlite extension can't
be loaded (e.g. a locked-down sandbox with load_extension disabled). Every row is
always written to BOTH paths so switching is transparent and nothing is ever lost.
"""
import struct
import numpy as np

from app import db as _db
from app.db import get_conn
from app.config import EMBEDDING_DIM

# Whether the sqlite_vec Python package + extension mechanism works AT ALL in this
# environment -- an environment-level fact, safe to cache process-wide. Whether it's
# been LOADED ON THIS SPECIFIC CONNECTION is a different question (extension loading
# is per-connection, and connections are thread-local -- see app/db.py get_vec_status).
_vec_mechanism_ok = None


def _try_enable_vec(conn) -> bool:
    global _vec_mechanism_ok
    cached = _db.get_vec_status()
    if cached is not None:
        return cached
    if _vec_mechanism_ok is False:
        _db.mark_vec_status(False)
        return False
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _vec_mechanism_ok = True
        _db.mark_vec_status(True)
        if cached is None:
            print("[info] sqlite-vec loaded")
    except Exception as e:
        if _vec_mechanism_ok is None:
            print(f"[warn] sqlite-vec unavailable ({e!r}) -- using brute-force numpy "
                  f"cosine search fallback. Fine at KB-article/canned-response scale "
                  f"(hundreds-thousands of rows); revisit if that changes.")
        _vec_mechanism_ok = False
        _db.mark_vec_status(False)
    return _db.get_vec_status()


def ensure_vec_table(table: str):
    """table is one of: kb_articles, canned, answer_cache. Creates a matching
    vec0 shadow table `vec_<table>` when sqlite-vec is available."""
    conn = get_conn()
    if _try_enable_vec(conn):
        conn.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_{table} USING vec0("
            f"row_id INTEGER PRIMARY KEY, embedding FLOAT[{EMBEDDING_DIM}])"
        )
        conn.commit()


def _blob(vec: np.ndarray) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec.tolist())


def _unblob(b: bytes) -> np.ndarray:
    n = len(b) // 4
    return np.array(struct.unpack(f"{n}f", b), dtype=np.float32)


def upsert(table: str, row_id: int, vec: np.ndarray):
    """Writes the embedding to the row's `embedding` column (always) and to the
    vec0 shadow table (if available)."""
    conn = get_conn()
    blob = _blob(vec)
    conn.execute(f"UPDATE {table} SET embedding = ? WHERE id = ?", (blob, row_id))
    if _try_enable_vec(conn):
        ensure_vec_table(table)
        conn.execute(f"DELETE FROM vec_{table} WHERE row_id = ?", (row_id,))
        conn.execute(f"INSERT INTO vec_{table}(row_id, embedding) VALUES (?, ?)",
                     (row_id, blob))
    conn.commit()


def search(table: str, query_vec: np.ndarray, top_k: int = 4, where: str = "1=1"):
    """Returns list of (row_id, similarity) sorted best-first. `where` is an extra
    SQL filter on the base table (e.g. "status = 'published'")."""
    conn = get_conn()
    if _try_enable_vec(conn):
        ensure_vec_table(table)
        blob = _blob(query_vec)
        rows = conn.execute(
            f"""
            SELECT v.row_id, v.distance
            FROM vec_{table} v
            JOIN {table} t ON t.id = v.row_id
            WHERE v.embedding MATCH ? AND k = ? AND ({where})
            ORDER BY v.distance
            """,
            (blob, top_k),
        ).fetchall()
        # sqlite-vec returns L2 distance on normalized vectors; convert to cosine sim.
        return [(r["row_id"], 1 - (r["distance"] ** 2) / 2) for r in rows]

    # brute-force fallback
    rows = conn.execute(f"SELECT id, embedding FROM {table} WHERE embedding IS NOT NULL AND ({where})").fetchall()
    scored = []
    for r in rows:
        v = _unblob(r["embedding"])
        sim = float(np.dot(query_vec, v))  # both unit-normalized -> dot == cosine
        scored.append((r["id"], sim))
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]
