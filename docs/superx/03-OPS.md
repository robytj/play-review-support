# SuperX — 03 · ops.superx.gg (the operator side)

The other side of the app: where support agents and store operators work, for every game.

## 1 · Sign-in and roles

- Google sign-in limited to staff domains — the pattern GameGateway already uses
  (`ADMIN_GOOGLE_ALLOWED_DOMAINS`). Every action is attributed to the staff email.
- Roles: **agent** (chats, tickets), **lead** (+ approvals, KB, personas), **store ops**
  (+ store operations for assigned games), **admin**.
- Starts as the responder (Flask, Railway) on a new domain; modules move as they're rebuilt.

## 2 · Inbox

One queue across games and channels: concierge chats, store `/support`, Discord, email,
Freshdesk, and **app-store reviews** (the responder's original job).

- Filters: game/app, channel, status, priority, assignee, overdue, language.
- Priority and SLA as today (SPEC-09): payers auto-P1; P1 4 h, P2 12 h, P3 24 h, P4 72 h.
- Each item opens with the **player card**: SuperX account, linked games, proof level,
  purchases and delivery status, open tickets, ban state — staff see vendors and amounts.
- **Suggested next step** from the KB and the action list ("Order not delivered — re-deliver?"
  with one button), and the persona's drafted reply to approve or edit.
- Review replies: drafted in the game's voice, approved and posted from the same queue.

## 3 · Live

- Every live conversation with a status dot (live / idle / ended) and what the player is
  asking right now (one line, from the intent record).
- **Watch** any conversation in real time; **Take over** with one click; **Hand back** to
  the concierge. Already built (SPEC-08 takeover); carries over.
- Alerts when a conversation turns angry, mentions a payment problem, or the concierge
  hands off.
- Approvals queue: actions the concierge proposed but can't do alone (refunds, currency).

## 4 · Store ops, per game

The reason to put this here: one place to run every store, using the same APIs the stores
use (04 §2).

| Module | Source today |
|---|---|
| Game availability and maintenance messages | GameGateway Edge Config (`/v1/apps/{appId}/api-status`); superx-tc maintenance mode |
| Featured offers and catalog | superx-tc `games/*` config and `/api/store/featured`; Prime Rush offers |
| Coupons: budgets, rules, support coupons | `COUPONS_CONFIG`, coupon ledgers |
| Deliveries that failed | fulfil-retry queue (superx-tc cron), Prime Rush grant failures |
| Refunds flagged for review | MaskGun clawback `review: true`; refund webhooks |
| Player lookup and grants (audited) | game admin APIs |
| Store health | conversion, failed payments, delivery lag — per app, per day |

Changes go through the same audit trail as tickets.

## 5 · Reports: what players want

Every player message produces an **intent record** (04 §4). From them:

- **Daily digest per game** written by an LLM: top asks, new or growing issues with counts,
  three verbatim quotes, sentiment, and what the concierge couldn't answer. Posted to ops,
  Slack and Zero.
- **Spike alerts:** an intent at 3× its baseline in an hour (e.g. "item not delivered" on
  MaskGun) pages store ops — usually it's a fulfilment or backend problem before anyone files
  a bug.
- **Gaps:** questions answered from no KB article → a weekly list of articles to write,
  per game.
- Weekly: automation rate, first-reply time, time to resolve, ratings, takeover rate, cost per
  conversation, per game and per persona.

## 6 · Knowledge and personas

- KB per game (shared articles for account and payments), with the gaps list from §5.
- Persona cards (02 §4): edit voice, palette, lines; preview a test conversation; see the
  eval scores before publishing.

## 7 · Also here

The responder's existing tools stay, staff-only, under "Game ops": Cheaters, Match Analyzer,
Weapon Meta, Weapon Config, Diagnostics.
