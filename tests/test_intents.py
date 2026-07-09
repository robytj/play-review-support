"""Typo-tolerant intent lexicons (app/intents.py) -- born from the 2026-07-09
regression where 'i cant find my purchse' was deflected as out-of-scope."""
from app import intents


# ------------------------------------------------------------- purchase intent --

def test_purchase_exact_and_phrases():
    for msg in ("show my purchases", "I was charged twice for gems",
                "where is my refund", "i paid for the battle pass",
                "check my google play order please", "top up failed"):
        assert intents.has_purchase_intent(msg), msg


def test_purchase_typos_from_the_incident():
    # the two literal messages from broken session #19 (+ common variants)
    assert intents.has_purchase_intent("i cant find my purchse")
    assert intents.has_purchase_intent("show my purchses")
    assert intents.has_purchase_intent("my purchace is missing")
    assert intents.has_purchase_intent("i want a refnud")
    assert intents.has_purchase_intent("paymnet went through but no gems")


def test_purchase_fuzzy_traps_do_not_fire():
    # 1-edit neighbors of lexicon words that are everyday game words
    assert not intents.has_purchase_intent("he killed me through the wall")     # ~billed
    assert not intents.has_purchase_intent("I changed my nickname yesterday")   # ~charged
    assert not intents.has_purchase_intent("the update brought new bugs")       # ~bought
    assert not intents.has_purchase_intent("in order to win, which gun?")       # 'order' removed
    assert not intents.has_purchase_intent("how do I play better")


# ------------------------------------------------------------------ ban intent --

def test_ban_intent_variants():
    assert intents.has_ban_intent("why was I banned??")
    assert intents.has_ban_intent("my account is suspnded")        # typo
    assert intents.has_ban_intent("I want to appeal my ban")
    assert intents.has_ban_intent("chat ban for no reason")
    assert not intents.has_ban_intent("the event banner looks broken")  # fuzzy-safe...
    assert not intents.has_ban_intent("I looked everywhere for the setting")


# ------------------------------------------------------- support-concern rescue --

def test_support_concern_category():
    assert intents.support_concern_category("i cant find my purchse") == "Payments & Purchases"
    assert intents.support_concern_category("why banned") == "Bans & Fair Play"
    assert intents.support_concern_category("game crashes on startup") == "Technical Issues"
    assert intents.support_concern_category("cant log in to my acount") == "Account & Login"
    assert intents.support_concern_category("write my homework essay") is None
    assert intents.support_concern_category("hello there") is None


# -------------------------------------------------------------- edit distance --

def test_ed1_primitives():
    assert intents._ed1("purchse", "purchase")     # deletion
    assert intents._ed1("purchace", "purchase")    # substitution
    assert intents._ed1("purchsae", "purchase")    # adjacent transpose
    assert intents._ed1("purchases", "purchase")   # insertion
    assert not intents._ed1("purchse", "payment")
    assert not intents._ed1("killed", "billing")
