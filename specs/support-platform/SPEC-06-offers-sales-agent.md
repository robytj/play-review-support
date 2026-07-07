# SPEC-06 — Post-resolution offers → lightweight sales agent (SuperX / Prime Market / Xfer)

*Phase P5. Depends on SPEC-05 and SuperX coupon infrastructure. This is our "Fin for
Sales/Ecommerce"-lite: support first, offer only after resolution, never during disputes.
Gated by an `offers_enabled` toggle + per-campaign switches.*

## 1. Stage A — coupons & rebates after resolved support

### Trigger policy (all must hold)
- Conversation `status='resolved'` in-session (bot-resolved or staff-resolved), **and**
  player gave 👍 or neutral on the closing CSAT prompt;
- Identified session (verified SID);
- Category is **not** payments-dispute, refund, chargeback, ban, or deletion;
- No open escalated ticket for the same SID;
- Frequency cap: 1 offer / SID / 14 days (`offer_log` table); global daily campaign cap.

### Offer mechanics
- **SuperX side (new, small)**: `coupons` table in Supabase
  (`code, sid, campaign, discount_type (pct|flat|rebate), value, expires_at, redeemed_at,
  order_id`) + two endpoints: `POST /api/coupons/issue` (server-to-server, key-gated;
  idempotent per sid+campaign) and a redemption hook at checkout that reports back.
  Rebates = post-purchase credit grant via the existing `IndusGrantRequest` path.
- **SupportBot side**: `app/offers.py` calls issue API, renders the offer card in chat
  (code + one-tap deeplink to the SuperX checkout with code pre-applied:
  `store.primerush.gg/…?coupon=<code>&sid=…`), logs to `offer_log`.
- Copy is templated per campaign (localized), never LLM-generated. Example: "Thanks for
  your patience today — here's 10% off your next Gem Pack, valid 7 days."
- **Measurement**: issue → view → tap → redeem funnel (Amplitude events + redemption
  webhook); revenue attribution via `order_id`. Dashboard panel: offers issued, redemption
  rate, attach revenue, CSAT delta.

## 2. Stage B — sales agent for Prime Market / Xfer Market (later)

When Prime Market (personalized AMM "night market") is live on SuperX:

- **Discover**: in an identified, resolved session, the agent may surface the player's
  current Prime Market slots (read-only Supabase query — personalized 1 legendary + 2 mid
  + 2 common per window) as a card carousel: "Your Prime Market refreshes in 6h — this
  week's legendary is X." Player-initiated questions about items/prices are answered from a
  **catalog KB** (auto-synced articles from the SuperX catalog: item name, price, contents
  — regenerated nightly so the bot never invents prices; Tier 0/1/2 as usual).
- **Qualify** (Fin-for-Sales pattern, mapped to F2P): simple deterministic rules over
  `PlayerContext` — spend band, pack affinity, days-since-last-purchase — choose which
  (if any) slot to highlight. No LLM scoring in v1.
- **Close**: deeplink to SuperX checkout with context carried (item, coupon if any). The
  agent never transacts in chat; checkout stays on the store (merchant-of-record, Xsolla).
- **Xfer (Transfer) Market**: out of scope until it exists; reserve `campaign='xfer_*'`
  and note P2P trading support questions (scams, escrow, disputes) will need their own KB
  category + escalate-only policy at launch.
- **Hard rules**: sales mode never activates in unresolved/negative sessions; never for
  minors-flagged accounts; respects the same frequency caps; every sales interaction logged
  as a suggestion row for review, like everything else.

## 3. Acceptance criteria

1. Coupon issued only when the full trigger policy holds (unit tests per condition);
   idempotent issuance; redemption round-trips to `offer_log`.
2. Offer card renders in chat with working pre-applied checkout deeplink.
3. Dashboard shows the offers funnel; kill switch verified.
4. Stage B behind its own toggle; catalog KB sync job produces price-accurate articles
   (spot-check test against Supabase catalog).

## 4. Agent execution notes

- SupportBot: `app/offers.py`, `offer_log`, config `offers:` (campaigns, caps, categories
  excluded), CSAT close prompt (👍/👎 already tracked in metrics — add per-conversation).
- SuperX (separate repo, coordinate with W): coupons table + issue/redeem endpoints +
  checkout coupon param; catalog read endpoint for the KB sync.
- Compliance notes: price display must respect regional pricing (Xsolla); include coupon
  terms line; keep copy honest (no fake urgency).
