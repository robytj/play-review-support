# Player Data Map — brx_main Mongo → player content → support usage

*Source of truth: IndusAdminUi source (github.com/JuneSoftware/IndusAdminUi) analyzed
2026-07-07, cross-checked against a live probe of 8 sample SIDs. This is the reference
for support agents AND for the Support Chat Agent (`app/player_context.py`). The admin
panel (`admin.brx.indusgame.com/player/<SID>`) reads the same data via IndusAPI.*

## 1. Identity & account (`account` collection)

| Mongo field | Meaning | Support usage |
|---|---|---|
| `_id` (int) | userId — joins every other collection | internal key; equals the Amplitude id |
| `shortId` | **SID** — what players read from their profile | the universal lookup key |
| `nickname {local, tag, value}` | display name; `value` = unique name+tag (e.g. `QuenteCapitão4497`) | confirm identity with `value` |
| `state` | account state | see enum below |
| `chatBanned` (bool) | chat ban — independent of `state` | chat-ban appeals are separate from account bans |
| `email.id` | registered email (absent on guests) | fallback lookup; mask when displayed |
| `level`, `xp`, `rank` | progression; deep rank via `rank.stats.mrank` (MMR) | recognition; progression complaints |
| `matchesPlayed` | lifetime games (fallbacks: `matchesCount`, `stats.matchesPlayed`) | recognition ("played N games") |
| `createTime` / admin "firstLogin" | account age | recognition ("with us since …") |
| `location.countryCode` | region (MX/BR/CO… on LatAm SKU) | language hints, regional pricing questions |
| `buildVersion` / admin `version` | client version | bug triage |
| `userDevices[].device.{deviceId,type}` | device history (`apple`→iOS, `android`) | device-ban overlap, multi-device questions |
| `socials[].{provider,socialId}` (via API) | linked login (google/apple) | guest vs linked — account recovery cases |
| `currencies` (map `currencyId → amount`) | wallet; names resolve via `/configs/currency` (e.g. Indus Credits) | missing-currency claims |
| `inApp.total` (API aggregate) | **lifetime real-money spend** | payer recognition; never quote the number to players |
| `owned[] {id, name, elements{elementId→name}}` | inventory by category (`weapon`, `profile.avatar`, `profile.userprofile.frame/portrait`, `profile.callingcard.*`) | missing-item claims: names come from `elements` values |
| `timeLimitedItems {elementId → expiryEpoch}` | rentals/timed items | "my skin disappeared" = check expiry first |
| `tags` (e.g. `suspicious`) | moderation flags | internal only |
| `group` | `player, user, admin, internalTester, externalTester, moderator, creator` | creators/testers get white-glove routing |

**Account state enum** (`Admin.AccountState`; raw Mongo uses PascalCase, the player-detail
API lowercases): `Active`, `Verified` (linked account), `Guest` (no linked login),
`Unverified`, `Suspicious` (flagged), `Locked`, `Suspended` (temporary), `Banned`,
`Deleted`. **Banned set = Locked/Suspended/Banned** (env `BANNED_STATES`; compare
case-insensitively). Admin ban actions collapse to `state="locked"` in places.

## 2. Purchases (`user.transaction`, `purchase.aggregated`, `topspender.*`)

- **Only completed purchases are stored.** Failed payments live in a separate system
  today (planned to be imported later). Absence of a charged purchase ⇒ escalate.
- Real money = `pricingOption.paymentSystem` set. Values: `Apple`, `Google`,
  `GoogleSubscription`, `XSollaWebshop` (webstore!). Player-facing labels: Apple /
  Google / XSolla.
- Per-transaction fields: `purchasedTime`, `transactionId`, `offerId`,
  `actualPrice.{amount,currency,productId}`, `standardPrice.*` (pre-discount),
  `orderQuantity`, `type` (`inApp`/`webShop`/`inGame`), `creatorId` (creator code!),
  `isRefunded` + `refundedTime`, `response` (raw provider receipt — **never show**),
  `paymentProof`, `deviceDetails.*`.
- **`rewards[]` inner keys: `id`, `name`, `url` (image), `quantity`, `rarity`.**
  `name` is the human description of what the purchase contained (the admin shows
  these backend-resolved; raw Mongo docs carry at least `id` — names resolve from the
  offer/config layer where absent).
- Product display name source: **offer config collections** (`/configs/offer`,
  `/configs/offer/productId`) — offers define `offerId`, `pricingOptions[]`,
  `rewards[]`. Reward grant types: Currency, Game Attribute (cosmetics), Gacha (crates),
  Battle Pass.
- **Top spender** = ranked by in-app real-money `total` (`POST /player/transaction/
  topspender`; fields `userId, shortId, name, total+currency, count, gamesPlayed`).
  `purchase.aggregated` holds the per-player rollup (`totalPurchasesCount`,
  `purchasesCount{InApp:n}`).
- In-game (soft-currency) purchases have no `paymentSystem`; buckets: co, cr, cs, elc,
  elp, gold, ig, llc, llp.
- Refunds are **display-only** in the admin (`isRefunded` chip + Play Console link) —
  there is no refund button; refunds happen at the store. Restores happen via grants.

## 3. Stats & matches (`user.stats`, `user.match`)

- Modes: `br, miniBr, freeRoam, training, tdm, tutorialBr, ftue, tutorial, brRebirth,
  easyBR, brx`; team modes `solo/duo/quad`.
- Raw `user.stats` rows (per mode/season): `totalKills, totalWins, totalLosses,
  totalDamage, totalHeadshotKills, longestKillStreak, matchMvpCount, totalTimeSpent,
  weaponDamageMap…`. Admin's per-mode view adds `topThreeCount, topFiveCount,
  averageDamage, headshotAccuracy, averageSurvivalTime, totalDistanceTravelled…`.
- `user.match` = per-match rows (`matchId, gameMode, teamMode, region, createTime,
  stats`), newest-first on `userId_1_createTime_-1`.

## 4. Moderation (`user.reported`, `banned.device`, audit)

- Report reasons enum: `voiceAbuse` ("Abusive voice"), `cheating`, `offensiveName`,
  `griefing`, `other`. Reported rows: `count`, `reasons{}`, `reportingUsers[]`,
  `lastReportedTime`.
- Ban/unban (player, chat, device) always require free-text **remarks** — there is no
  fixed ban-reason enum; the reason is whatever the operator wrote. Every action lands
  in the per-player **audit log** (`POST /player/{id}/auditlog`) — for ban appeals, the
  audit log + remarks is where "why was I banned" actually lives.
- `banned.device._id` = banned deviceIds; overlap with a player's `userDevices` is the
  device-ban signal.

## 5. Admin actions available (for "what can support actually do")

Grant cosmetics/avatars/weapons (`POST /player/avatar|weapon/{id}`), grant game
attributes (`PUT /player/{id}/game-attributes`), adjust currency (`PUT /player/{id}/
currency`, remarks required), giftables wallet (`PUT /api/players/{id}/giftables/
update`), battle-pass points/upgrade, level/xp/rank edits, rename, reset, delete,
ban/unban (player/chat/device), mark suspicious/tester, read inbox. **No refund
action** — store-side only. These are the SPEC-08 Stage-3 "guarded write" candidates;
the chat agent never calls them, it escalates with context.

## 6. How the chat agent uses this (implemented in `app/player_context.py`)

- Identity: `shortId` → confirm `nickname.value`; guests (`state=Guest`, no email)
  still fully supported.
- Recognition: tenure (`createTime`), `matchesPlayed`, best of `matchMvpCount` >
  `longestKillStreak` > `totalWins` > `totalTimeSpent`.
- **Payer thanks**: payer tier (ACTIVE ≤30d / DORMANT ≤90d / LAPSED / NONE from
  transactions) + purchase count; high payer = count ≥ `chat.high_payer_min_purchases`
  (default 20) or aggregated spend presence. Thank supporters warmly, **never quote
  amounts or totals**.
- Purchases: completed-only summary (Apple/Google/XSolla), items described by
  `rewards[].name` (fallback productId), refunded status from `isRefunded`.
- Bans: state + chatBanned + report count + device-ban overlap + payer tier → staff
  ban-assessment card; player-facing replies only from the approved `ban_response` set.
