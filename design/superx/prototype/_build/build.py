"""SuperX clickable prototype — Zero theme (zero.supertuned.ai) on SuperX.

Builds static, fully linked pages for id.superx.gg, support.superx.gg, the in-game /
store concierge, and ops.superx.gg. One stylesheet (Zero tokens; SuperX = In the Pink,
so headline periods are pink; signal orange only for alerts) inlined into every page so
files open anywhere, including previews that block external CSS.

    python3 _build/build.py        # writes pages next to _build/
Illustrative data only. Spec: docs/superx/.
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent

CSS = r"""
:root{
  --ink:#0A0A0A; --ink2:#4A4845; --ink3:#868079;
  --paper:#F7F5F1; --paper2:#EFEDE7; --card:#FFFFFF;
  --line:#E3E0DA; --line2:#D2CFC9;
  --pink:#F5308C; --signal:#FF5B2E; --green:#00C267; --okd:#079150;
  --pr:#F7C600; --tc:#7C3AED; --mg:#FFB400;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--paper);color:var(--ink);font:14px/1.45 Geist,system-ui,-apple-system,'Helvetica Neue',Arial,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit;text-decoration:none}
.app{display:grid;grid-template-columns:232px 1fr 372px;min-height:100vh}
.app.nodock{grid-template-columns:232px 1fr}
/* nav */
nav.side{background:var(--ink);color:#EDEAE4;padding:20px 14px;display:flex;flex-direction:column;gap:2px;position:sticky;top:0;height:100vh}
.brandrow{display:flex;align-items:center;gap:10px;padding:2px 8px 18px}
.blogo{width:30px;height:30px;color:#EDEAE4;flex:none}
.brand{font-weight:700;font-size:21px;letter-spacing:-.02em;line-height:1}
.brand b,h1 b,h2 b,.t b{color:var(--pink)}
.by{font:500 10px var(--mono);color:#8E8A84;letter-spacing:.06em;text-transform:uppercase;margin-top:3px}
.ask{display:flex;align-items:center;gap:8px;background:#1C1B1A;border:1px solid #2E2C2A;border-radius:10px;padding:9px 10px;margin:0 0 14px;color:#B9B4AC;font-size:13px}
.ask kbd{margin-left:auto;font:500 10px var(--mono);color:#8E8A84;border:1px solid #3A3835;border-radius:4px;padding:1px 5px}
.navh{font:500 10px var(--mono);color:#7D7972;letter-spacing:.1em;text-transform:uppercase;padding:14px 8px 6px}
.ni{display:flex;align-items:center;gap:10px;padding:7px 8px;border-radius:8px;color:#CFCAC2;font-size:13.5px}
.ni:hover{background:#1A1918}
.ni.on{background:#232120;color:#fff}
.ni .c{margin-left:auto;font:500 11px var(--mono);color:#8E8A84}
.ni .c.hot{color:var(--signal)}
.dot{width:8px;height:8px;border-radius:50%;flex:none;display:inline-block}
.navfoot{margin-top:auto;padding:12px 8px 0;border-top:1px solid #2A2826;font:500 10.5px var(--mono);color:#7D7972;line-height:1.7}
.navfoot b{color:var(--green);font-weight:500}
/* main */
main{padding:22px 28px 40px;display:flex;flex-direction:column;gap:16px;min-width:0}
.top{display:flex;align-items:flex-end;justify-content:space-between;gap:16px}
.eyebrow{font:500 11px var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--ink3)}
h1{font-size:30px;letter-spacing:-.025em;font-weight:700;line-height:1.1;margin-top:6px}
h2{font-size:18px;letter-spacing:-.02em;font-weight:700}
.crumbs{font:500 11px var(--mono);color:var(--ink3);white-space:nowrap}
.crumbs span{color:var(--ink)}
.grid{display:grid;gap:12px}
.g2{grid-template-columns:1fr 1fr}.g3{grid-template-columns:repeat(3,1fr)}.g4{grid-template-columns:repeat(4,1fr)}
.g21{grid-template-columns:1.25fr 1fr}
.bcard{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;display:block}
.bcard .k{font:500 10.5px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);display:flex;align-items:center;gap:6px}
.bcard .n{font-size:26px;font-weight:700;letter-spacing:-.02em;margin:4px 0 2px}
.bcard .s{font-size:12.5px;color:var(--ink2)}
a.bcard:hover,a.row:hover{border-color:var(--ink3)}
.panel{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.ph{display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap}
.ph .tag:first-of-type{margin-left:auto}
.tag{font:500 10.5px var(--mono);border:1px solid var(--line2);border-radius:999px;padding:2px 8px;color:var(--ink2);white-space:nowrap;display:inline-flex;align-items:center;gap:5px}
.tag.o{border-color:var(--signal);color:var(--signal)}
.tag.p{border-color:var(--pink);color:var(--pink)}
.tag.g{border-color:var(--okd);color:var(--okd)}
.tag.f{background:var(--ink);color:#fff;border-color:var(--ink)}
.summary{background:var(--paper);border-radius:10px;padding:11px 13px;font-size:13.5px}
.summary .k{font:500 10px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);display:block;margin-bottom:4px}
.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.fact{border:1px solid var(--line);border-radius:10px;padding:8px 10px}
.fact .k{font:500 10px var(--mono);letter-spacing:.06em;text-transform:uppercase;color:var(--ink3)}
.fact .v{font-size:13px;font-weight:600;margin-top:2px}
.rows{display:flex;flex-direction:column;gap:7px}
.row{display:grid;grid-template-columns:18px 1fr auto;gap:10px;align-items:center;padding:9px 11px;border:1px solid var(--line);border-radius:10px;background:var(--card)}
.row.nod{grid-template-columns:1fr auto}
.row .nm{font-weight:600;font-size:13px}
.row .nm small{font:500 10.5px var(--mono);color:var(--ink3);font-weight:500;margin-left:6px}
.row .act{font-size:12px;color:var(--ink2);margin-top:1px}
.row .st{font:500 10.5px var(--mono);color:var(--ink3);text-align:right;white-space:nowrap}
.st.ok{color:var(--okd)}.st.wait{color:var(--signal)}.st.pk{color:var(--pink)}
.ring{width:14px;height:14px;border-radius:50%;border:2px solid var(--ink);display:grid;place-items:center}
.ring i{width:6px;height:6px;border-radius:50%;display:block}
.tl{position:relative;padding-left:16px}
.tl:before{content:"";position:absolute;left:4px;top:6px;bottom:6px;width:1px;background:var(--line2)}
.ev{position:relative;padding:0 0 11px}
.ev:before{content:"";position:absolute;left:-15px;top:6px;width:9px;height:9px;border-radius:50%;background:var(--card);border:2px solid var(--ink3)}
.ev.o:before{border-color:var(--pink);background:var(--pink)}
.ev .when{font:500 10.5px var(--mono);color:var(--ink3)}
.ev .what{font-size:13px;margin-top:1px}
.src{display:inline-flex;align-items:center;gap:4px;font:500 10px var(--mono);color:var(--ink2);background:var(--paper2);border-radius:5px;padding:1px 6px;margin-left:4px;vertical-align:1px}
.bar{height:4px;background:var(--paper2);border-radius:4px;margin-top:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--ink)}
.bar.pk i{background:var(--pink)}
.btn{font:500 12px Geist,system-ui,sans-serif;border:1px solid var(--line2);background:var(--card);border-radius:8px;padding:6px 11px;display:inline-flex;align-items:center;gap:6px;cursor:pointer;white-space:nowrap}
.btn.p{background:var(--ink);color:#fff;border-color:var(--ink)}
.btn.o{border-color:var(--signal);color:var(--signal)}
.btn.pk{background:var(--pink);color:#fff;border-color:var(--pink)}
.acts{display:flex;gap:6px;flex-wrap:wrap}
table.t2{width:100%;border-collapse:collapse;font-size:13px}
table.t2 th{font:500 10px var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
table.t2 td{padding:10px;border-bottom:1px solid var(--line);vertical-align:top}
table.t2 tr:hover td{background:var(--paper)}
.mono{font-family:var(--mono);font-size:11.5px}
.muted{color:var(--ink3)}
.search{display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--line2);border-radius:12px;padding:12px 14px;font-size:14px;color:var(--ink3)}
.search kbd{margin-left:auto;font:500 10px var(--mono);border:1px solid var(--line2);border-radius:4px;padding:1px 5px}
.foot{font:500 10px var(--mono);color:var(--ink3);letter-spacing:.06em;text-align:center;margin-top:auto;padding-top:10px}
.toggle{width:30px;height:17px;border-radius:9px;background:var(--ink);position:relative;display:inline-block;vertical-align:middle;flex:none}
.toggle:after{content:"";position:absolute;right:2px;top:2px;width:13px;height:13px;border-radius:50%;background:#fff}
.toggle.off{background:var(--line2)}.toggle.off:after{left:2px;right:auto}
/* dock */
aside.dock{background:var(--card);border-left:1px solid var(--line);display:flex;flex-direction:column;position:sticky;top:0;height:100vh}
.dockh{padding:18px 18px 12px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:10px}
.dockh .t{font-weight:700;font-size:15px}
.dockh .chips{margin-left:auto;display:flex;gap:4px}
.chip{font:500 10px var(--mono);border:1px solid var(--line2);border-radius:999px;padding:2px 7px;color:var(--ink2)}
.chip.on{background:var(--ink);color:#fff;border-color:var(--ink)}
.thread{flex:1;padding:14px 16px;display:flex;flex-direction:column;gap:10px;overflow:auto}
.me{align-self:flex-end;background:var(--ink);color:#fff;border-radius:14px 14px 4px 14px;padding:9px 12px;font-size:13px;max-width:84%;position:relative}
.me .via{display:block;font:500 9.5px var(--mono);color:#9C978F;margin-top:3px;text-align:right}
.z{align-self:flex-start;background:var(--paper);border-radius:14px 14px 14px 4px;padding:10px 12px;font-size:13px;max-width:92%}
.z p+p{margin-top:6px}
.z .route{font:500 10px var(--mono);color:var(--ink3);margin-bottom:5px}
.z ul{margin:4px 0 0 16px}
.z .acts{margin-top:8px}
.react{position:absolute;bottom:-9px;left:8px;background:#fff;border:1px solid var(--line);border-radius:10px;font-size:11px;padding:0 4px;line-height:16px}
.composer{margin:0 14px 14px;border:1px solid var(--line2);border-radius:14px;padding:10px 10px 10px 14px;display:flex;align-items:center;gap:8px}
.composer .ph2{color:var(--ink3);font-size:13px;flex:1}
.send{width:36px;height:36px;border-radius:50%;background:var(--pink);display:grid;place-items:center;flex:none;color:#fff;font-size:15px}
.av{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-weight:800;font-size:13px;color:#111;flex:none}
/* phones (chat mocks, kept) */
.stage{padding:28px;display:flex;gap:28px;flex-wrap:wrap;align-items:flex-start}
.phone{width:360px;height:760px;background:#0E0E10;border:1px solid #1A1A1A;border-radius:30px;overflow:hidden;position:relative;flex:none;color:#fff}
.phone .status{height:30px;display:flex;justify-content:space-between;padding:9px 20px 0;font:500 10.5px var(--mono);opacity:.8}
.url{margin:4px 14px 0;font:500 10.5px var(--mono);padding:6px 10px;border-radius:8px;background:rgba(255,255,255,.08);display:flex;justify-content:space-between}
.chat-h{display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid rgba(255,255,255,.1)}
.chat-h .nm{font-weight:700;font-size:14px}
.chat-h .sb{font-size:11px;opacity:.65;display:flex;align-items:center;gap:6px}
.live{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--green)}
.msgs{padding:12px 12px 6px;display:flex;flex-direction:column;gap:6px;font-size:13.5px;line-height:1.42}
.b{max-width:82%;padding:8px 11px;border-radius:16px;position:relative}
.b.u{align-self:flex-end;background:#2B2B30;border-bottom-right-radius:5px}
.b.a{align-self:flex-start;background:#1C1C21;border-bottom-left-radius:5px}
.b.gap{margin-top:8px}
.b .rx{position:absolute;bottom:-9px;right:6px;background:#2B2B30;border:2px solid #0E0E10;border-radius:10px;font-size:11px;padding:0 4px;line-height:16px}
.card{align-self:flex-start;width:86%;border-radius:14px;overflow:hidden;background:#17171B;border:1px solid rgba(255,255,255,.1)}
.card .r1{display:flex;gap:10px;padding:10px;align-items:center}
.thumb{width:44px;height:44px;border-radius:8px;flex:none;background:#26262B;position:relative}
.thumb:after{content:"";position:absolute;inset:11px;border-radius:50%;background:var(--c,#888)}
.card .ft{display:flex;justify-content:space-between;align-items:center;padding:8px 10px;border-top:1px solid rgba(255,255,255,.08);font-size:11.5px}
.okt{color:#4ADE80;font:500 10.5px var(--mono);letter-spacing:.06em;text-transform:uppercase}
.steps{display:flex;gap:6px;font:500 9.5px var(--mono);letter-spacing:.06em;text-transform:uppercase;padding:0 10px 10px}
.steps span{flex:1;padding-top:6px;border-top:2px solid #444;opacity:.6}
.steps span.on{border-color:#4ADE80;opacity:1}
.quick{display:flex;gap:6px;flex-wrap:wrap;padding:4px 0}
.quick span{font-size:12px;padding:6px 10px;border-radius:999px;border:1px solid rgba(255,255,255,.25)}
.pcomp{position:absolute;left:0;right:0;bottom:0;padding:10px 12px 18px;display:flex;gap:8px;align-items:center;background:#0E0E10;border-top:1px solid rgba(255,255,255,.08)}
.pcomp .in{flex:1;border-radius:999px;padding:10px 14px;font-size:13px;background:rgba(255,255,255,.08);opacity:.8}
.note{max-width:300px;font-size:13px;color:var(--ink2);line-height:1.55}
.note h2{margin-bottom:8px}
.lockbg{position:absolute;inset:0;background:radial-gradient(120% 80% at 30% 10%,#3A2A12 0%,#0E0E10 60%)}
.clock{position:relative;text-align:center;margin-top:70px;font-size:64px;font-weight:300;letter-spacing:-2px}
.notif{position:relative;margin:14px 12px 0;background:rgba(40,40,46,.86);border-radius:18px;padding:11px 12px;display:flex;gap:10px;font-size:13px;line-height:1.35}
.notif .ic{width:32px;height:32px;border-radius:8px;flex:none;display:grid;place-items:center;font-weight:900;color:#0E0E10}
/* id */
.idwrap{min-height:100vh;display:grid;grid-template-columns:1fr 480px}
.idleft{background:var(--ink);color:#EDEAE4;padding:40px;display:flex;flex-direction:column}
.idright{padding:56px 48px;display:flex;flex-direction:column;gap:14px}
.field{display:flex;gap:8px}
.inp{border:1px solid var(--line2);background:var(--card);border-radius:10px;padding:11px 12px;font:500 13px var(--mono);flex:1;color:var(--ink2)}
.big{width:100%;justify-content:center;padding:12px;font-size:14px;border-radius:10px}
.codebox{display:flex;gap:8px}.codebox span{width:46px;height:54px;border:1px solid var(--line2);border-radius:10px;background:#fff;display:grid;place-items:center;font:600 22px var(--mono)}
/* map */
.mapgrid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.mapgrid ul{list-style:none;display:flex;flex-direction:column;gap:6px;margin-top:10px}
.mapgrid li a{font-size:13.5px;border-bottom:1px solid var(--line);display:block;padding:4px 0}
.mapgrid li a:hover{color:var(--pink)}
"""

LOGO = ('<svg class="blogo" viewBox="-50 -50 100 100" aria-hidden="true"><g stroke="currentColor" '
        'stroke-width="10" stroke-linecap="round"><line x1="-30" y1="-30" x2="30" y2="30"/>'
        '<line x1="30" y1="-30" x2="-30" y2="30"/></g><circle r="12" fill="#F5308C"/></svg>')

GAMES = {"pr": ("Prime Rush", "var(--pr)"), "tc": ("Tower Conquest", "var(--tc)"), "mg": ("MaskGun", "var(--mg)")}


def page(title, body, depth=1):
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{title}</title><style>{CSS}</style></head><body>{body}</body></html>')


def nav(product, items, active, extra="", foot=""):
    up = "../"
    links = []
    for it in items:
        if it[0] == "h":
            links.append(f'<div class="navh">{it[1]}</div>')
            continue
        _, label, href, count, dot = (list(it) + [None, None])[:5]
        cls = " on" if href == active else ""
        dothtml = f'<span class="dot" style="background:{dot}"></span>' if dot else ""
        c = ""
        if count:
            hot = " hot" if str(count).startswith("!") else ""
            c = f'<span class="c{hot}">{str(count).lstrip("!")}</span>'
        links.append(f'<a class="ni{cls}" href="{href}">{dothtml}{label}{c}</a>')
    return (f'<nav class="side"><a class="brandrow" href="{up}index.html">{LOGO}<div>'
            f'<div class="brand">SuperX<b>.</b></div><div class="by">{product}</div></div></a>'
            f'{extra}{"".join(links)}<div class="navfoot">{foot}</div></nav>')


OPS_ITEMS = [
    ("i", "Today", "index.html", None, None),
    ("i", "Live", "live.html", "14", None),
    ("i", "Inbox", "inbox.html", "38", None),
    ("i", "Approvals", "approvals.html", "!3", None),
    ("i", "Store reviews", "reviews.html", "12", None),
    ("h", "Games"),
    ("i", "Prime Rush", "inbox.html#pr", "29", "var(--pr)"),
    ("i", "Tower Conquest", "inbox.html#tc", "3", "var(--tc)"),
    ("i", "MaskGun", "inbox.html#mg", "6", "var(--mg)"),
    ("h", "Run the stores"),
    ("i", "Store ops", "store.html", None, None),
    ("i", "Reports", "reports.html", "!1", None),
    ("h", "Concierges"),
    ("i", "Characters", "concierges.html", "5", None),
    ("i", "Knowledge", "knowledge.html", "!4", None),
    ("h", "Game ops"),
    ("i", "Cheaters", "#", None, None),
    ("i", "Weapon meta", "#", None, None),
]
OPS_FOOT = 'ops.superx.gg<br><b>●</b> OpenPing · 12 checks green'
OPS_ASK = '<div class="ask">Ask ops anything…<kbd>⌘I</kbd></div>'

SUP_ITEMS = [
    ("i", "Home", "index.html", None, None),
    ("i", "Conversations", "conversations.html", "!1", None),
    ("i", "Purchases", "purchases.html", None, None),
    ("i", "Help", "help.html", None, None),
    ("i", "Account", "../id/account.html", None, None),
    ("h", "Your games"),
    ("i", "Prime Rush · LATAM", "help.html", "EDFXPT5G", "var(--pr)"),
    ("i", "MaskGun", "help.html#mg", "viper_22", "var(--mg)"),
    ("i", "Tower Conquest", "../id/account.html", "link", "var(--tc)"),
]
SUP_FOOT = 'support.superx.gg<br><b>●</b> signed in with SuperX ID'
SUP_ASK = '<div class="ask">Ask anything about your games…<kbd>⌘K</kbd></div>'


def app(navhtml, center, dock=None):
    cls = "app" if dock else "app nodock"
    d = dock or ""
    return f'<div class="{cls}">{navhtml}<main>{center}<div class="foot">PROTOTYPE · ILLUSTRATIVE DATA</div></main>{d}</div>'


def head(eyebrow, h1, crumbs=""):
    return (f'<div class="top"><div><div class="eyebrow">{eyebrow}</div><h1>{h1}<b>.</b></h1></div>'
            f'<div class="crumbs">{crumbs}</div></div>')


def dock(title, chips, thread, placeholder, foot=""):
    ch = "".join(f'<span class="chip{" on" if i == 0 else ""}">{c}</span>' for i, c in enumerate(chips))
    return (f'<aside class="dock"><div class="dockh">{title}<div class="chips">{ch}</div></div>'
            f'<div class="thread">{thread}</div>{foot}<div class="composer"><span class="ph2">{placeholder}</span>'
            f'<span class="send">↑</span></div></aside>')


# ---------------------------------------------------------------- docks
OPS_DOCK = dock(
    '<span class="av" style="background:var(--ink);color:#fff">X</span><div class="t">Ask ops<b>.</b></div>',
    ["Chat", "Slack"],
    '<div class="me">Why are MaskGun deliveries failing tonight?<span class="via">chat · 21:12</span></div>'
    '<div class="z"><div class="route">question → store ops · MaskGun · 3 sources</div>'
    '<p><b>/web/v1/purchases/fulfil</b> started timing out at 19:38. 41 orders failed delivery; '
    'Mysterio re-sent 38 from chat, 3 are waiting for you.</p>'
    '<p>GameGateway still reports MaskGun available, so players don\'t see a maintenance message.</p>'
    '<div class="acts"><a class="btn p" href="store.html">Open failed deliveries</a><a class="btn" href="reports.html">See spike</a></div></div>'
    '<div class="me">Re-send the 3 and tell the backend team.<span class="via">chat · 21:14</span></div>'
    '<div class="z"><p>Done — 3 re-sent, all landed. Posted in #maskgun-backend with the timeline.</p>'
    '<p>I\'ll watch the fulfil error rate and tell you if it climbs again.</p></div>',
    "Ask, tell, or hand off anything…")


def sup_dock(opener):
    return dock(
        '<span class="av" style="background:var(--pr)">J</span><div><div class="t">Juliana<b>.</b></div>'
        '<div class="muted" style="font-size:11px">Prime Rush · Latam Legends</div></div>',
        ["Prime Rush", "MaskGun"],
        opener,
        "Fala com a Juliana…")


JULIANA = ('<div class="z"><div class="route">proactive · season pass</div>'
           '<p>E aí, Quente! Vi que o Charme Kitsune do nível 40 ficou travado no nosso lado depois da '
           'atualização. Já mandei pra sua caixa de correio — é só resgatar quando entrar na partida.</p>'
           '<div class="acts"><span class="btn p">Valeu!</span><span class="btn">Não chegou ainda</span></div></div>'
           '<div class="me">valeu juliana<span class="react">🔥</span></div>'
           '<div class="z"><p>Tamo junto. A temporada dos Latam Legends acaba domingo — faltam 3 níveis '
           'pro Rafael. Quer que eu te avise quando liberar a missão bônus?</p>'
           '<div class="acts"><span class="btn pk">Me avisa</span><span class="btn">Agora não</span></div></div>')


def write(rel, html):
    p = OUT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(html, encoding="utf-8")


# ================================================================ ops.superx.gg
def ops_today():
    c = head("Saturday 18 Oct · ops brief", "Evening, Ana. Three things need you",
             'ops.superx.gg › <span>Today</span>')
    c += ('<div class="grid g4">'
          '<a class="bcard" href="approvals.html"><div class="k"><span class="dot" style="background:var(--signal)"></span>Needs you</div><div class="n">3</div><div class="s">Approve a refund · a currency grant · one ban appeal</div></a>'
          '<a class="bcard" href="live.html"><div class="k"><span class="dot" style="background:var(--green)"></span>Live now</div><div class="n">14</div><div class="s">Chats across 3 games, 1 handed off</div></a>'
          '<a class="bcard" href="reports.html"><div class="k">Resolved today</div><div class="n">612</div><div class="s">84% without a human · 4.6 ★</div></a>'
          '<a class="bcard" href="store.html"><div class="k"><span class="dot" style="background:var(--signal)"></span>Spike</div><div class="n">3.4×</div><div class="s">MaskGun "item not delivered" since 19:40</div></a>'
          '</div>')
    c += '<div class="grid g21">'
    c += ('<div class="panel"><div class="ph"><h2>MaskGun deliveries<b>.</b></h2><span class="tag">Store ops</span><span class="tag o">spike</span><span class="tag">owner: Ana</span></div>'
          '<div class="summary"><span class="k">What\'s true now · compiled from chats + store logs</span>The fulfil call to the MaskGun backend has been timing out since 19:38. Mysterio is re-sending failed orders from chat; 3 need a person. GameGateway still says available.</div>'
          '<div class="facts" style="margin:12px 0"><div class="fact"><div class="k">Failed</div><div class="v">41 orders</div></div><div class="fact"><div class="k">Re-sent by Mysterio</div><div class="v">38</div></div><div class="fact"><div class="k">Next step</div><div class="v">3 to re-send</div></div></div>'
          '<div class="tl">'
          '<div class="ev o"><div class="when">21:12</div><div class="what">Ana asked Ops why deliveries fail; routed to store ops <span class="src">#maskgun</span></div></div>'
          '<div class="ev"><div class="when">20:05</div><div class="what">Spike alert: "item not delivered" at 3.4× baseline <span class="src">Reports</span></div></div>'
          '<div class="ev"><div class="when">19:38</div><div class="what">First fulfil timeout on /web/v1/purchases/fulfil <span class="src">OpenPing</span></div></div>'
          '</div></div>')
    c += ('<div class="panel"><div class="ph"><h2>Concierges at work<b>.</b></h2><span class="tag">each a character from its game</span></div><div class="rows">'
          '<a class="row" href="concierges.html"><span class="ring"><i style="background:var(--pr)"></i></span><div><div class="nm">Juliana <small>Prime Rush · LATAM</small></div><div class="act">281 chats · re-sent 12 pass rewards · pt-BR</div></div><span class="st ok">4.7 ★</span></a>'
          '<a class="row" href="concierges.html"><span class="ring"><i style="background:var(--pr)"></i></span><div><div class="nm">Kaara <small>Prime Rush · Global</small></div><div class="act">96 chats · 2 handed off</div></div><span class="st ok">4.5 ★</span></a>'
          '<a class="row" href="concierges.html"><span class="ring"><i style="background:var(--mg)"></i></span><div><div class="nm">Mysterio <small>MaskGun</small></div><div class="act">174 chats · re-sent 38 deliveries</div></div><span class="st wait">spike</span></a>'
          '<a class="row" href="concierges.html"><span class="ring"><i style="background:var(--tc)"></i></span><div><div class="nm">Kingsmen Captain <small>Tower Conquest</small></div><div class="act">61 chats · name TBC</div></div><span class="st ok">4.6 ★</span></a>'
          '<a class="row" href="concierges.html"><span class="ring"><i style="background:var(--line2)"></i></span><div><div class="nm">— <small>Prime Rush · MENA</small></div><div class="act">character not chosen yet</div></div><span class="st">off</span></a>'
          '</div></div>')
    c += '</div>'
    write("ops/index.html", page("Today · SuperX Ops", app(nav("Ops", OPS_ITEMS, "index.html", OPS_ASK, OPS_FOOT), c, OPS_DOCK)))


LIVE_ROWS = [
    ("Viper_22", "mg", "Item not delivered · Gold Vest Pack", "Mysterio handling", "P1 · payer", "ticket.html"),
    ("rafa_br", "pr", "Ban appeal · angry", "handed off", "pt-BR", "ticket.html"),
    ("Ana_TC", "tc", "Payment failed at checkout", "Kingsmen Captain handling", "", "ticket.html"),
    ("lucas.mx", "pr", "How to join a team", "Juliana handling", "es", "ticket.html"),
    ("ghost99", "mg", "Refund request · Starter Pack", "needs approval", "", "approvals.html"),
]


def ops_live():
    c = head("Live · 14 conversations", "What players are asking right now", 'ops.superx.gg › <span>Live</span>')
    rows = ""
    for who, g, ask, st, tag, href in LIVE_ROWS:
        hot = "wait" if st in ("handed off", "needs approval") else "ok"
        rows += (f'<a class="row" href="{href}"><span class="dot" style="background:var(--green)"></span>'
                 f'<div><div class="nm">{who} <small>{GAMES[g][0]}</small></div><div class="act">{ask}</div></div>'
                 f'<span class="st {hot}">{st}{" · " + tag if tag else ""}</span></a>')
    c += f'<div class="grid g21"><div class="panel"><div class="ph"><h2>Live<b>.</b></h2><span class="tag">all games</span><span class="tag">auto-refresh</span></div><div class="rows">{rows}</div></div>'
    c += ('<div class="panel"><div class="ph"><h2>Viper_22 · MaskGun<b>.</b></h2><span class="tag g">● live</span><a class="btn p" href="ticket.html">Take over</a></div>'
          '<div class="summary"><span class="k">Watching · from the game · maskgun.superx.gg/support</span>'
          '<p><b>Mysterio:</b> Your Gold Vest drop never made it out of the armoury — I\'ve sent it again. Restart and check Inventory → Vests.</p>'
          '<p style="margin-top:6px"><b>Viper_22:</b> legend thanks</p></div>'
          '<div class="tl" style="margin-top:12px"><div class="ev"><div class="when">tool · orders.get</div><div class="what">paid · delivery failed</div></div>'
          '<div class="ev o"><div class="when">tool · orders.redeliver</div><div class="what">ok · audit #8812 · push queued</div></div></div></div></div>')
    write("ops/live.html", page("Live · SuperX Ops", app(nav("Ops", OPS_ITEMS, "live.html", OPS_ASK, OPS_FOOT), c, OPS_DOCK)))


def ops_inbox():
    c = head("Inbox · every game, every channel", "38 open, 2 overdue", 'ops.superx.gg › <span>Inbox</span>')
    c += ('<div class="acts"><span class="tag f">All</span><span class="tag">Chat</span><span class="tag">Store review</span><span class="tag">Discord</span>'
          '<span class="tag">Email</span><span class="tag">P1</span><span class="tag o">Overdue</span><span class="tag">pt-BR</span></div>')
    data = [
        ("PR-BJQX4", "pr", "Season pass reward missing", "Chat", "P1", "Juliana", "due 3h", "ok"),
        ("MG-4KD2A", "mg", "Double charge on Gold Vest Pack", "Discord", "P1", "Ana", "OVERDUE 40m", "wait"),
        ("PR-77QWE", "pr", "Ban appeal — says it was his brother", "Chat", "P2", "Rahul", "due 9h", "ok"),
        ("TC-1A9KM", "tc", "Can't link Google, new phone", "Email", "P3", "—", "due 20h", "ok"),
        ("RV-5521", "pr", "★☆☆☆☆ \"lost all progress after update\"", "Play review", "P2", "draft ready", "due 6h", "ok"),
        ("MG-88LQZ", "mg", "Coupon says invalid", "Chat", "P3", "Mysterio", "due 22h", "ok"),
    ]
    rows = "".join(
        f'<tr><td class="mono"><a href="ticket.html">{i}</a></td><td><span class="dot" style="background:{GAMES[g][1]}"></span> {GAMES[g][0]}</td>'
        f'<td><a href="ticket.html"><b>{s}</b></a></td><td>{ch}</td><td><span class="tag{" f" if p == "P1" else ""}">{p}</span></td>'
        f'<td>{a}</td><td class="mono" style="color:{"var(--signal)" if st == "wait" else "var(--ink3)"}">{d}</td></tr>'
        for i, g, s, ch, p, a, d, st in data)
    c += (f'<div class="panel" style="padding:0"><table class="t2"><tr><th>Ticket</th><th>Game</th><th>Issue</th><th>Channel</th>'
          f'<th>Priority</th><th>With</th><th>SLA</th></tr>{rows}</table></div>')
    write("ops/inbox.html", page("Inbox · SuperX Ops", app(nav("Ops", OPS_ITEMS, "inbox.html", OPS_ASK, OPS_FOOT), c, OPS_DOCK)))


def ops_ticket():
    c = head("MG-4KD2A · MaskGun · Discord", "Double charge on Gold Vest Pack", 'Inbox › <span>MG-4KD2A</span>')
    c += ('<div class="grid g21"><div class="panel"><div class="ph"><h2>Conversation<b>.</b></h2><span class="tag f">P1 · payer</span><span class="tag o">overdue 40m</span><span class="tag">assignee: Ana</span></div>'
          '<div class="summary"><span class="k">What\'s true now · compiled by ops</span>Charged twice for the Gold Vest Pack at 20:43 (two invoices, 40 s apart). One was delivered; the second is a duplicate. Refunds need a person.</div>'
          '<div class="tl" style="margin-top:12px">'
          '<div class="ev"><div class="when">20:51 · Discord</div><div class="what">"paid twice for the vest pack, only got one"</div></div>'
          '<div class="ev"><div class="when">20:51 · Mysterio</div><div class="what">Checked both invoices; one delivered, one duplicate. Proposed a refund of the duplicate <span class="src">orders.get</span></div></div>'
          '<div class="ev o"><div class="when">20:52 · approval</div><div class="what">Waiting for a person: refund $4.99 to the store <span class="src">needs you</span></div></div>'
          '</div><div class="acts" style="margin-top:6px"><a class="btn o" href="approvals.html">Approve refund</a><span class="btn">Reply as Mysterio</span><span class="btn">Take over</span></div></div>'
          '<div class="panel"><div class="ph"><h2>Player<b>.</b></h2><span class="tag">SuperX ID</span></div>'
          '<div class="rows"><div class="row nod"><div><div class="nm">Viper_22</div><div class="act">MaskGun · viper_22 · proven (game)</div></div><span class="st">since Mar 2025</span></div>'
          '<div class="row nod"><div><div class="nm">Also plays</div><div class="act">Prime Rush · EDFXPT5G</div></div><span class="st ok">linked</span></div>'
          '<div class="row nod"><div><div class="nm">Orders today</div><div class="act">Gold Vest Pack ×2 · SuperX store (Xsolla) · $4.99 each</div></div><span class="st wait">duplicate</span></div>'
          '<div class="row nod"><div><div class="nm">Standing</div><div class="act">no reports · not banned · supporter: high</div></div><span class="st ok">clear</span></div></div>'
          '<div class="summary" style="margin-top:12px"><span class="k">Suggested next step</span>Approve the duplicate refund; Mysterio tells the player and sends the receipt to their in-game mail.</div></div></div>')
    write("ops/ticket.html", page("MG-4KD2A · SuperX Ops", app(nav("Ops", OPS_ITEMS, "inbox.html", OPS_ASK, OPS_FOOT), c, OPS_DOCK)))


def ops_approvals():
    c = head("Approvals · actions the concierges can't do alone", "Three things wait for a person", 'ops.superx.gg › <span>Approvals</span>')
    items = [
        ("mg", "Refund duplicate charge · $4.99", "Mysterio · Viper_22 · MG-4KD2A", "Two invoices 40 s apart; one delivered."),
        ("pr", "Grant 500 Prime Gold", "Juliana · rafa_br · PR-77QWE", "Gold spent on a bundle that was pulled mid-purchase."),
        ("pr", "Lift chat ban", "Kaara · kenji_p · PR-90AAF", "Reported once for a name later changed; no other reports."),
    ]
    rows = "".join(
        f'<div class="row"><span class="ring"><i style="background:{GAMES[g][1]}"></i></span><div><div class="nm">{t}</div>'
        f'<div class="act">{w} — {why}</div></div><span class="acts"><a class="btn o" href="ticket.html">Approve</a><a class="btn" href="ticket.html">Open</a></span></div>'
        for g, t, w, why in items)
    c += f'<div class="panel"><div class="rows">{rows}</div></div>'
    write("ops/approvals.html", page("Approvals · SuperX Ops", app(nav("Ops", OPS_ITEMS, "approvals.html", OPS_ASK, OPS_FOOT), c, OPS_DOCK)))


def ops_reviews():
    c = head("Store reviews · drafted in each game's voice", "12 to answer", 'ops.superx.gg › <span>Store reviews</span>')
    revs = [
        ("pr", "★☆☆☆☆", "rafa_br · Google Play", "Perdi todo meu progresso depois da atualização",
         "Poxa, rafa — isso não é o jeito Latam Legends de tratar ninguém. Seu progresso fica salvo na sua conta: vincula ela em support.superx.gg e a Juliana devolve tudo hoje."),
        ("mg", "★★☆☆☆", "ghostrecon · App Store", "Coupon said invalid on the vest pack",
         "Masks off — that coupon only works on full-price packs. Ask Mysterio in the store and he'll swap it for one that fits the vest."),
        ("tc", "★★★★★", "towerqueen · Google Play", "Best update yet, the new arena is great",
         "The Kingsmen raise a banner for you. New arenas land every season — see you on the walls."),
    ]
    rows = "".join(
        f'<div class="panel"><div class="ph"><span class="dot" style="background:{GAMES[g][1]}"></span><b>{GAMES[g][0]}</b><span class="tag">{s}</span><span class="tag">{who}</span></div>'
        f'<div class="summary"><span class="k">Player</span>{txt}</div><div class="summary" style="margin-top:8px;background:#fff;border:1px dashed var(--line2)">'
        f'<span class="k">Draft reply · in-world voice</span>{reply}</div><div class="acts" style="margin-top:8px"><span class="btn p">Approve &amp; post</span><span class="btn">Edit</span></div></div>'
        for g, s, who, txt, reply in revs)
    c += f'<div class="grid">{rows}</div>'
    write("ops/reviews.html", page("Store reviews · SuperX Ops", app(nav("Ops", OPS_ITEMS, "reviews.html", OPS_ASK, OPS_FOOT), c, OPS_DOCK)))


def ops_store():
    c = head("Store ops · MaskGun", "Run every store from here", 'ops.superx.gg › <span>Store ops</span>')
    c += ('<div class="acts"><span class="tag"><span class="dot" style="background:var(--pr)"></span>Prime Rush</span><span class="tag"><span class="dot" style="background:var(--tc)"></span>Tower Conquest</span><span class="tag f"><span class="dot" style="background:var(--mg)"></span>MaskGun</span></div>')
    c += ('<div class="grid g2">'
          '<div class="panel"><div class="ph"><h2>Availability<b>.</b></h2><span class="tag">GameGateway</span></div><div class="facts"><div class="fact"><div class="k">Backend</div><div class="v">available</div></div><div class="fact"><div class="k">Android · iOS</div><div class="v">3.049</div></div><div class="fact"><div class="k">WebGL</div><div class="v">3.049</div></div></div>'
          '<div class="row nod" style="margin-top:10px"><div><div class="nm">Maintenance message</div><div class="act">"The armoury\'s being restocked — back in 20 minutes."</div></div><span class="toggle off"></span></div></div>'
          '<div class="panel"><div class="ph"><h2>Failed deliveries<b>.</b></h2><span class="tag o">3 waiting</span><span class="tag">41 today</span></div><div class="rows">'
          '<div class="row nod"><div><div class="nm">ghost99 · Starter Pack</div><div class="act">fulfil timeout 20:12</div></div><span class="btn">Re-send</span></div>'
          '<div class="row nod"><div><div class="nm">neo.k · 500 Diamonds</div><div class="act">fulfil timeout 20:31</div></div><span class="btn">Re-send</span></div>'
          '<div class="row nod"><div><div class="nm">sasha · Gold Vest Pack</div><div class="act">fulfil timeout 20:47</div></div><span class="btn">Re-send</span></div></div></div>'
          '<div class="panel"><div class="ph"><h2>Refunds flagged for review<b>.</b></h2><span class="tag">clawback review</span></div><div class="rows">'
          '<div class="row nod"><div><div class="nm">ghost99 · refunded after delivery</div><div class="act">Starter Pack · items still in inventory</div></div><span class="acts"><span class="btn">Claw back</span><span class="btn">Keep</span></span></div></div></div>'
          '<div class="panel"><div class="ph"><h2>Coupons<b>.</b></h2><span class="tag p">support thank-you 10%</span></div>'
          '<div class="row nod"><div><div class="nm">Budget this week</div><div class="act">412 of 1,000 used</div><div class="bar pk"><i style="width:41%"></i></div></div><span class="st">41%</span></div>'
          '<div class="row nod" style="margin-top:8px"><div><div class="nm">Offer after 4★+ resolutions</div><div class="act">collection-aware · once per 14 days</div></div><span class="toggle"></span></div></div>'
          '</div>')
    write("ops/store.html", page("Store ops · SuperX Ops", app(nav("Ops", OPS_ITEMS, "store.html", OPS_ASK, OPS_FOOT), c, OPS_DOCK)))


def ops_reports():
    c = head("Reports · MaskGun · today", "What players asked for", 'ops.superx.gg › <span>Reports</span>')
    c += ('<div class="panel" style="border-color:var(--signal)"><div class="ph"><span class="dot" style="background:var(--signal)"></span><b>Spike</b><span class="tag o">3.4× baseline</span></div>'
          '<div style="font-size:14px">"Item not delivered" on MaskGun since 19:40 — 41 chats, 38 fixed by re-delivery. Likely a fulfil backend problem.</div>'
          '<div class="acts" style="margin-top:8px"><a class="btn p" href="store.html">Open store ops</a></div></div>')
    asks = [("Item not delivered after purchase", "212", "▲ 3.4×"), ("Link Google / new phone", "96", "—"), ("Ban appeal", "41", "▼"),
            ("Coupon didn't apply", "33", "new"), ("When is the next season", "29", "—")]
    rows = "".join(f'<div class="row"><span class="mono">{i+1}</span><div class="nm">{a}</div><span class="st{" wait" if "▲" in t or t == "new" else ""}">{n} · {t}</span></div>'
                   for i, (a, n, t) in enumerate(asks))
    c += (f'<div class="grid g21"><div class="panel"><div class="ph"><h2>Top asks<b>.</b></h2><span class="tag">from intent records</span></div><div class="rows">{rows}</div>'
          '<div class="summary" style="margin-top:12px"><span class="k">In their words</span>"paid twice and got nothing, fix this pls" · "coupon says invalid on the vest pack"</div></div>'
          '<div class="panel"><div class="ph"><h2>How support did<b>.</b></h2></div><div class="facts" style="grid-template-columns:1fr 1fr">'
          '<div class="fact"><div class="k">Without a human</div><div class="v">84%</div></div><div class="fact"><div class="k">First reply</div><div class="v">1.4 s</div></div>'
          '<div class="fact"><div class="k">Time to fix</div><div class="v">3 min</div></div><div class="fact"><div class="k">Rating</div><div class="v">4.6 ★</div></div>'
          '<div class="fact"><div class="k">Taken over</div><div class="v">6%</div></div><div class="fact"><div class="k">Cost / chat</div><div class="v">$0.004</div></div></div>'
          '<div class="summary" style="margin-top:12px"><span class="k">OpenPing</span><span class="dot" style="background:var(--green)"></span> support.superx.gg · widget · engine · GameGateway · agent test (MaskGun passed 21:00) · push + inbox test</div></div></div>')
    write("ops/reports.html", page("Reports · SuperX Ops", app(nav("Ops", OPS_ITEMS, "reports.html", OPS_ASK, OPS_FOOT), c, OPS_DOCK)))


def ops_concierges():
    c = head("Concierges · one per game, a character from its world", "Who answers your players", 'ops.superx.gg › <span>Characters</span>')
    cards = [
        ("J", "var(--pr)", "Juliana", "Prime Rush · LATAM · Latam Legends", "Warm, fast, pt-BR and es; talks like a Rio street legend; brings up the season and the Latam Legends series.",
         "🔥 ⚡ 🎯", "\"Já tô vendo — um seg.\"", "4.7 ★ · eval 92"),
        ("K", "var(--pr)", "Kaara", "Prime Rush · Global · Fight Club", "Blunt, competitive, short sentences; frames fixes like a fight won.", "🥊 ⚡", "\"Sorted. Back in the ring.\"", "4.5 ★ · eval 88"),
        ("M", "var(--mg)", "Mysterio", "MaskGun · mask roster", "Dry, a little cryptic, tactical; talks in loadouts, maps and masks.", "🎭 🎯", "\"Your drop never left the armoury. Sent it again.\"", "4.6 ★ · eval 90"),
        ("K", "var(--tc)", "Kingsmen Captain", "Tower Conquest · Kingsmen (name TBC)", "Proud, playful strategist; talks in towers, arenas and the five universes.", "🏰 🛡️", "\"The banner's raised — your chest is in the keep.\"", "4.6 ★ · eval 86"),
    ]
    out = "".join(
        f'<div class="panel"><div class="ph"><span class="av" style="background:{col}">{a}</span><div><h2>{n}<b>.</b></h2><div class="muted" style="font-size:12px">{w}</div></div>'
        f'<span class="tag g">{sc}</span></div><div class="summary"><span class="k">Voice</span>{v}</div>'
        f'<div class="facts" style="margin-top:10px"><div class="fact"><div class="k">Emoji</div><div class="v">{e}</div></div>'
        f'<div class="fact" style="grid-column:span 2"><div class="k">Sounds like</div><div class="v">{q}</div></div></div>'
        f'<div class="acts" style="margin-top:10px"><span class="btn p">Edit character</span><span class="btn">Test a conversation</span><span class="btn">Learned from: tickets · Discord · reviews</span></div></div>'
        for a, col, n, w, v, e, q, sc in cards)
    out += ('<div class="panel" style="border-style:dashed"><div class="ph"><span class="av" style="background:var(--line2)">?</span><h2>Prime Rush · MENA<b>.</b></h2><span class="tag o">needs a character</span></div>'
            '<div class="muted">Pick a character from the MENA roster; the voice is learned from MENA players\' chats and reviews (ar).</div></div>')
    c += f'<div class="grid g2">{out}</div>'
    write("ops/concierges.html", page("Characters · SuperX Ops", app(nav("Ops", OPS_ITEMS, "concierges.html", OPS_ASK, OPS_FOOT), c, OPS_DOCK)))


def ops_knowledge():
    c = head("Knowledge · per game, written in the game's words", "Four gaps to fill", 'ops.superx.gg › <span>Knowledge</span>')
    gaps = [("mg", "Coupon didn't apply", "33 asks this week, no article"), ("pr", "Moving my account to a new phone", "21 asks · article exists in pt-BR only"),
            ("tc", "Season chest not in mailbox", "14 asks"), ("pr", "What is Prime Market", "12 asks · new feature")]
    rows = "".join(f'<div class="row"><span class="dot" style="background:{GAMES[g][1]}"></span><div><div class="nm">{t}</div><div class="act">{d}</div></div><span class="btn pk">Draft in-world</span></div>' for g, t, d in gaps)
    c += f'<div class="grid g21"><div class="panel"><div class="ph"><h2>Gaps<b>.</b></h2><span class="tag">from "couldn\'t answer"</span></div><div class="rows">{rows}</div></div>'
    c += ('<div class="panel"><div class="ph"><h2>Articles<b>.</b></h2></div><div class="facts" style="grid-template-columns:1fr 1fr">'
          '<div class="fact"><div class="k">Prime Rush</div><div class="v">122 · pt-BR, es, ar</div></div><div class="fact"><div class="k">Tower Conquest</div><div class="v">18 · en, ru</div></div>'
          '<div class="fact"><div class="k">MaskGun</div><div class="v">21 · en</div></div><div class="fact"><div class="k">Shared</div><div class="v">14 · account, payments</div></div></div></div></div>')
    write("ops/knowledge.html", page("Knowledge · SuperX Ops", app(nav("Ops", OPS_ITEMS, "knowledge.html", OPS_ASK, OPS_FOOT), c, OPS_DOCK)))


# ================================================================ support.superx.gg
def sup_home():
    c = head("Saturday 18 Oct · support.superx.gg", "Hey Quente. One thing's moving", 'support.superx.gg › <span>Home</span>')
    c += '<div class="search">Ask anything about Prime Rush, Tower Conquest or MaskGun…<kbd>⌘K</kbd></div>'
    c += ('<div class="grid g4">'
          '<a class="bcard" href="conversation.html"><div class="k"><span class="dot" style="background:var(--pink)"></span>In progress</div><div class="n">1</div><div class="s">Kitsune charm — Juliana sent it to your mailbox</div></a>'
          '<a class="bcard" href="purchases.html"><div class="k">Deliveries</div><div class="n">All in</div><div class="s">Last 30 days, every purchase delivered</div></a>'
          '<a class="bcard" href="../id/account.html"><div class="k">Games linked</div><div class="n">2</div><div class="s">Prime Rush · MaskGun · link Tower Conquest</div></a>'
          '<a class="bcard" href="conversations.html"><div class="k">Resolved</div><div class="n">4</div><div class="s">All rated ★★★★★ — thanks</div></a></div>')
    c += ('<div class="grid g21"><div class="panel"><div class="ph"><h2>Kitsune charm, season pass<b>.</b></h2><span class="tag">Prime Rush</span><span class="tag p">with Juliana</span></div>'
          '<div class="summary"><span class="k">Where it stands</span>The level-40 reward got stuck on our side after the update. Juliana re-sent it to your in-game mailbox at 21:02 — claim it next time you log in.</div>'
          '<div class="tl" style="margin-top:12px"><div class="ev"><div class="when">21:00</div><div class="what">Juliana spotted the stuck reward before you asked</div></div>'
          '<div class="ev o"><div class="when">21:02</div><div class="what">Re-sent to your mailbox <span class="src">in-game mail</span></div></div>'
          '<div class="ev"><div class="when">next</div><div class="what">You\'ll get a push when it\'s claimed</div></div></div></div>'
          '<div class="panel"><div class="ph"><h2>Help, by game<b>.</b></h2></div><div class="rows">'
          '<a class="row" href="help.html"><span class="dot" style="background:var(--pr)"></span><div><div class="nm">Prime Rush</div><div class="act">Pass, Latam Legends, Prime Market, teams</div></div><span class="st">122</span></a>'
          '<a class="row" href="help.html#mg"><span class="dot" style="background:var(--mg)"></span><div><div class="nm">MaskGun</div><div class="act">Masks, loadouts, clans, the armoury</div></div><span class="st">21</span></a>'
          '<a class="row" href="help.html#tc"><span class="dot" style="background:var(--tc)"></span><div><div class="nm">Tower Conquest</div><div class="act">Universes, arenas, chests</div></div><span class="st">18</span></a></div></div></div>')
    write("support/index.html", page("SuperX Support", app(nav("Support", SUP_ITEMS, "index.html", SUP_ASK, SUP_FOOT), c, sup_dock(JULIANA))))


def sup_conversations():
    c = head("Conversations · every game", "Your conversations", 'support.superx.gg › <span>Conversations</span>')
    rows = [("pr", "Kitsune charm, season pass", "Juliana · re-sent to your mailbox", "in progress", "pk"),
            ("mg", "Gold Vest Pack didn't land", "Mysterio · re-sent in 3 min", "resolved ★★★★★", "ok"),
            ("mg", "Linking Google on a new phone", "Mysterio · linked", "resolved ★★★★★", "ok"),
            ("pr", "How do teams work", "Juliana · answered", "resolved ★★★★", "ok")]
    r = "".join(f'<a class="row" href="conversation.html"><span class="dot" style="background:{GAMES[g][1]}"></span><div><div class="nm">{t}</div><div class="act">{w}</div></div><span class="st {s}">{st}</span></a>' for g, t, w, st, s in rows)
    c += f'<div class="panel"><div class="rows">{r}</div></div>'
    write("support/conversations.html", page("Conversations · SuperX Support", app(nav("Support", SUP_ITEMS, "conversations.html", SUP_ASK, SUP_FOOT), c, sup_dock(JULIANA))))


def sup_conversation():
    c = head("Prime Rush · with Juliana", "Kitsune charm, season pass", 'Conversations › <span>Kitsune charm</span>')
    c += ('<div class="grid g21"><div class="panel"><div class="ph"><h2>Status<b>.</b></h2><span class="tag p">in progress</span></div>'
          '<div class="facts"><div class="fact"><div class="k">Received</div><div class="v">21:00</div></div><div class="fact"><div class="k">Fixed</div><div class="v">21:02 · re-sent</div></div><div class="fact"><div class="k">Next</div><div class="v">claim in game</div></div></div>'
          '<div class="tl" style="margin-top:14px"><div class="ev"><div class="when">21:00 · Juliana</div><div class="what">E aí, Quente! Vi que o Charme Kitsune do nível 40 ficou travado no nosso lado…</div></div>'
          '<div class="ev o"><div class="when">21:02 · fixed</div><div class="what">Re-sent to your in-game mailbox <span class="src">in-game mail</span></div></div>'
          '<div class="ev"><div class="when">soon</div><div class="what">Push when it\'s claimed, then a one-tap rating</div></div></div></div>'
          '<div class="panel"><div class="ph"><h2>Something else wrong<b>?</b></h2></div><div class="rows">'
          '<div class="row nod"><div class="nm">It still isn\'t there</div><span class="btn">Tell Juliana</span></div>'
          '<div class="row nod"><div class="nm">Talk to a person</div><span class="btn">Hand off</span></div></div></div></div>')
    write("support/conversation.html", page("Kitsune charm · SuperX Support", app(nav("Support", SUP_ITEMS, "conversations.html", SUP_ASK, SUP_FOOT), c, sup_dock(JULIANA))))


def sup_purchases():
    c = head("Purchases · store and in-app", "Everything you've bought", 'support.superx.gg › <span>Purchases</span>')
    data = [("mg", "Gold Vest Pack", "SuperX store", "18 Oct", "delivered"), ("pr", "Prime Pass · Season 4", "Google Play", "2 Oct", "delivered"),
            ("pr", "Latam Legends bundle", "SuperX store", "28 Sep", "delivered"), ("mg", "500 Diamonds", "App Store", "21 Sep", "delivered")]
    rows = "".join(f'<tr><td><span class="dot" style="background:{GAMES[g][1]}"></span> {GAMES[g][0]}</td><td><b>{n}</b></td><td>{w}</td><td class="mono">{d}</td>'
                   f'<td><span class="tag g">{s}</span></td><td><a class="btn" href="conversation.html">Problem with this order?</a></td></tr>' for g, n, w, d, s in data)
    c += f'<div class="panel" style="padding:0"><table class="t2"><tr><th>Game</th><th>Item</th><th>Bought on</th><th>Date</th><th>Status</th><th></th></tr>{rows}</table></div>'
    write("support/purchases.html", page("Purchases · SuperX Support", app(nav("Support", SUP_ITEMS, "purchases.html", SUP_ASK, SUP_FOOT), c, sup_dock(JULIANA))))


def sup_help():
    c = head("Help · in each game's own words", "Help centre", 'support.superx.gg › <span>Help</span>')
    def col(g, cats):
        items = "".join(f'<a class="row nod" href="article.html"><div><div class="nm">{t}</div><div class="act">{d}</div></div><span class="st">{n}</span></a>' for t, d, n in cats)
        return f'<div class="panel" id="{g}"><div class="ph"><span class="dot" style="background:{GAMES[g][1]}"></span><h2>{GAMES[g][0]}<b>.</b></h2></div><div class="rows">{items}</div></div>'
    c += '<div class="grid g3">'
    c += col("pr", [("Your pass and rewards", "Latam Legends, levels, stuck rewards", 18), ("Prime Market", "Night market, trades", 9), ("Your account", "Linking, new phone", 14)])
    c += col("mg", [("The armoury", "Purchases, drops, deliveries", 7), ("Masks & loadouts", "Equip, vests, weapon skins", 8), ("Your account", "Google link, new phone", 6)])
    c += col("tc", [("Chests & the keep", "Season chests, mailbox", 6), ("Universes & arenas", "Factions, mixing units", 7), ("Your account", "Linking, new phone", 5)])
    c += '</div>'
    write("support/help.html", page("Help · SuperX Support", app(nav("Support", SUP_ITEMS, "help.html", SUP_ASK, SUP_FOOT), c, sup_dock(JULIANA))))


def sup_article():
    c = head("Prime Rush · Your pass and rewards", "A pass reward didn't arrive", 'Help › Prime Rush › <span>Pass rewards</span>')
    c += ('<div class="grid g21"><div class="panel"><div class="summary"><span class="k">Short answer</span>Most stuck rewards are in your in-game mailbox, not your inventory. Open Mail → Rewards and tap Claim.</div>'
          '<div style="margin-top:14px;font-size:14px;line-height:1.6"><p>Season rewards in the Latam Legends pass are delivered by mail after each level. After a big update they can take a few minutes to show.</p>'
          '<ol style="margin:10px 0 0 18px"><li>Open the game and go to <b>Mail</b>.</li><li>Look under <b>Rewards</b>.</li><li>Tap <b>Claim</b>. It goes to your locker.</li></ol>'
          '<p style="margin-top:10px">Still not there after 15 minutes? Juliana can check your pass and re-send it.</p></div>'
          '<div class="acts" style="margin-top:14px"><span class="btn">Helpful</span><span class="btn">Not helpful</span></div></div>'
          '<div class="panel"><div class="ph"><h2>Faster<b>.</b></h2></div><div class="muted" style="font-size:13px">Juliana can look at your account and fix it in chat.</div><div class="acts" style="margin-top:10px"><span class="btn pk">Ask Juliana</span></div></div></div>')
    write("support/article.html", page("Pass rewards · SuperX Support", app(nav("Support", SUP_ITEMS, "help.html", SUP_ASK, SUP_FOOT), c, sup_dock(JULIANA))))


# ================================================================ id.superx.gg
def id_left(sub):
    return (f'<div class="idleft"><a class="brandrow" href="../index.html">{LOGO}<div><div class="brand">SuperX<b>.</b></div><div class="by">ID</div></div></a>'
            f'<div style="margin-top:auto"><div style="font-size:40px;font-weight:700;letter-spacing:-.03em;line-height:1.05">One sign-in for<br>all your games<b style="color:var(--pink)">.</b></div>'
            f'<div style="margin-top:12px;color:#B9B4AC;font-size:14px;max-width:420px">{sub}</div>'
            f'<div style="display:flex;gap:8px;margin-top:22px"><span class="tag" style="color:#EDEAE4;border-color:#3A3835"><span class="dot" style="background:var(--pr)"></span>Prime Rush</span>'
            f'<span class="tag" style="color:#EDEAE4;border-color:#3A3835"><span class="dot" style="background:var(--tc)"></span>Tower Conquest</span>'
            f'<span class="tag" style="color:#EDEAE4;border-color:#3A3835"><span class="dot" style="background:var(--mg)"></span>MaskGun</span></div></div></div>')


def id_signin():
    right = ('<div class="eyebrow">id.superx.gg</div><h1>Sign in<b>.</b></h1>'
             '<div class="muted">Playing from the game? Tap Support in the game — you\'re signed in automatically.</div>'
             '<div style="margin-top:10px;font-weight:600;font-size:13px">Player ID</div>'
             '<div class="field"><span class="inp" style="flex:none">MaskGun ▾</span><span class="inp">viper_22</span></div>'
             '<a class="btn p big" href="code.html">Send a code to my in-game mail</a>'
             '<div class="muted" style="text-align:center;font-size:12px">or</div>'
             '<a class="btn big" href="account.html">Continue with Google</a><a class="btn big" href="account.html">Continue with Apple</a>')
    write("id/signin.html", page("Sign in · SuperX ID", f'<div class="idwrap">{id_left("Your purchases, collection and support conversations for every game, on one account.")}<div class="idright">{right}</div></div>'))


def id_code():
    right = ('<div class="eyebrow">id.superx.gg</div><h1>Check your in-game mail<b>.</b></h1>'
             '<div class="muted">We sent a 6-digit code to viper_22\'s MaskGun mailbox. It works for 5 minutes.</div>'
             '<div class="codebox"><span>4</span><span>8</span><span>1</span><span>2</span><span></span><span></span></div>'
             '<a class="btn p big" href="account.html">Sign in</a><div class="muted" style="font-size:12px">Didn\'t get it? Open MaskGun → Mail. <u>Send again</u></div>')
    write("id/code.html", page("Code · SuperX ID", f'<div class="idwrap">{id_left("We never ask for your password — a code goes to the game you already play.")}<div class="idright">{right}</div></div>'))


def id_account():
    c = head("SuperX ID · signed in with Google", "Your account", 'id.superx.gg › <span>Account</span>')
    c += ('<div class="grid g21"><div class="panel"><div class="ph"><h2>Linked games<b>.</b></h2><span class="tag">one account</span></div><div class="rows">'
          '<div class="row"><span class="dot" style="background:var(--pr)"></span><div><div class="nm">Prime Rush · LATAM</div><div class="act">QuenteCapitão4497 · EDFXPT5G · linked by in-game code</div></div><span class="st ok">proven</span></div>'
          '<div class="row"><span class="dot" style="background:var(--mg)"></span><div><div class="nm">MaskGun</div><div class="act">viper_22 · linked from the game</div></div><span class="st ok">proven</span></div>'
          '<div class="row"><span class="dot" style="background:var(--tc)"></span><div><div class="nm">Tower Conquest</div><div class="act">not linked yet</div></div><a class="btn pk" href="code.html">Link</a></div></div></div>'
          '<div class="panel"><div class="ph"><h2>Sign-in<b>.</b></h2></div><div class="rows">'
          '<div class="row nod"><div class="nm">Google · q***@gmail.com</div><span class="st ok">on</span></div>'
          '<div class="row nod"><div class="nm">Apple</div><span class="btn">Add</span></div>'
          '<div class="row nod"><div class="nm">Notifications</div><span class="toggle"></span></div></div></div></div>')
    write("id/account.html", page("Account · SuperX ID", app(nav("ID", SUP_ITEMS, "../id/account.html", SUP_ASK, SUP_FOOT).replace('href="index.html"', 'href="../support/index.html"').replace('href="conversations.html"', 'href="../support/conversations.html"').replace('href="purchases.html"', 'href="../support/purchases.html"').replace('href="help.html', 'href="../support/help.html'), c)))


# ================================================================ in the game & stores
def play_maskgun():
    phone1 = ('<div class="phone"><div class="status"><span>21:04</span><span>MaskGun</span></div>'
              '<div class="url"><span>maskgun.superx.gg/support</span><span>🔒 signed in · game</span></div>'
              '<div class="chat-h"><span class="av" style="background:var(--mg)">M</span><div><div class="nm">Mysterio · MaskGun</div><div class="sb"><span class="live"></span>knows your armoury</div></div></div>'
              '<div class="msgs">'
              '<div class="b a">Viper. Your Gold Vest drop never made it out of the armoury 20 minutes ago.</div>'
              '<div class="card"><div class="r1"><div class="thumb" style="--c:var(--mg)"></div><div style="font-size:13px"><b>Gold Vest Pack</b><br><span style="opacity:.6;font-size:11.5px">SuperX store · 20:43</span></div></div>'
              '<div class="steps"><span class="on">Paid</span><span class="on">Re-sent</span><span>In game</span></div><div class="ft"><span style="opacity:.7">Sent again just now</span><span class="okt">Done</span></div></div>'
              '<div class="b a">Already sent it again. Restart and it\'s in Inventory → Vests. I\'ll ping you when it lands 🎭</div>'
              '<div class="b u gap">wait how did you know lol<span class="rx">👀</span></div>'
              '<div class="b a gap">Masks see everything. Anything else before you drop into Favela?</div>'
              '<div class="quick"><span>My coupon</span><span>Link Google</span><span>All good</span></div>'
              '</div><div class="pcomp"><span class="in">Message Mysterio</span><span class="send">↑</span></div></div>')
    phone2 = ('<div class="phone"><div class="lockbg"></div><div class="status" style="position:relative"><span>21:06</span><span></span></div>'
              '<div class="clock">21:06</div><div style="position:relative;text-align:center;font-size:14px;opacity:.8">Saturday 18 October</div>'
              '<div class="notif"><div class="ic" style="background:var(--mg)">M</div><div><div style="display:flex;justify-content:space-between;font-size:12px;opacity:.8"><span>MaskGun · Mysterio</span><span>now</span></div><b>Your Gold Vest is in ✅</b><br>Inventory → Vests. Tap to rate.</div></div>'
              '<div class="notif"><div class="ic" style="background:#fff">✉</div><div><div style="display:flex;justify-content:space-between;font-size:12px;opacity:.8"><span>MaskGun · mail</span><span>now</span></div><b>Delivery fixed</b><br>The armoury re-sent your Gold Vest Pack.</div></div></div>')
    note = ('<div class="note"><div class="eyebrow">From the game</div><h2>Tap Support → signed in<b>.</b></h2>'
            '<p>The game opens <span class="mono">maskgun.superx.gg/support?lt=…</span>; the one-time launch code signs the player in. '
            'Mysterio opens with what it already knows — a failed delivery — fixes it, and comes back with a push when it lands.</p>'
            '<p style="margin-top:10px"><a class="btn" href="towerconquest-store.html">Next: concierge in the store →</a></p></div>')
    write("play/maskgun-support.html", page("MaskGun support · in game", f'<div class="stage">{phone1}{phone2}{note}</div>'))


def play_tc_store():
    body = ('<div style="background:#FBFAFF;min-height:100vh;position:relative">'
            '<div style="display:flex;align-items:center;gap:24px;padding:14px 32px;background:#fff;border-bottom:1px solid #ECE8FA">'
            '<b style="color:var(--tc);font-size:20px;letter-spacing:.5px">TOWER CONQUEST</b><span style="color:#6B5E8E">Home</span><b>Store</b><span style="color:#6B5E8E">Play</span><span style="color:#6B5E8E">Support</span>'
            '<span class="tag" style="margin-left:auto">SuperX ID · Ana_TC</span></div>'
            '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;padding:28px 32px">'
            + "".join('<div style="height:220px;border-radius:18px;background:#EDE7FF"></div>' for _ in range(4)) +
            '<div style="grid-column:1/-1;border:1px solid #F5C2C7;background:#FFF5F6;border-radius:12px;padding:12px 16px"><b>Payment didn\'t go through.</b> You weren\'t charged.</div></div>'
            '<div style="position:fixed;right:32px;bottom:100px;background:#fff;border:1px solid var(--line);border-radius:16px;padding:12px 14px;width:300px;font-size:13.5px;box-shadow:0 10px 30px rgba(0,0,0,.08)">'
            '<b>Kingsmen Captain</b> · That payment never reached the treasury, so nothing was taken. Want me to find out why before you try again?'
            '<div class="acts" style="margin-top:10px"><span class="tag">Yes, check</span><span class="tag">Not now</span></div></div>'
            '<a href="maskgun-support.html" style="position:fixed;right:32px;bottom:28px;display:flex;align-items:center;gap:10px;background:var(--ink);color:#fff;border-radius:999px;padding:10px 18px 10px 10px;font-weight:600">'
            '<span class="av" style="background:var(--tc);color:#fff">K</span>Ask the Captain <span class="live"></span></a></div>')
    write("play/towerconquest-store.html", page("Tower Conquest store · concierge", body))


def play_personas():
    def ph(av, col, name, lang, msgs):
        return (f'<div class="phone"><div class="status"><span>9:41</span><span>{name}</span></div><div class="chat-h"><span class="av" style="background:{col}">{av}</span>'
                f'<div><div class="nm">{name}</div><div class="sb"><span class="live"></span>{lang}</div></div></div><div class="msgs">{msgs}</div></div>')
    pr = ph("J", "var(--pr)", "Juliana · Prime Rush", "pt-BR",
            '<div class="b a">E aí, Quente! Seu Charme Kitsune do nível 40 travou depois da atualização — já mandei pra sua caixa de correio ⚡</div>'
            '<div class="b u gap">sério? valeu<span class="rx">🔥</span></div>'
            '<div class="b a gap">Tamo junto. Faltam 3 níveis pro Rafael dos Latam Legends — a temporada acaba domingo.</div>')
    tc = ph("K", "var(--tc)", "Kingsmen Captain · TC", "en",
            '<div class="b a">Hail, Ana. Your Season 9 chest is still sitting in the keep — unclaimed, not lost 🏰</div>'
            '<div class="b u gap">oh where<span class="rx">👀</span></div>'
            '<div class="b a gap">Mail → Rewards → Claim. And the Jade Dynasty arena opens tonight — your monks are ready.</div>')
    mg = ph("M", "var(--mg)", "Mysterio · MaskGun", "en",
            '<div class="b a">Your daily drop went to your other mask — VIPER_22. This one\'s ViperAlt.</div>'
            '<div class="b a">Link them and every drop finds you, whichever face you wear 🎭</div>'
            '<div class="quick"><span>Link them</span><span>Leave it</span></div>')
    write("play/characters.html", page("Characters · concierge", f'<div class="stage">{pr}{tc}{mg}</div>'))


# ================================================================ map
def index():
    groups = [
        ("Player · in the game & stores", [("MaskGun: tap Support in game", "play/maskgun-support.html"), ("Tower Conquest store + concierge button", "play/towerconquest-store.html"), ("Three characters, three worlds", "play/characters.html")]),
        ("support.superx.gg", [("Home", "support/index.html"), ("Conversations", "support/conversations.html"), ("A conversation", "support/conversation.html"), ("Purchases", "support/purchases.html"), ("Help centre", "support/help.html"), ("Help article", "support/article.html")]),
        ("id.superx.gg", [("Sign in", "id/signin.html"), ("In-game code", "id/code.html"), ("Account + linked games", "id/account.html")]),
        ("ops.superx.gg", [("Today", "ops/index.html"), ("Live", "ops/live.html"), ("Inbox", "ops/inbox.html"), ("Ticket", "ops/ticket.html"), ("Approvals", "ops/approvals.html"), ("Store reviews", "ops/reviews.html"), ("Store ops", "ops/store.html"), ("Reports", "ops/reports.html"), ("Characters", "ops/concierges.html"), ("Knowledge", "ops/knowledge.html")]),
    ]
    cols = "".join(f'<div class="panel"><h2>{t}<b>.</b></h2><ul>{"".join(f"<li><a href={chr(34)}{h}{chr(34)}>{n}</a></li>" for n, h in links)}</ul></div>' for t, links in groups)
    dark_logo = LOGO.replace('class="blogo"', 'class="blogo" style="color:#0A0A0A"')
    body = (f'<div style="max-width:1280px;margin:0 auto;padding:40px 28px"><div class="brandrow" style="padding:0 0 18px;color:var(--ink)">{dark_logo}'
            f'<div><div class="brand">SuperX<b>.</b></div><div class="by" style="color:var(--ink3)">Prototype · docs/superx</div></div></div>'
            f'<h1>Support, sign-in and ops for every game<b>.</b></h1><p class="muted" style="margin:8px 0 22px;max-width:760px">Clickable prototype in the Zero theme. Every link works; data is illustrative. Concierges are characters from each game.</p>'
            f'<div class="mapgrid">{cols}</div></div>')
    write("index.html", page("SuperX prototype", body))


if __name__ == "__main__":
    for f in (ops_today, ops_live, ops_inbox, ops_ticket, ops_approvals, ops_reviews, ops_store, ops_reports,
              ops_concierges, ops_knowledge, sup_home, sup_conversations, sup_conversation, sup_purchases,
              sup_help, sup_article, id_signin, id_code, id_account, play_maskgun, play_tc_store, play_personas, index):
        f()
    print("built", sum(1 for _ in OUT.rglob("*.html")), "pages into", OUT)
