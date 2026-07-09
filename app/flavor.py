"""PrimeRush flavor content: facts and jokes the chat bot drops while it works
("while I pull that up...") and highlight lead-ins for the precomputed player
compliments (app/highlights.py).

EDITABLE STARTER SET (John, 2026-07-09): these lists are deliberately plain
Python so the team can curate them in one place -- rewrite, delete, add freely.
Rules for anything that lives here:
  - No promises, no roadmap leaks, no numbers about money or other players.
  - Facts must stay TRUE (they ship verbatim); anything speculative belongs in
    a joke, where nobody expects lore accuracy.
  - Keep each line one sentence, chat-bubble sized, at most one emoji.

Selection is deterministic per session (seeded by session id) with no repeats
within a session -- the same player reloading a transcript sees the same lines.
"""
from __future__ import annotations

PRIMERUSH_FACTS = [
    # product-true facts (safe to ship as-is)
    "Your SID — the 8-character code on your profile — is unique to you and the "
    "fastest way any human or bot at PrimeRush can find your account.",
    "PrimeRush purchases land on your account server-side — if it completed, "
    "it's on your list here, no matter which store you bought through.",
    "Battle Royale and Team Deathmatch stats are tracked separately per season — "
    "your BR kill streak never dilutes your TDM record.",
    "Refunds for store purchases (Apple, Google, XSolla) are issued by the store "
    "itself — that's why support routes them there instead of in-game.",
    "The support team reads every escalated ticket — a real human, not a queue "
    "that goes nowhere.",
    "PrimeRush is built by SuperGaming — the same team that has been making "
    "multiplayer shooters played by millions for years.",
    "Every match you finish updates your season stats within moments — wins, "
    "kills, headshots, MVPs, all of it.",
    "Linking your account protects your progress — a lost phone should never "
    "mean a lost locker.",
    # team-curate candidates (true in spirit; punch them up with real numbers/lore)
    "Somewhere out there is a player on a 40+ kill streak — maybe it's you we're "
    "talking to right now.",
    "The zone doesn't hate you personally. It hates everyone equally.",
    "Season resets wipe the leaderboard, not your legend — lifetime stats stay "
    "with your account.",
    "The best drop spot is the one nobody else believes in.",
]

PRIMERUSH_JOKES = [
    "Why don't campers ever win in PrimeRush? The zone has trust issues.",
    "Why did the sniper bring a pencil to the match? To draw first blood.",
    "Our servers never skip leg day — that's why they're always up.",
    "What's a battle royale player's favorite drink? Victory Royale-tea. Sorry. "
    "Legally distinct victory tea.",
    "Why did the medkit break up with the shield? It felt used.",
    "I asked a bot why it lost the match — it said it still had a few bugs to "
    "work out.",
    "Why do PrimeRush players make terrible secret-keepers? They always drop "
    "their loot-cations.",
    "What did the zone say to the last squad outside it? 'You can run, but it's "
    "going to sting.'",
    "Why was the shotgun bad at interviews? It could never handle the range "
    "questions.",
    "My K/D ratio and my sleep schedule have one thing in common: we don't talk "
    "about either.",
    "Why did the player bring a ladder to the lobby? Heard the ranks were "
    "climbing.",
    "Respawn: the only place where 'see you in 5 seconds' is a threat.",
]

# Lead-ins the chat engine wraps around a fact/joke/highlight while it works.
LEADS = {
    "highlight": (
        "While I pull that up — had a look at your record and, honestly: ",
        "One sec, checking… meanwhile, this jumped out from your stats: ",
        "Digging into that now. By the way — ",
    ),
    "fact": (
        "While I check that — PrimeRush fact for you: ",
        "On it. Meanwhile, a PrimeRush fact: ",
        "Give me a second… PrimeRush fact while you wait: ",
    ),
    "joke": (
        "While I dig — one from the PrimeRush joke locker: ",
        "Working on it. Meanwhile: ",
        "Checking now — quick one for you: ",
    ),
}


def pick(session_id: int, used: list[str]) -> tuple[str, str, str] | None:
    """Next unused (kind, key, text) for this session, alternating fact -> joke.
    `used` is the session's list of consumed keys ("fact:3", "joke:0"). Returns
    None when both pools are exhausted (the engine just stays quiet then)."""
    used_set = set(used or [])
    n_used = len(used_set)
    order = ("fact", "joke") if n_used % 2 == 0 else ("joke", "fact")
    pools = {"fact": PRIMERUSH_FACTS, "joke": PRIMERUSH_JOKES}
    for kind in order:
        pool = pools[kind]
        if not pool:
            continue
        start = (session_id * 7 + n_used) % len(pool)
        for i in range(len(pool)):
            idx = (start + i) % len(pool)
            key = f"{kind}:{idx}"
            if key not in used_set:
                return kind, key, pool[idx]
    return None


def lead(kind: str, session_id: int, n: int) -> str:
    variants = LEADS.get(kind) or LEADS["fact"]
    return variants[(session_id + n) % len(variants)]
