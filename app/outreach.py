"""SPEC-09 §5 player outreach -- wired but INERT by default.

send_inbox_message() is the ONE function that would talk to IndusAPI (the admin
panel's Communication → Inbox System), so confirming the real endpoint/payload
contract is a one-file change. Today it NEVER sends anything:

1. runtime toggle `outreach_enabled` (config.yaml `outreach:` block, flipped from
   Support Settings) is OFF by default;
2. env INDUS_API_URL / INDUS_API_TOKEN / INDUS_TENANT_ID are all unset;
3. even with both satisfied, the exact IndusAPI inbox-send contract is
   unconfirmed **[TODO John/W: confirm from IndusAPI — the admin UI uses the
   Communication module; per-player read is `GET /{id}/inbox-message`]** -- so the
   final branch refuses too, on purpose, until that TODO is resolved.

Push notifications: no push endpoint exists in the admin UI source -- TODO to
confirm with W (likely a different service). The dashboard reserves a disabled
"Push" button; there is deliberately no send_push() here yet.

Every attempt (even a refusal) is logged by the caller (dashboard_api) as an
`outreach_inbox` ticket_events row -- title + first 80 chars only, never the
full body.
"""
import os

from app import config

REQUIRED_ENV = ("INDUS_API_URL", "INDUS_API_TOKEN", "INDUS_TENANT_ID")


def _missing_env() -> list[str]:
    return [k for k in REQUIRED_ENV if not os.environ.get(k)]


def status() -> dict:
    """Powers the dashboard's outreach buttons (disabled states honest about why)."""
    missing = _missing_env()
    enabled = bool(getattr(config, "OUTREACH_ENABLED", False))
    if not enabled:
        reason = "outreach_enabled is OFF (Support Settings)"
    elif missing:
        reason = f"IndusAPI env not configured ({', '.join(missing)} unset)"
    else:
        reason = "IndusAPI inbox-send contract unconfirmed (TODO John/W)"
    return {
        "inbox_available": False,   # flips only when the TODO above is resolved
        "enabled": enabled,
        "configured": not missing,
        "reason": reason,
        "push_available": False,
        "push_reason": "pending game-server API",
    }


def send_inbox_message(sid: str, title: str, body: str, actor: str) -> dict:
    """Attempt an in-game inbox send. Returns {"sent": bool, "reason": str|None}.
    Guaranteed inert today -- every guard path returns a refusal; nothing here
    performs network I/O until the IndusAPI contract TODO is confirmed."""
    st = status()
    if not st["enabled"] or not st["configured"] or not st["inbox_available"]:
        print(f"[info] outreach: REFUSED inbox send to {sid!r} by {actor!r} -- {st['reason']}")
        return {"sent": False, "reason": st["reason"]}
    # Unreachable today (inbox_available is hard False). When the contract is
    # confirmed, the IndusAPI POST goes here and nowhere else.
    return {"sent": False, "reason": "not implemented"}
