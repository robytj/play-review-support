"""Per-player 'you're actually special' highlights for the support chat.

Idea (John, 2026-07-09): when a player logs in to support, find something
genuinely unique about THEIR gameplay/tenure and compliment it -- "your longest
kill streak of 40 is top 1% of every PrimeRush player" -- and drop these lines
while the bot works on their request.

How it works, in three layers:

  1. POPULATION BASELINES (offline, cheap to read): scripts/build_player_baselines.py
     samples real accounts from brx_main (AI accounts excluded by the SPEC-11
     rule: 5-digit ids + isBot), aggregates their user.stats, and stores
     percentile quantiles per metric in the `player_baselines` SQLite table.
     Re-run weekly-ish; the chat never touches Mongo for baselines.
  2. LOGIN-TIME COMPUTE (per session): when the player's SID is verified, the
     chat engine calls compute_highlights(ctx) -- one pass over the player's own
     already-fetched context, zero extra Mongo reads -- and stores the resulting
     lines on the session meta. Best line feeds the recognition message; the
     rest are dropped one at a time as "while I check that" flavor.
  3. ELITE FALLBACK (no baselines yet): before the baselines script has ever
     run, static thresholds still produce lines for clearly-exceptional values,
     so the feature works day one and just gets sharper once percentiles exist.

Hard rules (Package A carries over): money is invisible -- no purchase counts,
amounts, or spend-derived metrics anywhere in a highlight. Facts only from the
player's own record; percentile claims only when a baseline row backs them.

Future feeds (registry is built to absorb them): per-weapon/per-mode accuracy
from the match-recorder cache (SPEC-11 weapon meta) would unlock "top 1%
accuracy with the M4 in TDM" -- plug in as new metrics with their own baselines.
"""
from __future__ import annotations

import json

from app import db

# Percentile ladder: highest quantile the value clears -> the claim we make.
_LADDER = ((99, "top 1%"), (95, "top 5%"), (90, "top 10%"), (75, "top 25%"))
_MIN_QUANTILE = 75          # below p75 a metric is not a highlight
QUANTS = (50, 75, 90, 95, 99)


# ------------------------------------------------------------ metric registry --
# value: ctx -> number|None (None = metric not computable for this player)
# line:  (value, top_pct|None) -> player-facing sentence

def _stats(ctx) -> dict:
    return ctx.stats or {}


def _v_streak(ctx):
    v = _stats(ctx).get("longestKillStreak") or 0
    return v or None


def _v_wins(ctx):
    v = _stats(ctx).get("totalWins") or 0
    return v or None


def _v_mvp(ctx):
    v = _stats(ctx).get("matchMvpCount") or 0
    return v or None


def _v_headshot_rate(ctx):
    s = _stats(ctx)
    kills, hs = s.get("totalKills") or 0, s.get("totalHeadshotKills") or 0
    if kills >= 200 and hs > 0:          # small samples make silly percentages
        return hs / kills
    return None


def _v_win_rate(ctx):
    s = _stats(ctx)
    w, l = s.get("totalWins") or 0, s.get("totalLosses") or 0
    if (w + l) >= 50:
        return w / (w + l)
    return None


def _v_hours(ctx):
    v = (_stats(ctx).get("totalTimeSpent") or 0) / 3600.0
    return v if v >= 1 else None


def _v_matches(ctx):
    return ctx.matches_played or None


METRICS = {
    # metric: (value_fn, elite_threshold_for_fallback, line_fn)
    "longest_kill_streak": (_v_streak, 30, lambda v, p: (
        f"a longest kill streak of {v:,.0f}"
        + (f" — that's {p} of every PrimeRush player" if p else " — seriously elite company"))),
    "headshot_rate": (_v_headshot_rate, 0.30, lambda v, p: (
        f"you land headshots on {v:.0%} of your kills"
        + (f" — {p} accuracy in the whole game" if p else " — sharpshooter territory"))),
    "match_mvp": (_v_mvp, 50, lambda v, p: (
        f"{v:,.0f} match MVP awards"
        + (f" — {p} of all players" if p else " — the lobby carries have been noticed"))),
    "total_wins": (_v_wins, 500, lambda v, p: (
        f"{v:,.0f} total wins"
        + (f" — {p} of the entire player base" if p else " — a serious trophy shelf"))),
    "win_rate": (_v_win_rate, None, lambda v, p: (
        f"a {v:.0%} win rate" + (f" — {p} in the game" if p else ""))),
    "hours_played": (_v_hours, 500, lambda v, p: (
        f"about {v:,.0f} hours in the arena"
        + (f" — {p} of all players by time played" if p else " — true veteran hours"))),
    "matches_played": (_v_matches, 1000, lambda v, p: (
        f"{v:,.0f} matches played"
        + (f" — more than {p.removeprefix('top ')} of players have even started"
           if p else " — dedication"))),
}


# ---------------------------------------------------------------- baselines io --

def save_baseline(metric: str, quantiles: dict, sample_n: int):
    """Upsert one metric's quantiles ({50: v, 75: v, 90: v, 95: v, 99: v})."""
    with db.tx() as c:
        c.execute(
            "INSERT INTO player_baselines (metric, quantiles_json, sample_n, computed_at) "
            "VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(metric) DO UPDATE SET quantiles_json = excluded.quantiles_json, "
            "sample_n = excluded.sample_n, computed_at = excluded.computed_at",
            (metric, json.dumps({str(k): v for k, v in quantiles.items()}), sample_n),
        )


def load_baselines() -> dict[str, dict]:
    rows = db.get_conn().execute(
        "SELECT metric, quantiles_json, sample_n FROM player_baselines").fetchall()
    out = {}
    for r in rows:
        try:
            q = {int(k): float(v) for k, v in json.loads(r["quantiles_json"]).items()}
        except (ValueError, TypeError):
            continue
        out[r["metric"]] = {"quantiles": q, "sample_n": r["sample_n"]}
    return out


def baselines_status() -> dict:
    row = db.get_conn().execute(
        "SELECT COUNT(*) AS n, MIN(computed_at) AS oldest FROM player_baselines"
    ).fetchone()
    return {"metrics": row["n"], "oldest_computed_at": row["oldest"],
            "healthy": row["n"] > 0,
            "note": None if row["n"] else
            "no baselines yet -- run scripts/build_player_baselines.py "
            "(elite-fallback highlights still active)"}


def _top_pct(value: float, quantiles: dict[int, float]) -> str | None:
    for q, claim in _LADDER:
        qv = quantiles.get(q)
        if qv is not None and value >= qv and q >= _MIN_QUANTILE:
            return claim
    return None


# ------------------------------------------------------------------ public API --

def compute_highlights(ctx, limit: int = 3) -> list[dict]:
    """Ranked unique-player facts: [{'metric','value','top_pct','line'}].
    Percentile-backed lines rank first (rarest claim wins); elite-fallback lines
    only fill in when no baseline row exists for that metric. Empty list when
    the player has nothing highlight-worthy -- never invent."""
    if ctx is None:
        return []
    baselines = load_baselines()
    scored = []
    for metric, (value_fn, elite_at, line_fn) in METRICS.items():
        try:
            v = value_fn(ctx)
        except Exception:
            v = None
        if v is None:
            continue
        base = baselines.get(metric)
        if base:
            claim = _top_pct(v, base["quantiles"])
            if claim:
                rank = {"top 1%": 4, "top 5%": 3, "top 10%": 2, "top 25%": 1}[claim]
                scored.append((rank, metric, v, claim))
        elif elite_at is not None and v >= elite_at:
            scored.append((0, metric, v, None))     # fallback: below any percentile claim
    scored.sort(key=lambda x: (-x[0], x[1]))
    out = []
    for rank, metric, v, claim in scored[:limit]:
        _, _, line_fn = METRICS[metric]
        out.append({"metric": metric, "value": v, "top_pct": claim,
                    "line": line_fn(v, claim)})
    return out
