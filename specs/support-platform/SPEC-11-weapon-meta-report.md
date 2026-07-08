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

## 3. Defaults taken (flag if wrong)

1. **"Round" = one match.** Within-match phase split (early/mid/late by hit tick vs
   match duration) is a v2 column set.
2. **Modes**: `br` is the headline grid; `brRebirth`/`easyBR`/`tdm` available via flag,
   each its own grid. `tutorial*`, `ftue`, `training`, `freeRoam` always excluded.
3. **Season** = date window (`--days`, default 30) **split by buildVersion** — patch
   boundaries never blend. Mongo `seasonId` attribution is v2.
4. **Guns only** (`gun_*` ids); melee/grenades behind `--all-weapons`.
5. **Exclusions**: `isBot` players, matches < 2 min, players with 0 hits;
   cheater exclusion v1 = none (small %, noted), v2 = banned + hacker-score cohort.
6. **Skill banding** v1 = winners (teamRank 1) vs all; v2 = Mongo MMR bands.

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
