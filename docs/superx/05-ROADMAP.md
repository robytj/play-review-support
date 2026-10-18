# SuperX — 05 · Roadmap

## Fix first (live today, independent of everything else)

| # | Problem | Fix | Owner |
|---|---|---|---|
| F1 | TC players get Prime Rush answers: towerconquest.superx.gg chat → our public `/chat`, which ignores the game | Engine reads the `[towerconquest:<lang>]` prefix, tags the app, answers from a TC KB (tickets only until it has one) | support engine |
| F2 | Public `/chat` has no key and no rate limit | Require the bearer superx-tc already sends (`SUPPORT_CHAT_SECRET`); per-IP and per-id limits; daily budget | support engine + Vercel env |
| F3 | brx-store `/ingame` doesn't verify the JWT → anyone can act as any player on shop/loja.primerush.gg | Verify signature, real session, drop `?userid` | primerush-creators |
| F4 | Service-auth key hard-coded in `app/api/redeem-code/route.ts:38` | Rotate, move to env | primerush-creators |
| F5 | Chat names payment vendors | App Store · Google Play · SuperX store | support engine |

## Phases

| Phase | Ships | Done when |
|---|---|---|
| **1 · Foundations** (2 wks) | `support.superx.gg` shell on Vercel; `ops.superx.gg` domain on the responder; engine `app_id` everywhere + keyed partner API; OpenPing monitors on what exists | both domains live; TC chat tagged and separate; monitors green |
| **2 · SuperX ID** (3–4 wks) | id.superx.gg on the Prime Rush Supabase project; `superx_links` for all five apps; launch-code exchange (MaskGun now, TC and Prime Rush when their backends add it); `.superx.gg` cookie; stores accept SuperX ID | tap Support in MaskGun → signed-in chat; same session on every `*.superx.gg` |
| **3 · Concierge v1** (3 wks) | concierge button on every superx.gg store + Hub; `/support` pages; Instinct-style UX; personas v1; read-only tools via GameGateway v2 | a proven player sees their orders and delivery status in chat on all three games |
| **4 · Actions + resolution** (3 wks) | re-deliver, equip, claim, coupons; approvals queue; resolution notifications (chat → push → inbox → email); order-attached support | "my item didn't arrive" resolved end-to-end with a push, no human |
| **5 · Ops** (3 wks, overlaps) | unified inbox incl. reviews; store ops per game; intent records in Postgres; daily digests + spike alerts; persona editor + evals | operators run all stores and all support from ops.superx.gg |
| **6 · Everywhere** | redirect sign-in for primerush.gg / primerushgame.com / primerushmena.com stores; concierge there via assertion; account page with collection + purchases + tickets; offers after resolution | one account page for every game |

## Measures

Per game: automation rate (resolved without a human), first reply < 2 s, time to resolution,
rating, takeover rate, resolution notifications opened, cost per conversation, intent spikes
caught before a bug report.
