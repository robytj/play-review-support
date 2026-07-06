"""Live, at-ingestion SID resolution (§4B / PHASE_6_7_SPEC Phase 6).

The batch backfill (scripts/resolve_sids.py) resolves SIDs for historical tickets; this is
the same idea for NEW tickets, called by the Discord shadow branch when a ticket arrives so
`conversations.player_id` is set from the start (the SID-first gate on the send endpoint
then has something to check).

Resolution order:
  1. A SID the player supplied (e.g. parsed from the Ticket King card) -> VALIDATE it
     against `account.shortId` (indexed) and use it if it exists.
  2. Else the sender/registered email -> `account.email.id` (indexed) -> `shortId`.
  3. Else None (agent/bot must ask — the SID-first intake ask, see SID_FIRST_INTAKE.md).

Safe/degradable: if pymongo/dnspython isn't installed or MONGO_URI is unset, every call
returns None and the bot keeps working (ticket just lands without a SID). Only direct,
indexed equality queries — never scans (per the brx_main load rules).
"""
from __future__ import annotations

import os
import re

MONGO_URI = os.environ.get("MONGO_URI", "")
MONGO_ACCOUNT_COLLECTION = os.environ.get("MONGO_ACCOUNT_COLLECTION", "account")
MONGO_EMAIL_FIELD = os.environ.get("MONGO_EMAIL_FIELD", "email.id")
MONGO_SID_FIELD = os.environ.get("MONGO_SID_FIELD", "shortId")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_client = None
_unavailable = False  # set once if the driver/URI is missing, to stop retrying


def _coll():
    global _client, _unavailable
    if _unavailable:
        return None
    if not MONGO_URI:
        _unavailable = True
        return None
    if _client is None:
        try:
            from pymongo import MongoClient
        except ImportError:
            _unavailable = True
            return None
        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    return _client.get_default_database()[MONGO_ACCOUNT_COLLECTION]


def resolve_sid(email: str | None = None, claimed_sid: str | None = None) -> str | None:
    """Return the player's SID (`shortId`) or None. Best-effort, never raises."""
    coll = _coll()
    if coll is None:
        return None
    try:
        if claimed_sid:
            claimed = claimed_sid.strip()
            if claimed and coll.find_one({MONGO_SID_FIELD: claimed}, {"_id": 1}):
                return claimed  # valid SID the player gave us — no email lookup needed
        if email:
            e = email.strip().lower()
            if _EMAIL_RE.fullmatch(e):
                doc = coll.find_one({MONGO_EMAIL_FIELD: e}, {MONGO_SID_FIELD: 1})
                if doc:
                    sid = doc.get(MONGO_SID_FIELD)
                    return str(sid) if sid is not None else None
    except Exception:
        return None
    return None
