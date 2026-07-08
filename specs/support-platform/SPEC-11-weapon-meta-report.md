# SPEC-11 — Weapon meta & performance grid (season baseline before balance changes)

*Requested 2026-07-08. Model: MaskGun's weapon results grid (per-weapon rounds %, K/D,
per-round kills/deaths/headshots/score + unlock/purchase columns), adapted to PrimeRush
BR telemetry. Goal: a defensible answer to "what are the most powerful weapons in the
current configuration" and a repeatable baseline to re-run after every meta change.*

## 1. Data sources (all existing, no game-client work)

| Source | What it gives |
|---|---|
| GCS `brx-match-data-prod` (`remote/player/<maj>/<min>/<patch>/<build>/<mode>/<matchId>.json`) | full match telemetry: `userSummaries[]` (per player: kills/deaths/headshots/hits/damage, `damageStatMap` keyed by weapon id, `playerRank`, `teamRank`, `isBot`), `hits[]` event log (weapon.id, isKill, distance, tick), `weaponUses[]` (trigger pulls; schema probed defensively), map/mode/teamMode/buildVersion/times |
| Mongo `user.stats` | per-player weaponDamageMap by mode+**seasonId** (season attribution) |
| Mongo `user.transaction` + `account.owned[]` | MaskGun's "purchase/unlock" columns: skin purchases per weapon line, ownership counts (v2) |
| IndusAdminUi catalog (`WeaponsImages.js` etc.) | weapon id → image + rarity; class via `gun_<class>_<nn>` convention |
| Responder anti-cheat | reusable GCS client + match parsing (`analyze_match`, `extract_user_match_metrics`), banned/hacker cohorts for exclusion |

## 2. Grid (MaskGun parity → PrimeRush)

Per weapon (rows grouped by class: AR / SMG / LMG / sniper / shotgun / pistol / …):

| MaskGun column | PrimeRush equivalent (v1 unless noted) |
|---|---|
| Rounds % | **pick rate** = player-matches where the weapon dealt ≥1 hit ÷ all player-matches |
| Rounds played | player-matches with the weapon |
| Kills:Deaths | kills with weapon ÷ deaths of its users (per-user attribution) |
| Avg kills / round | weapon kills ÷ player-matches with it |
| Avg headshots / round | HS events with weapon (if the hit event carries a HS flag; else from summary share) |
| Avg score / round | no score field in telemetry → **damage per round** stands in |
| — (new) | avg + p95 kill distance; accuracy on auto weapons (hits ÷ trigger pulls, shotgun-pellet artifact rejected as in anti-cheat); **win delta** (weapon users' top-1/top-3 rate vs baseline) |
| Unlock data / Purchase history | v2: unlock progression isn't in telemetry; purchases of weapon-line skins from `user.transaction.rewards[].id` prefix + `owned[]` counts |
| Patterns / Decals | v2: skin ownership counts from `owned[]`, rarity from catalog |

**Power score (v1 default, stated not asked):** min 500 player-rounds per weapon, then
z-score composite `0.4·pick_rate + 0.3·kills_per_round + 0.2·win_delta + 0.1·HS rate`,
reported alongside the raw columns — never instead of them.

## 3. Decisions (confirmed by John 2026-07-08)

1. **"Round" = one match.** Phase split is a possible v2 column set.
2. **Modes**: **BR and TDM as separate grids** (mode selector). `tutorial*`, `ftue`,
   `training`, `freeRoam` always excluded.
3. **Season window: since 2026-06-09** (current season start), split by buildVersion.
4. **Guns only** (`gun_*` ids).
5. **AI players**: identifiable by id length — **AI ids are 5 digits, real players 16
   digits**. Exclude by id length AND `isBot` (belt and braces).
6. **Pick rate**: match data reportedly contains picked-items telemetry — the schema
   probe must locate it; until found, pick rate = usage rate (dealt ≥1 hit), clearly
   labelled. When found, both columns: **picked %** and **used %**.
7. **Cheater exclusion: banned states + device bans + the hacker-score threshold
   cohort** (responder's cached scores).
8. **Skill banding: MMR** (`rank.stats.mrank` via Mongo) — best-effort/degradable;
   high-band (top quartile) pick rate is a first-class column when resolvable.
9. **Volume**: run a full scan first (per-day match counts since season start) to
   size sampling; then on-demand compute with **X matches/day since date** sampling.
10. **Metrics (MaskGun template)**: headline columns **K/D, Damage per match, Kills
    per game**, plus Rounds % (pick/usage), HS per round, accuracy, kill distance,
    win/top-3 delta, and the composite power score as a sort aid (raw grid is the
    product; audience = the game design team planning next season's weapon balance).

## 3a. Weapon Meta tab (responder dashboard — the delivery vehicle)

New nav tab **Weapon Meta** (admin app, next to Diagnostics), on-demand compute:

- **Controls**: mode (BR | TDM), since-date (default 2026-06-09), matches/day sample
  size, build filter (default: all builds in window, grouped in results).
- **Diagnostics panel** (per John: "set up all the diagnostics for this exercise
  under that tab"): (a) GCS volume scan — matches/day since season start per mode;
  (b) schema probe — weaponUses / damageStatMap / hit-event / picked-items discovery
  on a handful of matches, types only; (c) exclusion counts — AI players, banned,
  hacker-cohort, sub-2-min matches dropped in the last run.
- **Run** uses the responder's existing background-job pattern (like cheater scans):
  progress, cancel, results cached per parameter set.
- **Results**: MaskGun-style grid (weapon image from the bundled catalog where ids
  match, class grouping, headline K/D · Dmg/match · Kills/game), sortable columns,
  CSV export of the full grid, per-build split view.

## 4. Pipeline

- **v1 (now)**: `weapon_meta_report.py` in play-review-responder (standalone, same env
  as the service — run `railway run python3 weapon_meta_report.py --mode br --days 14
  --sample 1500`). Lists blobs under the current build's mode prefix, samples N matches,
  aggregates, prints the grid + power ranking, writes `weapon_meta_<date>.csv`, and
  emits a **schema-discovery section** (weaponUses / damageStatMap / hit-event fields)
  so the two undocumented schemas get pinned on the first real run.
- **v2**: nightly aggregation into SQLite + a **Weapon Meta** dashboard tab (grid with
  images from the catalog, filters: mode/map/build/skill band/date, per-weapon trend
  sparklines), monetization columns, phase split, MMR banding, cheater exclusion.
- **Meta-change workflow**: run before a balance patch (baseline), tag the CSV with
  buildVersion, re-run after; the tab shows both builds side by side.

## 5. Open questions (unanswered from the review round)

Matches/day volume (drives sample vs full-scan); whether loadout/carry telemetry exists
anywhere (pick rate currently = usage rate); melee/grenade inclusion; audience
(internal only vs community-shareable); nightly job vs on-demand.
