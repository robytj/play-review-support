"""Deterministic, typo-tolerant support-intent detection.

Born from the 2026-07-09 regression: "i cant find my purchse" / "show my
purchases" were deflected as out-of-scope because (a) the purchase regex had no
typo tolerance and (b) the scope gate ran before the data intents. This module
is the shared fix: cheap (no LLM, no embeddings), deterministic, and used in two
places --

  - app/chat_engine.py runs has_purchase_intent()/has_ban_intent() BEFORE the
    scope gate: a verified player asking about their own account is in scope by
    definition, whatever the gate thinks.
  - app/scope_gate.py calls support_concern_category() as a veto before any
    out_of_scope/abuse deflection: if the message plainly carries a support
    concern (purchase words, ban words, crash/login/etc.), it is rescued into
    that KB category instead of being deflected.

Typo tolerance = Damerau-Levenshtein distance <= 1 (one insert, delete,
substitute, or adjacent transpose), but ONLY against a curated fuzzy-safe
subset of each lexicon: words that are long and distinctive enough that one
edit cannot turn an everyday gaming word into a match. The traps are real --
"killed" is one edit from "billed", "change" from "charge", "brought" from
"bought" -- so anything with a common 1-edit neighbor matches exactly only.
"""
from __future__ import annotations

import re

from app import llm

# ------------------------------------------------------------------- lexicons --
# Single words are token-matched: exact always, fuzzy only for the *_FUZZY sets.
# Phrases are matched as substrings, exact only.

PURCHASE_WORDS = {
    "purchase", "purchases", "purchased", "buy", "buys", "bought", "pay",
    "pays", "paid", "payment", "payments", "charge", "charged", "charges",
    "refund", "refunds", "refunded", "transaction", "transactions", "receipt",
    "receipts", "billing", "billed", "invoice", "topup", "gems", "coins",
    "diamonds", "bundle", "bundles", "subscription", "iap", "money", "purchasing",
}
# Fuzzy-SAFE only (no common 1-edit neighbors). Deliberately excluded:
# charge/charged/charges ("change/changed"), billed/billing ("killed/killing"),
# bought ("brought"), money/gems/coins/pay/buy (too short).
PURCHASE_FUZZY = (
    "purchase", "purchases", "purchased", "payment", "payments", "refund",
    "refunds", "refunded", "transaction", "transactions", "receipt", "receipts",
    "invoice", "diamonds", "subscription",
)
PURCHASE_PHRASES = (
    "top up", "top-up", "in-app", "in app purchase", "app store", "google play",
    "play store",
)

BAN_WORDS = {
    "ban", "banned", "unban", "unbanned", "banning", "suspend", "suspended",
    "suspension", "locked", "appeal", "appeals", "appealing", "restriction",
    "restricted", "muted", "chatban",
}
# Excluded from fuzzy: appeal ("appear"), locked ("looked"), banning ("banging"),
# ban/unban/muted (too short).
BAN_FUZZY = ("banned", "unbanned", "suspend", "suspended", "suspension",
             "restriction", "restricted", "chatban")
BAN_PHRASES = ("chat ban", "fair play", "account locked", "kicked out")

_FUZZY_MIN_LEN = 6
_TOKEN_RE = re.compile(r"[a-z]+")
# Real words players actually type that sit one edit from a lexicon word --
# these tokens never fuzzy-match anything ("season banner is broken" != banned).
_NEVER_FUZZY_TOKENS = {"banner", "banners"}


# ---------------------------------------------------------------- edit distance --

def _ed1(a: str, b: str) -> bool:
    """True when a and b are within ONE edit of each other (insert / delete /
    substitute / adjacent transpose). Bounded and allocation-free -- safe to run
    per token per lexicon word."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    if la == lb:
        if a[i + 1:] == b[i + 1:]:          # one substitution
            return True
        return (i + 1 < la and a[i] == b[i + 1] and a[i + 1] == b[i]
                and a[i + 2:] == b[i + 2:])  # one adjacent transpose
    return a[i:] == b[i + 1:]                # one insertion


def _match(text: str, words: set[str], fuzzy: tuple[str, ...],
           phrases: tuple[str, ...]) -> bool:
    t = (text or "").lower()
    if any(p in t for p in phrases):
        return True
    for tok in _TOKEN_RE.findall(t):
        if tok in words:
            return True
        if len(tok) >= _FUZZY_MIN_LEN - 1 and tok not in _NEVER_FUZZY_TOKENS:
            # a 5-char typo can still hit a 6-char word
            if any(_ed1(tok, w) for w in fuzzy):
                return True
    return False


# ------------------------------------------------------------------ public API --

def has_purchase_intent(text: str) -> bool:
    """'show my purchases', 'i cant find my purchse', 'was charged twice'..."""
    return _match(text, PURCHASE_WORDS, PURCHASE_FUZZY, PURCHASE_PHRASES)


def has_ban_intent(text: str) -> bool:
    return _match(text, BAN_WORDS, BAN_FUZZY, BAN_PHRASES)


def support_concern_category(text: str) -> str | None:
    """Best-effort 'is this plainly a support concern?' detector for the scope
    gate's deflection veto. Returns one of config.KB_CATEGORIES or None -- unlike
    llm.categorize_keywords() there is NO default bucket: None means 'no clear
    support signal, deflect away'. Category keyword lists are shared with the
    offline categorizer (one lexicon to maintain), extended with fuzzy matching
    and this module's purchase/ban vocabularies."""
    if has_ban_intent(text):
        return "Bans & Fair Play"
    if has_purchase_intent(text):
        return "Payments & Purchases"
    t = (text or "").lower()
    tokens = _TOKEN_RE.findall(t)
    # Keywords with common 1-edit neighbors never fuzzy-match here either
    # ("charged"/"changed", "billing"/"killing" ...) -- exact only.
    no_fuzzy = {"charged", "billing", "charge"}
    for category, keywords in llm._CATEGORY_KEYWORDS:
        for kw in keywords:
            # substring first -- SAME semantics as llm.categorize_keywords, so
            # "crash" still catches "crashes"/"crashing" like it always has
            if kw in t:
                return category
            if (" " not in kw and len(kw) >= _FUZZY_MIN_LEN and kw not in no_fuzzy
                    and any(_ed1(tok, kw) for tok in tokens
                            if len(tok) >= _FUZZY_MIN_LEN - 1
                            and tok not in _NEVER_FUZZY_TOKENS)):
                return category
    return None
