"""Seed the SupportKB playbook -- 14 evergreen articles covering the typical
PrimeRush support cases, each with approved player-facing phrasing grounded in
PLAYER_DATA_MAP.md (what support can actually see and do): purchases are
verifiable per-SID; refunds happen at the Apple/Google/XSolla store, never
in-game; restores happen via support grants; ban reasons live in the audit
remarks and appeals go to Fair Play review; guest accounts without a linked
login can't be recovered on a new device.

Idempotent / safe to re-run:
- an article whose exact title already exists in kb_articles (any status) is
  SKIPPED -- never duplicated, never overwritten, so team edits in SupportKB
  always win;
- skipped rows whose embedding is still NULL get it backfilled, which makes
  re-running this script the (re)indexing mechanism too.

Seeded with status='published' (they are safe/policy-free) and tags 'playbook'
so the team can filter and review them in the SupportKB tab.

Embedding note: articles are embedded + vec-indexed at insert time via the same
embeddings.embed()/vectorstore.upsert() pair the dashboard's KB editor uses --
but ONLY when real fastembed embeddings are available. If fastembed can't load
(offline sandbox), the embedding column is left NULL: both retrieval paths skip
NULL-embedding rows, so a non-semantic hash vector never poisons Tier-2
retrieval. Finish by re-running this script once on the server (Railway), where
fastembed works -- it will backfill the missing embeddings and vec rows.

Usage:
    python -m scripts.seed_support_playbook
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db, embeddings, vectorstore

PLAYBOOK_TAG = "playbook"
PLAYBOOK_SOURCE = "playbook-seed"

# (title, category, symptom -- how players phrase it, answer -- approved phrasing)
PLAYBOOK = [
    {
        "title": "Purchase charged but item not received",
        "category": "Payments & Purchases",
        "symptom": ('"I was charged but my gems never arrived" / "Money left my '
                    'account and I got nothing in game" / "Bought the pack, no '
                    'items showed up"'),
        "answer": (
            "Sorry about that — let's get it checked properly. Every completed "
            "purchase is recorded on your account, so with your SID (the "
            "8-character code on your profile page) we can see exactly what "
            "reached your account and when. If a purchase you were charged for "
            "does not appear there, it didn't reach the game servers — please "
            "don't buy it again. Share your SID, which store you paid through "
            "(Apple, Google, or the webstore), the approximate date, and the "
            "store receipt or order number if you have it, and we'll escalate it "
            "so the team can verify the charge and restore the missing items to "
            "your account."),
    },
    {
        "title": "Charged twice for the same purchase",
        "category": "Payments & Purchases",
        "symptom": ('"I got billed twice for one purchase" / "There are two '
                    'charges on my card for the same pack" / "Double charged"'),
        "answer": (
            "Let's verify what actually happened first. Using your SID we can "
            "check the purchases recorded on your account: if two separate "
            "purchases completed, both sets of items should be on your account; "
            "if only one is recorded but you see two charges, one of them didn't "
            "reach the game. Either way, money itself is handled by the store "
            "you paid through (Apple, Google, or XSolla for the webstore) — "
            "refunds for duplicate charges are issued there, not inside the "
            "game. Share your SID and the store receipts for both charges and "
            "we'll flag it for the team to verify and guide the next step."),
    },
    {
        "title": "How to request a refund",
        "category": "Payments & Purchases",
        "symptom": ('"I want my money back" / "How do I get a refund for my '
                    'purchase?" / "Refund please, I bought it by mistake"'),
        "answer": (
            "Refunds are processed by the store you paid through, not inside the "
            "game — there's no refund button on our side. If you paid through "
            "the Apple App Store, request it at reportaproblem.apple.com; for "
            "Google Play, use your order history in the Play Store; for webstore "
            "purchases, use the XSolla receipt email or XSolla support. Each "
            "store decides refunds under its own policy, so we can't promise an "
            "outcome — but if something went wrong with the purchase itself "
            "(wrong item, item never delivered), tell us your SID and what "
            "happened and we'll check your account and flag it for the team."),
    },
    {
        "title": "Webstore (XSolla) purchase not showing up in game",
        "category": "Payments & Purchases",
        "symptom": ('"I bought from the webstore and got nothing in game" / '
                    '"My XSolla payment went through but no items" / "Webstore '
                    'order missing"'),
        "answer": (
            "Webstore purchases are delivered to the game account whose player "
            "ID was entered at checkout, and completed ones are recorded on your "
            "account just like store purchases — so first, double-check the SID "
            "you used at checkout matches the account you're playing on. Share "
            "your SID and the XSolla order number or receipt email and we'll "
            "check what's recorded: if the purchase completed but the items "
            "aren't on your account, the team can verify it and restore what's "
            "missing. Please don't purchase it again in the meantime."),
    },
    {
        "title": "Lost a guest account or moved to a new device",
        "category": "Account & Login",
        "symptom": ('"I got a new phone and my progress is gone" / "I played as '
                    'a guest and lost my account" / "How do I move my account to '
                    'my new device?"'),
        "answer": (
            "Guest accounts live on the device they were created on — they have "
            "no login attached, so if the account was never linked to Google or "
            "Apple, we unfortunately can't recover it on a new device. If you "
            "still have the old device, open the game there first and link the "
            "account (Settings > Account > link Google or Apple), then sign in "
            "with that same login on the new device and your progress comes "
            "with you. If the old device is gone and the account was linked, "
            "just sign in with the linked login. And if you're playing now: "
            "please link your account today — it takes a minute and makes your "
            "progress recoverable forever."),
    },
    {
        "title": "Linking your account (and why it matters)",
        "category": "Account & Login",
        "symptom": ('"How do I link my account?" / "I can\'t log in after '
                    'reinstalling" / "How do I save my progress?"'),
        "answer": (
            "Linking attaches your progress to a Google or Apple login so it "
            "survives reinstalls and device changes: open Settings > Account in "
            "the game and choose Google or Apple to link. If you can't log in "
            "after a reinstall, make sure you're signing in with the exact same "
            "provider and address you linked originally — picking a different "
            "Google account creates a fresh profile instead of restoring yours. "
            "Still stuck? Share your SID (or your in-game name with its number "
            "tag) and we'll check which login your account is linked to."),
    },
    {
        "title": "Forgot which login your account uses",
        "category": "Account & Login",
        "symptom": ('"I don\'t remember if I used Google or Apple" / "Which '
                    'email is my account on?" / "I have three Google accounts '
                    'and no idea which one I linked"'),
        "answer": (
            "We can help you figure it out. If you can share your SID (the "
            "8-character code on your profile page) — or, if you're locked out, "
            "your exact in-game name with its number tag — we can look up the "
            "account and tell you which provider it's linked to (Google or "
            "Apple) and confirm a masked version of the registered email, like "
            "jo***@gmail.com, so you know which login to try. We never show or "
            "change the full email in chat; if the account turns out not to be "
            "linked at all, see the guest-account article — and link it as soon "
            "as you're back in."),
    },
    {
        "title": "Account banned — why it happens and how to appeal",
        "category": "Bans & Fair Play",
        "symptom": ('"Why was I banned?" / "My account is suspended and I did '
                    'nothing wrong" / "How do I appeal my ban?"'),
        "answer": (
            "Account restrictions are applied after our Fair Play checks, and "
            "the specific reason is recorded in the moderation notes on your "
            "account — the review team reads those notes directly, so you don't "
            "need to guess or prove what happened. To appeal, share your SID and "
            "your side of the story (including if you believe someone else "
            "accessed your account) and it goes to the Fair Play team, who "
            "review every appeal individually and follow up. Support chat can't "
            "reverse a ban or promise an outcome — the review team makes that "
            "call after looking at the account's actual history."),
    },
    {
        "title": "Chat banned — muted in game",
        "category": "Bans & Fair Play",
        "symptom": ('"I can\'t talk in game anymore" / "Why am I muted?" / "My '
                    'chat is blocked but I can still play"'),
        "answer": (
            "A chat restriction is separate from an account ban — your account "
            "can be in perfectly good standing while chat is limited, usually "
            "after reports about messages or voice. These restrictions are "
            "typically temporary and are reviewed by the team. If you think "
            "yours was a mistake, share your SID and we'll add it to the case "
            "for a human to double-check; in the meantime you can keep playing "
            "normally, and keeping things civil once chat returns is the surest "
            "way to keep it."),
    },
    {
        "title": "Reporting a cheater",
        "category": "Bans & Fair Play",
        "symptom": ('"There\'s a hacker in my match" / "How do I report someone '
                    'for cheating?" / "This player is flying/aimbotting"'),
        "answer": (
            "Thank you for reporting — it genuinely helps. The best way is the "
            "in-game report on the player's profile or the end-of-match screen, "
            "picking the closest reason (cheating, abusive voice, offensive "
            "name, griefing): in-game reports attach the right match and player "
            "automatically and are counted and reviewed by the Fair Play team. "
            "If something was extreme, you can also tell us here what happened "
            "and in which match. One thing to set expectations on: we can't "
            "share what action was taken against another player's account — "
            "but every report lands with the review team."),
    },
    {
        "title": "Missing currency or item from your inventory",
        "category": "Gameplay & Progression",
        "symptom": ('"My credits disappeared" / "A skin I owned is gone from my '
                    'inventory" / "I\'m missing currency I earned"'),
        "answer": (
            "We can check this properly — your wallet balances and your full "
            "inventory (weapons, skins, cards, frames) are visible to support "
            "per account. Share your SID, what's missing, and roughly when you "
            "last had it. Two quick things worth ruling out first: currency "
            "spends (a purchase in the shop) and time-limited items, which "
            "expire by design — see the separate article on those. If something "
            "you earned or bought is verifiably missing from your account, the "
            "team can restore it with a support grant."),
    },
    {
        "title": "Skin or item disappeared (time-limited items)",
        "category": "Rewards & Events",
        "symptom": ('"My skin vanished after a few days" / "The weapon I got '
                    'from the event is gone" / "Why did my item expire?"'),
        "answer": (
            "Some rewards and event items are time-limited — they come with an "
            "expiry date and are removed automatically when it passes, which is "
            "the most common reason an item 'disappears'. Item trials and "
            "rental-style event rewards work this way; the item screen shows a "
            "timer while you hold them. If you share your SID and the item "
            "name, we can check whether it was time-limited and when it "
            "expired. If it turns out the item was NOT time-limited and is "
            "still missing, that's a real problem and we'll flag it for the "
            "team to investigate and restore."),
    },
    {
        "title": "Game crashing, lagging, or won't start",
        "category": "Technical Issues",
        "symptom": ('"The game crashes on startup" / "Constant lag, unplayable" '
                    '/ "Stuck on the loading screen"'),
        "answer": (
            "Let's run the quick fixes first: update the game to the latest "
            "version from your store (most crash waves are fixed in updates), "
            "restart your device, make sure you have a few GB of free storage, "
            "and try a different network (Wi-Fi vs mobile data) to separate lag "
            "from crashes. If it still misbehaves, tell us your SID, device "
            "model, and what exactly happens and when — we can see which game "
            "version your account last played on, which helps the team "
            "reproduce it. Nothing about your account or progress is lost "
            "during crashes; it's all saved server-side."),
    },
    {
        "title": "Finding your SID (player ID)",
        "category": "General",
        "symptom": ('"Where do I find my player ID?" / "What\'s my SID?" / '
                    '"Support asked for an 8-character code, where is it?"'),
        "answer": (
            "Your SID is the 8-character code of capital letters and digits "
            "(like AB12CD3E) shown on your profile page in the game — open your "
            "profile from the main screen and it's right there. It's how "
            "support securely finds YOUR account (names can repeat; the SID "
            "can't), and it's safe to share with official support. If you can't "
            "type it out, a screenshot of your profile or settings screen works "
            "too — we can read it from there."),
    },
]


def main() -> int:
    assert len(PLAYBOOK) == 14
    for art in PLAYBOOK:
        assert art["category"] in config.KB_CATEGORIES, art["title"]

    db.init_db()
    vectorstore.ensure_vec_table("kb_articles")
    conn = db.get_conn()
    fallback = embeddings.is_using_fallback()

    created = skipped = reindexed = 0
    for art in PLAYBOOK:
        row = conn.execute("SELECT id, embedding FROM kb_articles WHERE title = ?",
                           (art["title"],)).fetchone()
        if row:
            # Never duplicate or overwrite (team edits win). But a NULL embedding
            # means a previous run couldn't index -- backfill it now if we can.
            if row["embedding"] is None and not fallback:
                vectorstore.upsert("kb_articles", row["id"],
                                   embeddings.embed(f"{art['title']}\n{art['symptom']}"))
                reindexed += 1
                print(f"[info] re-indexed existing article: {art['title']}")
            else:
                print(f"[info] exists, skipping: {art['title']}")
            skipped += 1
            continue
        with db.tx() as c:
            cur = c.execute(
                "INSERT INTO kb_articles (title, symptom, answer, tags, status, "
                "category, source) VALUES (?, ?, ?, ?, 'published', ?, ?)",
                (art["title"], art["symptom"], art["answer"], PLAYBOOK_TAG,
                 art["category"], PLAYBOOK_SOURCE),
            )
            article_id = cur.lastrowid
        if fallback:
            print(f"[info] created (NOT indexed -- no fastembed): {art['title']}")
        else:
            vectorstore.upsert("kb_articles", article_id,
                               embeddings.embed(f"{art['title']}\n{art['symptom']}"))
            print(f"[info] created + indexed: {art['title']}")
        created += 1

    print(f"\n[info] done. created={created} skipped={skipped} reindexed={reindexed} "
          f"(tag '{PLAYBOOK_TAG}', status 'published')")
    if fallback:
        print("[warn] fastembed unavailable -- embeddings were left NULL so junk "
              "vectors never enter retrieval. Re-run this script on the server "
              "(where fastembed works) to backfill embeddings + vec index; until "
              "then Tier-2 retrieval won't see the new articles.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
