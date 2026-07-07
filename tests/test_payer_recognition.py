"""Package A: payer-aware player context (case-insensitive ban states, refund
handling, aggregated spend, supporter band) + the recognition thanks rules.
Mongo is exercised through tiny fake-driver stubs at the _txn_summary/_agg seam;
the chat flow runs through the real API surface like the rest of the suite."""
import re
from datetime import datetime, timedelta, timezone

from conftest import make_ctx
from app import chat_engine, config, llm, player_context


# ------------------------------------------------------------ fake Mongo driver --

class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def __iter__(self):
        return iter(self._docs)


class _Coll:
    def __init__(self, docs):
        self._docs = docs

    def find(self, flt, projection=None):
        return _Cursor(self._docs)

    def find_one(self, flt, projection=None):
        return self._docs[0] if self._docs else None


def _txn(days_ago: int, refunded: bool = False, product: str = "gems_500") -> dict:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    d = {"pricingOption": {"paymentSystem": "Google"},
         "purchasedTime": dt,
         "actualPrice": {"productId": product, "amount": 4.99, "currency": "USD"},
         "type": "inApp", "response": "success"}
    if refunded:
        d["isRefunded"] = True
        d["refundedTime"] = dt
    return d


# ------------------------------------------------- case-insensitive ban states --

def test_banned_state_check_is_case_insensitive():
    # raw Mongo is PascalCase; some API layers lowercase (PLAYER_DATA_MAP §1)
    for s in ("Locked", "locked", "LOCKED", "Suspended", "suspended", "Banned", "BANNED"):
        assert player_context._is_banned_state(s), s
    for s in ("Active", "active", "Verified", "Guest", "guest", "Unverified", "", None):
        assert not player_context._is_banned_state(s), s


# -------------------------------------------------------------- refund handling --

def test_refunded_txn_listed_but_excluded_from_tier_and_count():
    db_ = {"user.transaction": _Coll([_txn(5, refunded=True), _txn(120)])}
    s = player_context._txn_summary(db_, 1)
    last_dt = s.pop("_last_dt")
    assert s["real_money_count"] == 1            # the refunded one doesn't count...
    assert s["refunded_count"] == 1
    assert [r["status"] for r in s["recent"]] == ["refunded", "success"]  # ...but is listed
    # payer tier from the surviving 120d-old purchase -> LAPSED, NOT ACTIVE from
    # the 5d-old refunded one
    assert player_context._payer_tier(last_dt) == "LAPSED"
    # last_purchase mirrors the same exclusion
    assert s["last_purchase"] == (datetime.now(timezone.utc)
                                  - timedelta(days=120)).date().isoformat()


def test_all_refunded_means_no_payer_tier():
    db_ = {"user.transaction": _Coll([_txn(3, refunded=True)])}
    s = player_context._txn_summary(db_, 1)
    assert s["real_money_count"] == 0 and s["refunded_count"] == 1
    assert s["first_purchase"] is None and s["last_purchase"] is None
    assert player_context._payer_tier(s.pop("_last_dt")) == "NONE"


# ------------------------------------------------- rewards[] keys (confirmed) --

def test_reward_description_prefers_confirmed_name_and_quantity_keys():
    # confirmed inner shape (PLAYER_DATA_MAP §2): {id, name, url, quantity, rarity}
    d = {"rewards": [{"id": "weapon_ak_gold", "name": "Golden AK", "rarity": "epic",
                      "url": "https://cdn/x.png", "quantity": 2}]}
    assert player_context._txn_description(d) == "2× Golden AK"
    # id fallback when name is absent (names resolve from the offer layer)
    assert player_context._txn_description(
        {"rewards": [{"id": "gems_500", "quantity": 1}]}) == "gems_500"


# --------------------------------------------------------------- supporter band --

def test_supporter_band_thresholds():
    assert config.CHAT_HIGH_PAYER_MIN_PURCHASES == 20   # config.yaml default
    assert player_context._supporter_band(None, None) == "NONE"
    assert player_context._supporter_band(0, None) == "NONE"
    assert player_context._supporter_band(1, None) == "SUPPORTER"
    assert player_context._supporter_band(19, None) == "SUPPORTER"
    assert player_context._supporter_band(20, None) == "HIGH"
    assert player_context._supporter_band(25, None) == "HIGH"


def test_supporter_band_from_aggregated_rollup():
    # agg vouches even when the transaction source degraded to None/0
    assert player_context._supporter_band(0, {"totalPurchasesCount": 25}) == "HIGH"
    assert player_context._supporter_band(0, {"totalPurchasesCount": 3}) == "NONE"
    assert player_context._supporter_band(2, {"purchasesCount": {"InApp": 30}}) == "HIGH"
    assert player_context._supporter_band(2, {"purchasesCount": 30}) == "HIGH"


def test_supporter_band_respects_config_knob(monkeypatch):
    monkeypatch.setattr(config, "CHAT_HIGH_PAYER_MIN_PURCHASES", 3)
    assert player_context._supporter_band(3, None) == "HIGH"
    assert player_context._supporter_band(2, None) == "SUPPORTER"


def test_agg_purchases_keyed_lookup_with_id_fallback():
    doc = {"_id": 42, "total": 199.0, "currency": "USD", "totalPurchasesCount": 25}

    class _AggColl:
        def find_one(self, flt, projection=None):
            return doc if ("_id" in flt and flt["_id"] == 42) else None

    agg = player_context._agg_purchases({"purchase.aggregated": _AggColl()}, 42)
    assert agg == {"total": 199.0, "currency": "USD", "totalPurchasesCount": 25}


# ---------------------------------------------------------- recognition thanks --

def _verify(start, say, monkeypatch, ctx):
    monkeypatch.setattr(player_context, "get_player_context",
                        lambda s: ctx if (s or "").strip().upper() == ctx.sid else None)
    s = start()
    sid = s["session_id"]
    say(sid, "PrimeRush.gg (LatAm)")
    say(sid, "EDFXPT5G")
    out = say(sid, "Yes")
    assert out["state"] == "ISSUE_LOOP"
    return out


def _recognition_msg(out):
    return next(m for m in out["messages"] if m["type"] == "recognition")


def test_thanks_templates_never_leak_figures_or_forbidden_words():
    for t in (*chat_engine._THANKS_HIGH, *chat_engine._THANKS_SUPPORTER):
        assert not re.search(r"\d", t), t                       # no digits, ever
        assert not re.search(r"\b(payer|spender|vip)\b", t, re.I), t


def test_recognition_thanks_high_supporter(start, say, monkeypatch):
    # force the deterministic fallback so the appended template is asserted verbatim
    monkeypatch.setattr(llm, "phrase_recognition",
                        lambda facts: (_ for _ in ()).throw(RuntimeError("api down")))
    ctx = make_ctx(supporter_band="HIGH")
    rec = _recognition_msg(_verify(start, say, monkeypatch, ctx))
    thanks = [t for t in chat_engine._THANKS_HIGH if t in rec["content"]]
    assert len(thanks) == 1                                    # exactly one variant
    assert not re.search(r"\d", thanks[0])                     # thanks portion digit-free
    # Haiku-facing facts carry only the band word, no numbers
    assert rec["meta"]["facts"]["supporter"] == "high"


def test_recognition_thanks_supporter_band(start, say, monkeypatch):
    monkeypatch.setattr(llm, "phrase_recognition",
                        lambda facts: (_ for _ in ()).throw(RuntimeError("api down")))
    ctx = make_ctx(supporter_band="SUPPORTER")
    rec = _recognition_msg(_verify(start, say, monkeypatch, ctx))
    assert any(t in rec["content"] for t in chat_engine._THANKS_SUPPORTER)
    assert rec["meta"]["facts"]["supporter"] == "yes"


def test_recognition_omits_thanks_for_none_band(start, say, monkeypatch):
    monkeypatch.setattr(llm, "phrase_recognition",
                        lambda facts: (_ for _ in ()).throw(RuntimeError("api down")))
    ctx = make_ctx(supporter_band="NONE", payer_tier="NONE")
    rec = _recognition_msg(_verify(start, say, monkeypatch, ctx))
    assert "supporter" not in rec["meta"]["facts"]             # nothing for Haiku either
    for t in (*chat_engine._THANKS_HIGH, *chat_engine._THANKS_SUPPORTER):
        assert t not in rec["content"]
    assert "support" not in rec["content"].lower()             # no purchase mention at all


def test_recognition_omits_thanks_when_banned(start, say, monkeypatch):
    # even a HIGH supporter gets no thanks while banned -- it reads as mockery
    # in an appeal context
    monkeypatch.setattr(llm, "phrase_recognition",
                        lambda facts: (_ for _ in ()).throw(RuntimeError("api down")))
    for over in ({"state": "Locked", "is_banned": True}, {"chat_banned": True}):
        ctx = make_ctx(supporter_band="HIGH", **over)
        rec = _recognition_msg(_verify(start, say, monkeypatch, ctx))
        assert "supporter" not in rec["meta"]["facts"]
        for t in (*chat_engine._THANKS_HIGH, *chat_engine._THANKS_SUPPORTER):
            assert t not in rec["content"]


def test_supporter_thanks_variant_stable_per_session():
    ctx = make_ctx(supporter_band="HIGH")
    for sid in (1, 2, 3):
        a = chat_engine._supporter_thanks(ctx, sid)
        assert a in chat_engine._THANKS_HIGH
        assert a == chat_engine._supporter_thanks(ctx, sid)    # deterministic per id
    # and all variants are reachable across session ids
    seen = {chat_engine._supporter_thanks(ctx, i) for i in range(10)}
    assert seen == set(chat_engine._THANKS_HIGH)


# ------------------------------------------------- purchase reply shows refunds --

def test_purchase_reply_marks_refunded_entries(start, say, monkeypatch):
    tx = {"real_money_count": 1, "refunded_count": 1,
          "first_purchase": "2026-01-01", "last_purchase": "2026-01-01",
          "payment_systems": ["Google"],
          "recent": [{"date": "2026-02-02", "payment_system": "Google",
                      "product": "gems_500", "status": "refunded"},
                     {"date": "2026-01-01", "payment_system": "Google",
                      "product": "skin_x", "status": "success"}],
          "scanned": 2}
    ctx = make_ctx(transactions=tx)
    out = _verify(start, say, monkeypatch, ctx)
    out = say(out["session_id"], "where did my purchases go?")
    text = "\n".join(m["content"] for m in out["messages"] if m["role"] == "bot")
    assert "1 purchase(s) via Google" in text
    assert "1 purchase(s) show as refunded" in text
    assert re.search(r"gems_500.*refunded", text)              # entry itself is flagged
    assert re.search(r"skin_x(?!.*refunded)", text)            # completed one is not
