"""Read-only player context for the shadow chat agent (SPEC-08 §6).

One public call: get_player_context(sid) -> PlayerContext | None. Resolves the SID
against `account.shortId`, then enriches from `user.stats`, `user.transaction`,
`user.reported` and `banned.device` -- every query keyed to that ONE resolved userId
(there is no code path that queries another player, SPEC-08 §3.2), every query
projection-only with explicit limits (brx_main load rules), and every source
individually degradable: a failed lookup logs a [warn] and leaves that field None
while the rest of the context still resolves.

Safe/degradable like app/sid_lookup.py: if pymongo/dnspython isn't installed or
MONGO_URI is unset, get_player_context() always returns None and the chat engine
runs in degraded (KB-only) mode.

Env (existing vars unchanged): MONGO_URI, MONGO_ACCOUNT_COLLECTION, MONGO_SID_FIELD.
New: BANNED_STATES (comma-separated account.state values that count as banned,
default "Locked,Suspended,Banned").
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

MONGO_URI = os.environ.get("MONGO_URI", "")
MONGO_ACCOUNT_COLLECTION = os.environ.get("MONGO_ACCOUNT_COLLECTION", "account")
MONGO_SID_FIELD = os.environ.get("MONGO_SID_FIELD", "shortId")
BANNED_STATES = {
    s.strip() for s in os.environ.get("BANNED_STATES", "Locked,Suspended,Banned").split(",") if s.strip()
}

# Session-scoped cache: the chat engine re-reads the context on most ISSUE_LOOP
# turns; 10 minutes matches the session idle timeout so a context never outlives
# the session that fetched it.
CACHE_TTL_SECONDS = 600
_cache: dict[str, tuple[float, "PlayerContext | None"]] = {}

_client = None
_unavailable = False  # set once if the driver/URI is missing, to stop retrying

SID_RE = re.compile(r"^[A-Z0-9]{8}$")

# account projection -- fields confirmed from the responder's cheater/payments
# modules (SPEC-08 §6). matchesPlayed has two known fallback spellings.
_ACCOUNT_PROJECTION = {
    "_id": 1,
    "shortId": 1,
    "nickname": 1,
    "state": 1,
    "level": 1,
    "matchesPlayed": 1,
    "matchesCount": 1,
    "stats.matchesPlayed": 1,
    "createTime": 1,
    "location": 1,
    "buildVersion": 1,
    "chatBanned": 1,
    "email.id": 1,
    "userDevices.device.deviceId": 1,
    "userDevices.device.type": 1,
}

# user.stats rows (per mode/season) -> aggregate. Sums except longestKillStreak (max).
_STAT_SUM_FIELDS = ("totalKills", "totalWins", "totalLosses", "totalDamage",
                    "totalHeadshotKills", "matchMvpCount", "totalTimeSpent")
_STAT_MAX_FIELDS = ("longestKillStreak",)

# user.transaction per-item fields — confirmed by live probe 2026-07-07:
# actualPrice.{amount,currency,productId}, offerId, orderQuantity, type, response,
# transactionId, pricingOption.paymentSystem, purchasedTime. There is no literal
# "status" field; `response` carries the outcome string.
_TXN_PROJECTION = {
    "pricingOption.paymentSystem": 1,
    "purchasedTime": 1,
    "actualPrice.productId": 1,
    "actualPrice.amount": 1,
    "actualPrice.currency": 1,
    "offerId": 1,
    "orderQuantity": 1,
    "type": 1,
    "response": 1,
    "transactionId": 1,
}
_TXN_SCAN_LIMIT = 200   # newest N transactions considered for the summary
_RECENT_TXNS = 5


@dataclass
class PlayerContext:
    sid: str
    user_id: object = None            # account._id (int in brx_main)
    nickname: str = ""
    state: str = ""
    level: int | None = None
    matches_played: int | None = None
    create_time: datetime | None = None
    location: str | None = None
    build_version: str | None = None
    chat_banned: bool = False
    email: str | None = None
    device_ids: list = field(default_factory=list)
    stats: dict | None = None         # aggregated user.stats, None if source failed
    transactions: dict | None = None  # summary dict, None if source failed
    payer_tier: str = "NONE"          # ACTIVE | DORMANT | LAPSED | NONE
    report_count_90d: int | None = None
    banned_device_overlap: bool = False
    is_banned: bool = False

    @property
    def email_masked(self) -> str | None:
        if not self.email or "@" not in self.email:
            return None
        user, _, domain = self.email.partition("@")
        return f"{user[:2]}***@{domain}"

    @property
    def playing_since(self) -> str | None:
        return self.create_time.strftime("%B %Y") if self.create_time else None


def _db():
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
        return _client.get_default_database()
    except Exception:
        return _client[os.environ.get("MONGO_DB_NAME", "brx_main")]


def _nickname_str(v) -> str:
    """account.nickname is a dict in prod: {'local': 'QuenteCapitão', 'tag': '4497',
    'value': 'QuenteCapitão4497'} (probe 2026-07-07). Prefer the unique 'value',
    fall back to local+tag, tolerate plain strings."""
    if isinstance(v, dict):
        if v.get("value"):
            return str(v["value"])
        local, tag = v.get("local") or "", v.get("tag") or ""
        return f"{local}{tag}" if local else ""
    return str(v or "")


def _to_dt(v) -> datetime | None:
    """createTime / purchasedTime tolerant parse: datetime, epoch seconds or millis."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, (int, float)):
        try:
            ts = float(v)
            if ts > 1e11:  # millis
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    return None


def _get_path(doc: dict, path: str):
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _account(db, sid: str) -> dict | None:
    return db[MONGO_ACCOUNT_COLLECTION].find_one({MONGO_SID_FIELD: sid}, _ACCOUNT_PROJECTION)


def _aggregate_stats(db, user_id) -> dict | None:
    proj = {f: 1 for f in (*_STAT_SUM_FIELDS, *_STAT_MAX_FIELDS)}
    rows = list(db["user.stats"].find({"userId": user_id}, proj).limit(500))
    agg = {f: 0 for f in (*_STAT_SUM_FIELDS, *_STAT_MAX_FIELDS)}
    for row in rows:
        for f in _STAT_SUM_FIELDS:
            v = row.get(f)
            if isinstance(v, (int, float)):
                agg[f] += v
        for f in _STAT_MAX_FIELDS:
            v = row.get(f)
            if isinstance(v, (int, float)) and v > agg[f]:
                agg[f] = v
    agg["rows"] = len(rows)
    return agg


# Outcome words we recognise inside provider responses. Anything else is treated
# as an opaque blob and NEVER surfaced (live 2026-07-07: `response` on Apple
# purchases is the full signed JWS receipt incl. certificate chain — thousands
# of chars of base64 that must not reach the chat).
_STATUS_TOKEN_RE = re.compile(
    r"\b(succe(?:ss|ssful|eded)|completed|failed|failure|declined|refunded|"
    r"pending|cancel(?:led|ed)|expired)\b", re.I)
_SHORT_VALUE_RE = re.compile(r"[\w .:-]{1,24}$")


def _short_status(d: dict) -> str | None:
    """Human-safe outcome for one transaction: a recognised token from
    `response`/`type`, or a short clean value — never a raw blob."""
    for cand in (d.get("response"), d.get("type")):
        if cand is None:
            continue
        s = str(cand).strip()
        if not s:
            continue
        m = _STATUS_TOKEN_RE.search(s[:2000])
        if m:
            return m.group(1).lower()
        if _SHORT_VALUE_RE.fullmatch(s):
            return s
    return None


def _txn_summary(db, user_id) -> dict | None:
    docs = list(
        db["user.transaction"]
        .find({"userId": user_id}, _TXN_PROJECTION)
        .sort("purchasedTime", -1)
        .limit(_TXN_SCAN_LIMIT)
    )
    real = []
    systems = set()
    for d in docs:
        system = _get_path(d, "pricingOption.paymentSystem")
        if not system:
            continue  # paymentSystem set = real money (SPEC-08 §6); unset = soft currency
        dt = _to_dt(d.get("purchasedTime"))
        # Probe-confirmed names: product = actualPrice.productId (fallback offerId);
        # amount/currency from actualPrice. Outcome: see _short_status().
        product = _get_path(d, "actualPrice.productId") or d.get("offerId")
        status = _short_status(d)
        amount = _get_path(d, "actualPrice.amount")
        currency = _get_path(d, "actualPrice.currency")
        qty = d.get("orderQuantity")
        real.append({
            "date": dt.date().isoformat() if dt else None,
            "payment_system": str(system),
            "product": str(product) if product is not None else None,
            "status": str(status) if status is not None else None,
            "amount": (f"{amount:g} {currency}" if isinstance(amount, (int, float))
                       and currency else None),
            "qty": qty if isinstance(qty, int) and qty > 1 else None,
            "_dt": dt,
        })
        systems.add(str(system))
    dts = [t["_dt"] for t in real if t["_dt"]]
    summary = {
        "real_money_count": len(real),
        "first_purchase": min(dts).date().isoformat() if dts else None,
        "last_purchase": max(dts).date().isoformat() if dts else None,
        "payment_systems": sorted(systems),
        "recent": [{k: v for k, v in t.items() if k != "_dt"} for t in real[:_RECENT_TXNS]],
        "scanned": len(docs),
    }
    summary["_last_dt"] = max(dts) if dts else None
    return summary


def _payer_tier(last_purchase_dt: datetime | None) -> str:
    """ACTIVE <=30d, DORMANT <=90d, LAPSED >90d since last real-money purchase, NONE never."""
    if last_purchase_dt is None:
        return "NONE"
    days = (datetime.now(timezone.utc) - last_purchase_dt).days
    if days <= 30:
        return "ACTIVE"
    if days <= 90:
        return "DORMANT"
    return "LAPSED"


def _report_count_90d(db, user_id) -> int:
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=90)
    coll = db["user.reported"]
    n = coll.count_documents({"reportedUser": user_id, "createTime": {"$gte": cutoff_dt}})
    if n == 0:
        # createTime may be stored as epoch millis rather than a BSON date -- a
        # $gte-datetime filter silently matches nothing in that case, so retry
        # with a millis cutoff before trusting the zero.
        n = coll.count_documents(
            {"reportedUser": user_id, "createTime": {"$gte": int(cutoff_dt.timestamp() * 1000)}}
        )
    return n


def _banned_device_overlap(db, device_ids: list) -> bool:
    if not device_ids:
        return False
    return db["banned.device"].count_documents({"_id": {"$in": device_ids}}) > 0


def get_player_context(sid: str) -> PlayerContext | None:
    """Resolve a SID to a full PlayerContext, or None if the SID doesn't exist /
    Mongo is unavailable. Best-effort per source, never raises."""
    sid = (sid or "").strip().upper()
    if not SID_RE.match(sid):
        return None

    now = time.time()
    hit = _cache.get(sid)
    if hit and hit[0] > now:
        return hit[1]

    db = _db()
    if db is None:
        return None

    try:
        acc = _account(db, sid)
    except Exception as e:
        print(f"[warn] player_context: account lookup failed for {sid} ({e!r})")
        return None
    if not acc:
        _cache[sid] = (now + CACHE_TTL_SECONDS, None)
        return None

    matches = acc.get("matchesPlayed")
    if matches is None:
        matches = acc.get("matchesCount")
    if matches is None:
        matches = _get_path(acc, "stats.matchesPlayed")

    device_ids = []
    for ud in acc.get("userDevices") or []:
        did = _get_path(ud, "device.deviceId") if isinstance(ud, dict) else None
        if did:
            device_ids.append(did)

    state = str(acc.get("state") or "")
    ctx = PlayerContext(
        sid=sid,
        user_id=acc.get("_id"),
        nickname=_nickname_str(acc.get("nickname")),
        state=state,
        level=acc.get("level"),
        matches_played=matches,
        create_time=_to_dt(acc.get("createTime")),
        location=acc.get("location"),
        build_version=acc.get("buildVersion"),
        chat_banned=bool(acc.get("chatBanned")),
        email=_get_path(acc, "email.id"),
        device_ids=device_ids,
        is_banned=state in BANNED_STATES,
    )

    # Each enrichment source degrades independently (SPEC-08 §6).
    try:
        ctx.stats = _aggregate_stats(db, ctx.user_id)
    except Exception as e:
        print(f"[warn] player_context: user.stats lookup failed for {sid} ({e!r})")

    try:
        txn = _txn_summary(db, ctx.user_id)
        ctx.payer_tier = _payer_tier(txn.pop("_last_dt", None))
        ctx.transactions = txn
    except Exception as e:
        print(f"[warn] player_context: user.transaction lookup failed for {sid} ({e!r})")

    try:
        ctx.report_count_90d = _report_count_90d(db, ctx.user_id)
    except Exception as e:
        print(f"[warn] player_context: user.reported lookup failed for {sid} ({e!r})")

    try:
        ctx.banned_device_overlap = _banned_device_overlap(db, device_ids)
    except Exception as e:
        print(f"[warn] player_context: banned.device lookup failed for {sid} ({e!r})")

    _cache[sid] = (now + CACHE_TTL_SECONDS, ctx)
    return ctx


def clear_cache():
    """Test hook / manual reset."""
    _cache.clear()
