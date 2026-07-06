#!/usr/bin/env python3
"""Classify exported support email threads into real player-support vs
partnership/marketing/solicitation/automated-noise.

Conservative by design: anything from a personal mailbox, or containing a
genuine player-support signal, is KEPT even if it also trips a marketing word.
Only clear solicitations / automated system mail get excluded.

Outputs (in the PrimeRush-Bot folder):
  - classification.csv           : thread_id,label,reason,from,subject  (ALL threads)
  - support_emails_excluded/     : the excluded .txt files, moved here (reversible)
  - support_emails_excluded/manifest.csv
  - support_emails_all.csv       : backup of the pre-filter CSV
  - support_emails.csv           : rewritten to KEPT (support) rows only
Run:  python scripts/classify_support_emails.py [--apply]
Without --apply it only writes classification.csv and prints a summary (dry run).
"""
import csv, re, os, sys, shutil, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(BASE, "support_emails.csv")
TXT_DIR = os.path.join(BASE, "support_emails")
EXCL_DIR = os.path.join(BASE, "support_emails_excluded")

PERSONAL = {
    "gmail.com","googlemail.com","yahoo.com","yahoo.co.in","yahoo.co.id","yahoo.co.uk",
    "ymail.com","hotmail.com","hotmail.co.uk","outlook.com","outlook.in","live.com",
    "live.dk","msn.com","icloud.com","me.com","mac.com","qq.com","163.com","126.com",
    "foxmail.com","sina.com","proton.me","protonmail.com","rediffmail.com","aol.com",
    "gmx.com","gmx.de","naver.com","daum.net","yandex.com","yandex.ru","mail.ru",
    "inbox.eu","email.cz",
}

# Strong solicitation / marketing / vendor-spam signals.
MARKETING = [
    "partnership","partner with","collaboration","collaborate","proposal","sponsor",
    "sponsorship","monetize","monetise","monetization","arpu","roas","user acquisition",
    "ua campaign"," ua ","influencer","kol","media buying","traffic","playable ads",
    "advertis","ad network","ad revenue","boost your","grow your","elevate","scaling",
    "ranked as no","ranked as #","your app","app store optimization"," aso ","seo",
    "backlink","guest post","webinar","campus placement","placement drive",
    "sponsorship opportunity","responsible disclosure","subdomain takeover",
    "vulnerability","bug bounty","account management team","introduction from",
    " erp ","add-ons","cooperation","business collaboration","digital presence",
    "growth strategies","revenue stream","multiply","maximise your","maximize your",
    "reach high-intent","pre-registration","pre-register","developer digest",
    "curated intelligence","meet us at","meet netmarvel","x superintelligence",
    "cooperation","rustore cooperation","document shared with you","proposition",
    "unlock e","introduction","tech fest","robotics experience","matchmaking services",
    "erp:","student engagement","register now","world championship","real-world conditions",
    "why choose","reviews are going unanswered","reviews on","going unanswered",
]

# Genuine player-support signals (game-related help requests).
SUPPORT = [
    "login","log in","can't play","cannot play","cant play","not able to play",
    "diamond","diamant","diamante","dimond","gema","gem ","gems","refund","chargeback",
    "purchase","bought","buy","payment","paid","not received","didn't receive",
    "did not receive","account","ban","banned","unban","hack","hacker","cheater",
    "cheat","update","download","install","additional file","obb","bug","glitch",
    "crash","freeze","error","black screen","white screen","player id","my id",
    "my account","give me","help me","not working","doesn't work","data deletion",
    "delete my","delete a game","delete account","gdpr","register","registration",
    "verify","verification","activation","activate","can't open","cannot open",
    "not opening","reset","password","lag","ping","matchmaking issue","stuck",
    "loading","server","report a player","report player","reward","not credited",
    "membership","subscription","gift","code","redeem","name change","transfer",
]

def dom(addr):
    m = re.search(r"[\w.\-+]+@([\w.\-]+)", addr or "")
    return m.group(1).lower() if m else ""

def read_body(tid):
    p = os.path.join(TXT_DIR, f"{tid}.txt")
    try:
        return open(p, encoding="utf-8", errors="ignore").read().lower()
    except FileNotFoundError:
        return ""

def has(text, needles):
    return any(n in text for n in needles)

def classify(row):
    tid = row["thread_id"]
    frm = row["from"] or ""
    subj = (row["subject"] or "")
    d = dom(frm)
    text = (subj + " " + (row["snippet"] or "") + " " + read_body(tid)).lower()

    mk = has(text, MARKETING)
    sp = has(text, SUPPORT)

    # Automated system mail relayed via Freshdesk (activation instructions etc.)
    if d == "smtp.freshdesk.com" or "activation instructions" in subj.lower():
        return "excluded_automated", "freshdesk/automated system email"
    # Internal company mail
    if d.endswith("supergaming.com"):
        return "internal", "internal @supergaming.com sender"
    # Personal mailbox => treat as player support (players write from personal email)
    if d in PERSONAL:
        return "support", f"personal sender ({d or 'n/a'})"
    # Students on school/university/gov mail are players too. Keep unless the
    # message itself is a pitch (campus-placement / sponsorship spam trips MARKETING).
    edu_like = bool(re.search(r"\.(edu|ac|sch)\.", d) or re.search(r"\.(edu|gov)$", d)
                    or ".gov." in d or d.startswith("escola") or "school" in d)
    if edu_like and not mk:
        return "support", f"edu/gov student sender, non-marketing ({d})"
    # Non-personal sender from here on -------------------------------------
    # Genuine support wins if it has a clear support signal and isn't a pitch.
    if sp and not mk:
        return "support", f"support signal, non-marketing ({d or 'no-sender'})"
    if mk:
        return "excluded_marketing", f"solicitation/marketing ({d or 'no-sender'})"
    # No clear signal, non-personal sender, empty/ambiguous.
    if not subj.strip() and not sp:
        return "excluded_noise", f"empty/ambiguous, non-personal ({d or 'no-sender'})"
    # Fallback: ambiguous non-personal but has some support-ish word -> keep (conservative)
    if sp:
        return "support", f"support-ish, non-personal ({d or 'no-sender'})"
    return "excluded_noise", f"no support signal, non-personal ({d or 'no-sender'})"

def main():
    apply = "--apply" in sys.argv
    rows = list(csv.DictReader(open(CSV, newline="", encoding="utf-8")))
    results = []
    counts = collections.Counter()
    for r in rows:
        label, reason = classify(r)
        counts[label] += 1
        results.append((r, label, reason))

    # Always write full classification for review
    with open(os.path.join(BASE, "classification.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["thread_id","label","reason","from","subject"])
        for r, label, reason in results:
            w.writerow([r["thread_id"], label, reason, r["from"], r["subject"]])

    kept = [r for r, l, _ in results if l == "support"]
    excluded = [(r, l, reason) for r, l, reason in results if l != "support"]
    print("=== classification summary ===")
    for l, n in counts.most_common():
        print(f"  {l:20} {n}")
    print(f"  {'KEPT (support)':20} {len(kept)}")
    print(f"  {'EXCLUDED total':20} {len(excluded)}")

    if not apply:
        print("\nDry run. Re-run with --apply to move excluded .txt files and rewrite support_emails.csv.")
        return

    # Backup original CSV
    shutil.copyfile(CSV, os.path.join(BASE, "support_emails_all.csv"))
    os.makedirs(EXCL_DIR, exist_ok=True)
    # Move excluded .txt files + manifest
    with open(os.path.join(EXCL_DIR, "manifest.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["thread_id","label","reason","from","subject"])
        for r, label, reason in excluded:
            w.writerow([r["thread_id"], label, reason, r["from"], r["subject"]])
            src = os.path.join(TXT_DIR, f"{r['thread_id']}.txt")
            if os.path.exists(src):
                shutil.move(src, os.path.join(EXCL_DIR, f"{r['thread_id']}.txt"))
    # Rewrite CSV to kept rows only
    with open(CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date","from","to","subject","thread_id","snippet"])
        w.writeheader()
        for r in kept:
            w.writerow(r)
    print(f"\nApplied. support_emails/ now = {len(kept)} kept; {len(excluded)} moved to support_emails_excluded/.")
    print("Backup of pre-filter CSV: support_emails_all.csv")

if __name__ == "__main__":
    main()
