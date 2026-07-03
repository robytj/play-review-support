"""Env + config.yaml loader. Single place every module pulls settings from."""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

with open(ROOT / "config.yaml") as f:
    _cfg = yaml.safe_load(f)

# --- thresholds & tunables (from config.yaml, hot-editable without redeploy if you wire the dashboard to rewrite this file) ---
TAU_CANNED = _cfg["thresholds"]["tau_canned"]
TAU_ANSWER_CACHE = _cfg["thresholds"]["tau_answer_cache"]
TAU_RETRIEVAL_CONFIDENCE = _cfg["thresholds"]["tau_retrieval_confidence"]

RAG_TOP_K = _cfg["rag"]["top_k"]
RAG_MODEL = _cfg["rag"]["model"]
RAG_MAX_TOKENS = _cfg["rag"]["max_tokens"]

EMBEDDING_MODEL = _cfg["embeddings"]["model"]
EMBEDDING_DIM = _cfg["embeddings"]["dim"]

SENSITIVE_KEYWORDS = [k.lower() for k in _cfg["escalation"]["sensitive_keywords"]]

LEARNING_MIN_CLUSTER_SIZE = _cfg["learning"]["min_cluster_size"]
CANNED_PROMOTION_MIN_SENDS = _cfg["learning"]["canned_promotion_min_sends"]
CANNED_PROMOTION_MIN_POSITIVE_RATE = _cfg["learning"]["canned_promotion_min_positive_rate"]

# --- secrets / env ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "")
DISCORD_STAFF_ROLE_ID = os.environ.get("DISCORD_STAFF_ROLE_ID", "")
DISCORD_ESCALATION_CHANNEL_ID = os.environ.get("DISCORD_ESCALATION_CHANNEL_ID", "")

FRESHDESK_DOMAIN = os.environ.get("FRESHDESK_DOMAIN", "")
FRESHDESK_API_KEY = os.environ.get("FRESHDESK_API_KEY", "")

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "change-me")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-secure")

DB_PATH = os.environ.get("DB_PATH", str(ROOT / "data" / "supportbot.db"))
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
