"""Env + config.yaml loader. Single place every module pulls settings from."""
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
CONFIG_YAML_PATH = ROOT / "config.yaml"


def _load_yaml():
    with open(CONFIG_YAML_PATH) as f:
        return yaml.safe_load(f)


def _apply(cfg: dict):
    """Assigns module-level globals from a parsed config.yaml dict. Called at
    import time and again by reload() -- the Settings dashboard tab (play_reviewer.py
    /support-settings) rewrites config.yaml then calls POST /api/dashboard/settings,
    which calls reload() so changes apply immediately, no redeploy needed."""
    g = globals()
    g["TAU_CANNED"] = cfg["thresholds"]["tau_canned"]
    g["TAU_ANSWER_CACHE"] = cfg["thresholds"]["tau_answer_cache"]
    g["TAU_RETRIEVAL_CONFIDENCE"] = cfg["thresholds"]["tau_retrieval_confidence"]

    g["RAG_TOP_K"] = cfg["rag"]["top_k"]
    g["RAG_MODEL"] = cfg["rag"]["model"]
    g["RAG_MAX_TOKENS"] = cfg["rag"]["max_tokens"]

    g["EMBEDDING_MODEL"] = cfg["embeddings"]["model"]
    g["EMBEDDING_DIM"] = cfg["embeddings"]["dim"]

    g["SENSITIVE_KEYWORDS"] = [k.lower() for k in cfg["escalation"]["sensitive_keywords"]]

    g["LEARNING_MIN_CLUSTER_SIZE"] = cfg["learning"]["min_cluster_size"]
    g["CANNED_PROMOTION_MIN_SENDS"] = cfg["learning"]["canned_promotion_min_sends"]
    g["CANNED_PROMOTION_MIN_POSITIVE_RATE"] = cfg["learning"]["canned_promotion_min_positive_rate"]

    # Shadow mode lives in config.yaml (not env) specifically so the Support tab's
    # toggle can flip it live via POST /api/dashboard/settings -> write_settings()
    # -> reload(), no redeploy needed. discord_bot/bot.py must reference this via
    # `from app import config; config.DISCORD_SHADOW_MODE` at call time, same
    # hot-reload rule as the thresholds below.
    g["DISCORD_SHADOW_MODE"] = bool(cfg.get("discord", {}).get("shadow_mode", False))

    # Shadow chat agent (SPEC-08). Same hot-reload rule as shadow_mode above:
    # chat_enabled is the kill switch the Support Settings tab flips live via
    # write_settings() -> reload(); everything reads config.CHAT_ENABLED at call
    # time, never a frozen import. .get() defaults keep an older config.yaml
    # (without these blocks) booting fine.
    chat_cfg = cfg.get("chat", {}) or {}
    g["CHAT_ENABLED"] = bool(chat_cfg.get("enabled", False))
    g["TAU_CLARIFY"] = float(chat_cfg.get("tau_clarify", 0.45))
    # HIGH supporter threshold for the recognition thanks (Package A): at least
    # this many completed real-money purchases (direct count or the
    # purchase.aggregated rollup) earns the "biggest supporters" gratitude line.
    g["CHAT_HIGH_PAYER_MIN_PURCHASES"] = int(chat_cfg.get("high_payer_min_purchases", 20))
    budgets = cfg.get("chat_budgets", {}) or {}
    g["CHAT_TIER2_PER_SESSION"] = int(budgets.get("tier2_per_session", 8))
    g["CHAT_MESSAGES_PER_SESSION"] = int(budgets.get("messages_per_session", 30))
    g["CHAT_DAILY_TIER2_CALLS"] = int(budgets.get("daily_tier2_calls", 300))
    sg = cfg.get("scope_gate", {}) or {}
    g["SCOPE_GATE_ENABLED"] = bool(sg.get("enabled", True))
    g["SCOPE_GATE_MIN_SCORE"] = float(sg.get("min_score", 0.35))
    g["SCOPE_GATE_STRIKE_LIMIT"] = int(sg.get("strike_limit", 3))

    # SPEC-09 §3 -- SLA policy: hours to first human response per priority.
    # .get() defaults keep an older config.yaml (without the block) booting fine.
    sla = cfg.get("sla", {}) or {}
    g["SLA_HOURS"] = {
        "P1": int(sla.get("P1", 4)),
        "P2": int(sla.get("P2", 12)),
        "P3": int(sla.get("P3", 24)),
        "P4": int(sla.get("P4", 72)),
    }

    # SPEC-09 §5 -- player-outreach runtime toggle (Support Settings, default
    # OFF). Same hot-reload rule as chat_enabled/shadow_mode above; and even ON,
    # app/outreach.py still refuses until the INDUS_* env exists.
    outreach_cfg = cfg.get("outreach", {}) or {}
    g["OUTREACH_ENABLED"] = bool(outreach_cfg.get("enabled", False))


def reload():
    """Re-reads config.yaml from disk and updates the live module globals.
    NOTE: router.py must reference these via `from app import config; config.TAU_CANNED`
    (module attribute lookup at call time), NOT `from app.config import TAU_CANNED`
    (which freezes the value at import time and won't see reload() changes)."""
    _apply(_load_yaml())
    return get_thresholds_dict()


def get_thresholds_dict() -> dict:
    return {
        "tau_canned": TAU_CANNED,
        "tau_answer_cache": TAU_ANSWER_CACHE,
        "tau_retrieval_confidence": TAU_RETRIEVAL_CONFIDENCE,
        "rag_top_k": RAG_TOP_K,
        "sensitive_keywords": SENSITIVE_KEYWORDS,
        "shadow_mode": DISCORD_SHADOW_MODE,
        "chat_enabled": CHAT_ENABLED,
        "tau_clarify": TAU_CLARIFY,
        "sla_hours": SLA_HOURS,
        "outreach_enabled": OUTREACH_ENABLED,
    }


def write_settings(thresholds: dict = None, sensitive_keywords: list = None, shadow_mode: bool = None,
                   chat_enabled: bool = None, outreach_enabled: bool = None):
    """Used by POST /api/dashboard/settings. Rewrites config.yaml (preserving
    everything else) then reload()s so it takes effect immediately."""
    cfg = _load_yaml()
    if thresholds:
        cfg["thresholds"].update(thresholds)
    if sensitive_keywords is not None:
        cfg["escalation"]["sensitive_keywords"] = sensitive_keywords
    if shadow_mode is not None:
        cfg.setdefault("discord", {})["shadow_mode"] = bool(shadow_mode)
    if chat_enabled is not None:
        # kill switch for the shadow chat agent (SPEC-08 §8) -- lives next to
        # shadow_mode so the Support Settings tab flips it live, no redeploy.
        cfg.setdefault("chat", {})["enabled"] = bool(chat_enabled)
    if outreach_enabled is not None:
        # SPEC-09 §5 player-outreach toggle -- default OFF; flipping it ON still
        # sends nothing until the INDUS_* env + IndusAPI contract exist.
        cfg.setdefault("outreach", {})["enabled"] = bool(outreach_enabled)
    with open(CONFIG_YAML_PATH, "w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return reload()


_apply(_load_yaml())

# --- secrets / env ---
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "")
# May be one role id or several comma-separated (e.g. a Moderator role plus a
# separate Staff Volunteer role) -- discord_bot/bot.py splits on comma and
# treats any of them as staff.
DISCORD_STAFF_ROLE_ID = os.environ.get("DISCORD_STAFF_ROLE_ID", "")
DISCORD_ESCALATION_CHANNEL_ID = os.environ.get("DISCORD_ESCALATION_CHANNEL_ID", "")
# The Discord *category* id the bot actively listens in (spec section 5: "listens
# in your support channel(s), ticket threads, and DMs"). On this server, tickets
# are opened by a separate bot (Ticket King) that creates a brand-new private
# channel per ticket inside one category -- so this must be that category's id,
# not a single channel id. Any channel whose category matches, any thread whose
# parent channel's category matches, and all DMs are in scope. If unset, falls
# back to listening in every channel the bot can see -- fine for a quick local
# test, NOT fine for production.
DISCORD_TICKETS_CATEGORY_ID = os.environ.get("DISCORD_TICKETS_CATEGORY_ID", "")

# NOTE: DISCORD_SHADOW_MODE (whether the bot ingests tickets silently vs.
# actually replies) is set in _apply() from config.yaml, not from an env var
# here -- that's what lets the Support tab's toggle flip it live, no redeploy.

FRESHDESK_DOMAIN = os.environ.get("FRESHDESK_DOMAIN", "")
FRESHDESK_API_KEY = os.environ.get("FRESHDESK_API_KEY", "")

DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "change-me")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-secure")

# Bearer key play_reviewer.py's /support and /support-settings tabs use to call
# this service's /api/dashboard/* endpoints server-to-server. Mirrors
# play-review-responder's own SERVICE_API_KEY pattern. Dashboard API is
# disabled (503) if unset.
SUPPORT_SERVICE_API_KEY = os.environ.get("SUPPORT_SERVICE_API_KEY", "")

# SPEC-02 public support site (app/web_support.py). Requests whose Host matches
# SUPPORT_SITE_HOST are served the player-facing site at root paths (Railway
# custom domain on this same service); every other host gets the same site under
# /site for pre-DNS preview. SITE_DEV_KEY gates the /dev/components gallery
# (?key= must match; unset = gallery always 404s).
SUPPORT_SITE_HOST = os.environ.get("SUPPORT_SITE_HOST", "support.primerush.gg")
SITE_DEV_KEY = os.environ.get("SITE_DEV_KEY", "")

DB_PATH = os.environ.get("DB_PATH", str(ROOT / "data" / "supportbot.db"))
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# Fixed KB category list for the SupportKB tab (play_reviewer.py). Capped at 8 per
# the original request. Adapted from Supercell's Clash of Clans support portal
# taxonomy (Account / Purchases / Gameplay / Troubleshooting / Safe & Fair Play --
# https://support.supercell.com/clash-of-clans/en/), plus PrimeRush-specific asks
# ("Payments", "Updates") and a catch-all bucket so nothing is ever miscategorized
# into the wrong bucket just because it doesn't fit cleanly. Both app/llm.py's
# distill_cluster_to_article() (LLM-assigned, for new articles) and
# app/dashboard_api.py's keyword-heuristic backfill (for older rows with no
# category, no LLM call needed) must only ever emit one of these exact strings.
KB_CATEGORIES = [
    "Account & Login",
    "Payments & Purchases",
    "Gameplay & Progression",
    "Bans & Fair Play",
    "Technical Issues",
    "Updates & Patches",
    "Rewards & Events",
    "General",
]
KB_DEFAULT_CATEGORY = "General"

# Languages the SupportKB tab offers on-demand translation into. Keyed by the
# two-letter code the /api/dashboard/kb/{id}/translate/{lang} endpoint expects.
KB_TRANSLATION_LANGS = {
    "pt": "Portuguese",
    "es": "Spanish",
    "ar": "Arabic",
}
