"""Account watch: a browser task that reads the bank and inbox and looks for signs of compromise.

Wording rule: findings say "looks unusual, did you make this?" and never "this is fraud".
All navigation goes through the same safety gate and scam guard as any other task. No LLM is needed.
"""
import os
import datetime as dt
import re
import statistics

from . import guard
from worker import skills

TXN_JS = """() => [...document.querySelectorAll('table[aria-label="Transactions"] tbody tr')].map(tr =>
  ({id: tr.dataset.txnId || '', cells: [...tr.cells].map(td => td.innerText.trim())}))"""
INBOX_JS = """() => [...document.querySelectorAll('table[aria-label="Messages"] tbody tr')].map(tr =>
  ({id: tr.dataset.messageId, from: tr.cells[1].innerText.trim(), subject: tr.cells[2].innerText.trim(),
    href: (tr.querySelector('a') || {}).href || ''}))"""
MESSAGE_JS = """() => { const b = document.querySelector('#message-body'); return {
  from: (document.querySelector('#from') || {}).innerText || '', body: b ? b.innerText : '',
  links: b ? [...b.querySelectorAll('a')].map(a => [a.innerText.trim(), a.href]) : []}; }"""
SIGNIN_JS = """() => [...document.querySelectorAll('table[aria-label="Recent sign-ins"] tbody tr')].map(tr =>
  [...tr.cells].map(td => td.innerText.trim()))"""
SECURITY_NOTICE = re.compile(r"new sign-?in|password (was )?(reset|changed)|recovery (email|info\w*) (was )?changed|"
                             r"new device", re.I)
RECENT_DAYS = 7


def money(x):
    return f"${abs(x):,.2f}".replace(".00", "")


def parse_amount(s):
    v = float(re.sub(r"[^\d.]", "", s) or 0)
    return -v if s.strip().startswith("-") else v


def score_transactions(txns, today=None):
    """txns: [{date 'YYYY-MM-DD', merchant, amount (negative = spend), key}]. Returns finding dicts."""
    today = today or dt.date.today()
    for t in txns:
        t["_d"] = dt.date.fromisoformat(t["date"])
    spend = [t for t in txns if t["amount"] < 0]
    recent = [t for t in spend if (today - t["_d"]).days <= RECENT_DAYS]
    older_by_merchant = {}
    for t in spend:
        if (today - t["_d"]).days > RECENT_DAYS:
            older_by_merchant.setdefault(t["merchant"], []).append(-t["amount"])
    amounts = [-t["amount"] for t in spend if (today - t["_d"]).days > RECENT_DAYS] or [-t["amount"] for t in spend]
    med = statistics.median(amounts) if amounts else 0
    mad = statistics.median([abs(a - med) for a in amounts]) if amounts else 0
    high_line = med + 6 * 1.4826 * max(mad, 1.0)

    findings, used = [], set()
    new = [t for t in recent if t["merchant"] not in older_by_merchant]
    tests = [t for t in new if -t["amount"] < 3]
    for big in sorted((t for t in new if -t["amount"] >= 50), key=lambda t: t["amount"]):
        before = [t for t in tests if 0 <= (big["_d"] - t["_d"]).days <= 2]
        if before:
            used.update(t["key"] for t in before + [big])
            n = "two" if len(before) == 2 else str(len(before))
            findings.append({
                "kind": "test_charges", "severity": "high",
                "title": f"{money(big['amount'])} at {big['merchant']} after {len(before)} small test charges",
                "evidence": [{k: t[k] for k in ("date", "merchant", "amount")} for t in before + [big]],
                "explanation": f"I found a {money(big['amount'])} charge at {big['merchant'].title()}, a store you "
                               f"haven't used before, right after {n} small test charges. That pattern looks "
                               f"unusual. Did you make it?",
                "fkey": f"test_charges:{big['key']}"})
    for t in new:
        if t["key"] in used or -t["amount"] < 3:
            continue
        big = -t["amount"] > high_line
        findings.append({
            "kind": "new_merchant", "severity": "high" if big else "low",
            "title": f"{money(t['amount'])} at new merchant {t['merchant']}",
            "evidence": [{k: t[k] for k in ("date", "merchant", "amount")}],
            "explanation": f"There's a {money(t['amount'])} charge at {t['merchant'].title()}, a place you haven't "
                           f"used before" + (", and it's much more than you usually spend" if big else "") +
                           ". It looks unusual. Did you make this?",
            "fkey": f"new_merchant:{t['key']}"})
        used.add(t["key"])
    for t in recent:
        if t["key"] in used:
            continue
        prior = older_by_merchant.get(t["merchant"], [])
        if -t["amount"] > high_line and not any(abs(p + t["amount"]) <= 0.3 * p for p in prior):
            findings.append({
                "kind": "unusual_amount", "severity": "medium",
                "title": f"Unusually large: {money(t['amount'])} at {t['merchant']}",
                "evidence": [{k: t[k] for k in ("date", "merchant", "amount")}],
                "explanation": f"A {money(t['amount'])} charge at {t['merchant'].title()} is far more than you "
                               f"usually spend there. It looks unusual. Did you make this?",
                "fkey": f"unusual_amount:{t['key']}"})
    seen = {}
    for t in sorted(recent, key=lambda t: t["_d"]):
        k = (t["merchant"], t["amount"])
        if k in seen and (t["_d"] - seen[k]["_d"]).days <= 1 and -t["amount"] >= 3:
            findings.append({
                "kind": "duplicate", "severity": "medium",
                "title": f"Possible duplicate: {money(t['amount'])} at {t['merchant']} twice",
                "evidence": [{k2: x[k2] for k2 in ("date", "merchant", "amount")} for x in (seen[k], t)],
                "explanation": f"You were charged {money(t['amount'])} at {t['merchant'].title()} twice within a "
                               f"day. That might be a mistake. Did you mean to pay twice?",
                "fkey": f"duplicate:{seen[k]['key']}:{t['key']}"})
        seen[k] = t
    for t in txns:
        t.pop("_d", None)
    return findings


async def _open(session, url):
    snap = await session.goto(url)
    if snap.has_password_field:
        await session.login()
        snap = await session.goto(url)
    return snap


async def audit_bank(session, store, user_id):
    await _open(session, f"{skills.BANK}/transactions?limit=500")
    rows = []
    for r in await session.page.evaluate(TXN_JS):
        c = r["cells"]
        if len(c) >= 4:
            rows.append({"date": c[0], "merchant": c[1], "category": c[2], "amount": parse_amount(c[3]),
                         "key": f"{r['id']}|{c[0]}|{c[1]}|{c[3]}"})
    store.upsert_txns(user_id, rows)
    findings = score_transactions(store.txns(user_id))
    await session.goto(f"{skills.BANK}/security")
    signins = await session.page.evaluate(SIGNIN_JS)
    if len(signins) >= 2:
        newest, known = signins[0], {s[1] for s in signins[1:]}
        if newest[1] not in known:
            findings.append({
                "kind": "new_device", "severity": "medium", "title": f"New device signed in to your bank: {newest[1]}",
                "evidence": [newest],
                "explanation": f"Someone signed in to your bank from a {newest[1]} ({newest[2]}), which isn't your "
                               f"usual device. Was that you? If not, I can sign out other devices.",
                "fkey": f"new_device:{newest[0]}:{newest[1]}"})
    return findings


async def audit_inbox(session, limit=12):
    await _open(session, f"{skills.MAIL}/inbox")
    findings = []
    for row in (await session.page.evaluate(INBOX_JS))[:limit]:
        if not row["href"]:
            continue
        await session.goto(row["href"])
        m = await session.page.evaluate(MESSAGE_JS)
        v = guard.check_email(m["from"], row["subject"], m["body"], m["links"])
        sender = (guard.EMAIL.search(m["from"]) or [m["from"]])[0]
        if v["verdict"] != "safe":
            findings.append({
                "kind": "phishing_email", "severity": "high" if v["verdict"] == "dangerous" else "medium",
                "title": f'Suspicious email: "{row["subject"]}"',
                "evidence": {"from": m["from"], "signals": [r["detail"] for r in v["reasons"]]},
                "explanation": f'The email "{row["subject"]}" from {sender} looks like a scam. '
                               f'{v["plain_explanation"]} Don\'t click anything in it.',
                "fkey": f"phish:{row['id']}:{row['subject']}"})
        elif SECURITY_NOTICE.search(f"{row['subject']} {m['body']}"):
            findings.append({
                "kind": "security_notice", "severity": "medium", "title": f'Security notice: "{row["subject"]}"',
                "evidence": {"from": m["from"]},
                "explanation": f'You got a security notice: "{row["subject"]}". If that wasn\'t you, someone else '
                               f"may be in your account.",
                "fkey": f"notice:{row['id']}:{row['subject']}"})
    return findings


async def run_audit(tm, task, session) -> str:
    """Returns the spoken summary. Stores findings, notifies the caregiver, and phones the person if needed."""
    tm.narrate(task, "Checking your bank for anything unusual")
    findings = await audit_bank(session, tm.store, task.user_id)
    tm.narrate(task, "Checking your email for scams and security notices")
    findings += await audit_inbox(session)
    rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: rank[f["severity"]])
    fresh = [f for f in findings if tm.store.add_finding(task.user_id, task.id, f["kind"], f["severity"], f["title"],
                                                         f["evidence"], f["explanation"], f["fkey"])]
    serious = [f for f in findings if f["severity"] != "low"]
    new_high = [f for f in fresh if f["severity"] == "high"]
    for f in new_high:
        tm.notify(task.user_id, f"{f['title']}. {f['explanation']}")
    # Phone only about money: scam emails sit in every inbox and go on the report, not a phone call.
    money_alert = next((f for f in new_high if f["kind"] in ("test_charges", "new_merchant")), None)
    if money_alert and tm.adapter and not tm.on_call.get(task.user_id):
        phone = tm.store.settings()["profile"].get("phone", "") or os.getenv("USER_PHONE", "")
        line = f"Hi, it's Warden. I'm calling because I noticed something. {money_alert['explanation']}"
        tm.narrate(task, "Calling to tell them what I found")
        import asyncio
        asyncio.get_running_loop().run_in_executor(None, tm._safe, tm.adapter.place_outbound_call, phone, line)
    if not serious:
        return "I checked your bank and your email. Everything looks normal."
    top = " ".join(f["explanation"] for f in serious[:3])
    more = f" There are {len(serious) - 3} more things on the list for your family to look at." if len(serious) > 3 else ""
    return f"I checked your bank and your email and found {len(serious)} things that look unusual. {top}{more}"
