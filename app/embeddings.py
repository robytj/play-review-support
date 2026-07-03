"""fastembed wrapper -- local CPU embeddings, free, per spec section 1.

Falls back to a deterministic hash embedding if fastembed can't load (no network /
model download blocked). The fallback is NOT semantically meaningful -- it exists so
the rest of the pipeline (schema, router, dashboard) can be smoke-tested offline. Real
deployments must have fastembed actually working; get_embedder() prints a loud warning
if it falls back so this can't fail silently in production.
"""
import hashlib
import numpy as np

from app.config import EMBEDDING_MODEL, EMBEDDING_DIM

_embedder = None
_using_fallback = False


def _load_fastembed():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=EMBEDDING_MODEL)


def get_embedder():
    global _embedder, _using_fallback
    if _embedder is not None:
        return _embedder
    try:
        _embedder = _load_fastembed()
        print(f"[info] fastembed loaded: {EMBEDDING_MODEL}")
    except Exception as e:
        print(f"[warn] fastembed unavailable ({e!r}) -- using non-semantic hash "
              f"fallback embeddings. DO NOT run this in production; fix the fastembed "
              f"install/model download first.")
        _using_fallback = True
        _embedder = "fallback"
    return _embedder


def _hash_embed(text: str) -> np.ndarray:
    """Deterministic pseudo-embedding for offline smoke tests only."""
    vec = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    for tok in text.lower().split():
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
        vec[h % EMBEDDING_DIM] += 1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def embed(text: str) -> np.ndarray:
    """Returns a unit-normalized float32 vector of length EMBEDDING_DIM."""
    embedder = get_embedder()
    if embedder == "fallback":
        return _hash_embed(text)
    vec = next(embedder.embed([text]))
    vec = np.asarray(vec, dtype=np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


def embed_batch(texts: list[str]) -> list[np.ndarray]:
    embedder = get_embedder()
    if embedder == "fallback":
        return [_hash_embed(t) for t in texts]
    out = []
    for vec in embedder.embed(texts):
        vec = np.asarray(vec, dtype=np.float32)
        norm = np.linalg.norm(vec)
        out.append(vec / norm if norm > 0 else vec)
    return out


def is_using_fallback() -> bool:
    get_embedder()
    return _using_fallback
