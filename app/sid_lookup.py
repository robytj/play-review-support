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

# THE SID format regex (SPEC-01 §2) -- one definition for every surface.
# app/player_context.py imports this same object; do not redefine it elsewhere.
# 8 chars, capital letters + digits (e.g. CS9DNY34). Format check is cosmetic
# pre-filtering only; the server always re-validates against Mongo.
SID_RE = re.compile(r"^[A-Z0-9]{8}$")
# Body-scan variant: same shape but with word boundaries, for pulling SID-shaped
# tokens out of free ticket text (email bodies, Discord questions).
SID_SCAN_RE = re.compile(r"\b[A-Z0-9]{8}\b")
# At most this many scanned candidates are validated against Mongo per ticket --
# keeps a pathological ticket (a log dump full of 8-char tokens) from turning
# ingestion into a Mongo query storm.
SCAN_CANDIDATE_CAP = 3

# SPEC-01 §2 -- the shared "find your SID" helper, pt-BR primary + EN.
# TODO(John): screenshots (logged-in + guest) are a pending input -- text-only
# until they land; also confirm the exact in-game path below.
SID_HELPER_TEXT = (
    "**Não sabe seu ID? / Don't know your SID?**\n"
    "1. Abra o Prime Rush e toque na engrenagem (Configurações). / "
    "Open Prime Rush and tap the gear (Settings).\n"
    "2. Entre em Perfil. / Go to Profile.\n"
    "3. Toque no código de 8 caracteres abaixo do seu nome para copiá-lo e cole aqui. / "
    "Tap the 8-character code under your name to copy it, then paste it here."
)

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
    # DB name: URI path if present, else MONGO_DB_NAME (Railway sets the name
    # separately — the shared URI has no default database in its path).
    try:
        db = _client.get_default_database()
    except Exception:
        db = _client[os.environ.get("MONGO_DB_NAME", "brx_main")]
    return db[MONGO_ACCOUNT_COLLECTION]


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


def scan_sid_candidates(text: str | None, cap: int = SCAN_CANDIDATE_CAP) -> list[str]:
    """SID-shaped tokens from free ticket text: deduped in order of appearance,
    digit-bearing tokens first (all-caps 8-letter WORDS like 'SETTINGS' match the
    shape too, so tokens that contain a digit are far better candidates), capped
    at `cap`. Callers validate each against Mongo -- this is only the shortlist."""
    if not text:
        return []
    tokens: list[str] = []
    for tok in SID_SCAN_RE.findall(text):
        if tok not in tokens:
            tokens.append(tok)
    tokens.sort(key=lambda t: not any(ch.isdigit() for ch in t))  # stable sort
    return tokens[:cap]


def resolve_from_ticket(claimed_sid: str | None = None, email: str | None = None,
                        body_text: str | None = None) -> tuple[str | None, str | None]:
    """Ingestion-time resolution (SPEC-01 §3): returns (sid, sid_source) or
    (None, None). Priority order -- a SID the player claimed (validated against
    Mongo) beats an email match, which beats a body scan. sid_source values here:
    'claimed' | 'email_match' | 'scan' ('deeplink'/'manual' are set by other
    surfaces). Best-effort/degradable like resolve_sid(): Mongo down or driver
    missing -> (None, None), never raises, ingestion never crashes."""
    try:
        if claimed_sid:
            claimed = claimed_sid.strip().upper()
            if SID_RE.fullmatch(claimed) and resolve_sid(claimed_sid=claimed):
                return claimed, "claimed"
        if email:
            sid = resolve_sid(email=email)
            if sid:
                return sid, "email_match"
        for cand in scan_sid_candidates(body_text):
            if resolve_sid(claimed_sid=cand):
                return cand, "scan"
    except Exception:
        pass
    return None, None
