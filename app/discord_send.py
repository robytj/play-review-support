"""The SINGLE place in the whole system that writes to Discord (PHASE_6_7_SPEC Phase 6).

Posts a message to a channel/thread via the Discord REST API using the bot token — no
gateway needed for posting. Kept deliberately tiny and separate so "what can write to
Discord?" has exactly one answer. The send endpoint in app/dashboard_api.py is the only
caller, and only after its full guard stack passes (approved + live + discord + SID +
shadow_mode ON + not-already-sent).

DISCORD_BOT_TOKEN stays UNSET on Railway until John's Phase-6 go-live checklist, so this
raises NotConfigured until then — a safe default (no token = cannot post).
"""
from __future__ import annotations

import requests

from app.config import DISCORD_BOT_TOKEN

API_BASE = "https://discord.com/api/v10"


class NotConfigured(RuntimeError):
    """DISCORD_BOT_TOKEN is unset — posting is intentionally impossible."""


class SendFailed(RuntimeError):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"discord send failed ({status}): {detail}")


def post_message(channel_id: str, content: str, timeout: float = 10.0) -> str:
    """Post `content` to channel/thread `channel_id`. Returns the new Discord message id.
    Raises NotConfigured if the token is unset, SendFailed on a non-2xx (incl. 404 for a
    deleted ticket channel, 429 rate-limit, 403 missing access)."""
    if not DISCORD_BOT_TOKEN:
        raise NotConfigured("DISCORD_BOT_TOKEN unset")
    if not content or not content.strip():
        raise SendFailed(0, "refusing to send empty content")
    resp = requests.post(
        f"{API_BASE}/channels/{channel_id}/messages",
        headers={
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "PrimeRushSupportBot (approve-to-send, +https://primebot.up.railway.app)",
        },
        json={"content": content[:2000]},  # Discord hard limit
        timeout=timeout,
    )
    if resp.status_code // 100 != 2:
        raise SendFailed(resp.status_code, resp.text[:300])
    return str(resp.json().get("id", ""))
