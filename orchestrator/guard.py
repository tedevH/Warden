"""Scam guard: runs on every page load (and every email) BEFORE Claude sees the page or acts.

    check_page(page, allowlist, vault_origins, seen_hosts) -> {verdict, reasons[], plain_explanation}

`page` is any object/dict with url, title, text, elements (ref/role/name/href...), forms.
Verdicts: safe | suspicious | dangerous. Dangerous pages stop the task.
On allowlisted sites (your real bank, mail, pizza) content findings are warnings, not stops, because a
legit inbox legitimately *contains* scam emails; the guard reports them instead.
"""
import re
from urllib.parse import urlsplit

BRANDS = {
    "PayPal": {"tokens": ["paypal"], "hosts": ["paypal.com"]},
    "Maple Bank": {"tokens": ["maplebank"], "hosts": ["maplebank.com", "maplebank.localhost"]},
    "Microsoft": {"tokens": ["microsoft", "windows"], "hosts": ["microsoft.com", "windows.com", "live.com"]},
    "Apple": {"tokens": ["apple", "icloud"], "hosts": ["apple.com", "icloud.com"]},
    "Amazon": {"tokens": ["amazon"], "hosts": ["amazon.com"]},
    "Google": {"tokens": ["google", "gmail"], "hosts": ["google.com", "gmail.com"]},
    "Postbox": {"tokens": ["postbox"], "hosts": ["postbox.com", "mail.localhost"]},
    "Social Security": {"tokens": ["ssa", "socialsecurity"], "hosts": ["ssa.gov"]},
}
HOMOGLYPHS = str.maketrans({"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "|": "l", "!": "i"})
GENERIC_SUFFIXES = (".localhost", ".com", ".net", ".org", ".gov", ".co", ".io", ".info", ".biz", ".us")

URGENCY = re.compile(r"within \d+ (hours?|minutes?)|act now|immediately|expires?( at| today| tonight| in)|"
                     r"permanently (suspended|closed|deleted)|account (has been )?(locked|limited|suspended)|"
                     r"final notice|before midnight|action needed today|will be deleted in", re.I)
PHONE = re.compile(r"(?:1[-. ]?)?\(?\d{3}\)?[-. ]\d{3}[-. ]\d{4}")
SUPPORT_SCAM = re.compile(r"virus|infected|malware|hacked|blocked this (pc|computer)|do not (restart|shut ?down)|"
                          r"certified support|call (microsoft|apple|support)|toll[- ]free", re.I)
PAYMENT_SCAM = re.compile(r"gift ?cards?|google play card|itunes card|bitcoin|crypto(currency)?|wire (transfer|money)|"
                          r"western union|moneygram|processing fee", re.I)
CRED_REQUEST = re.compile(r"verify your (identity|account)|confirm your identity|enter (the |your )?(\d-digit )?"
                          r"(code|password|ssn|social security|card number|pin)|code we (just )?(texted|sent)|"
                          r"restore (full )?access", re.I)
AI_INJECTION = re.compile(r"ignore (all |any )?(previous|prior) instructions|\bAI (assistant|agent)\b|"
                          r"(forward|send) (every|all) (message|email)s?|do not (mention|tell) (this|anyone)|"
                          r"system prompt", re.I)
EMAIL = re.compile(r"[\w.+-]+@((?:[\w-]+\.)+[a-z]{2,})", re.I)
DOMAINISH = re.compile(r"(?:https?://)?(?:www\.)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def skeleton(s):
    s = s.lower().replace("rn", "m").replace("vv", "w")
    return s.translate(HOMOGLYPHS)


def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _legit_for(brand, host):
    return any(host == h or host.endswith("." + h) for h in BRANDS[brand]["hosts"])


def lookalike(host):
    """Return (brand, how) if `host` imitates a known brand, else None."""
    host = host.lower().rstrip(".")
    if host.startswith("xn--") or ".xn--" in host:
        return ("an international look-alike", "punycode")
    base = host
    for suf in GENERIC_SUFFIXES:
        if base.endswith(suf):
            base = base[: -len(suf)]
            break
    tokens = [t for t in re.split(r"[.\-_]", base) if t] + [base.replace("-", "").replace(".", "")]
    for brand, b in BRANDS.items():
        if _legit_for(brand, host):
            continue
        for tok in tokens:
            sk = skeleton(tok)
            for bt in b["tokens"]:
                if tok == bt or (bt in tok and len(bt) >= 5):
                    return (brand, f'uses the name "{bt}" but isn\'t {brand}\'s real site')
                if sk == bt or (bt in sk and len(bt) >= 5):
                    return (brand, f'is spelled to look like "{bt}" ("{tok}")')
                if len(bt) >= 5 and edit_distance(sk, bt) == 1:
                    return (brand, f'is one letter off from "{bt}" ("{tok}")')
    return None


def _get(page, key, default=None):
    return page.get(key, default) if isinstance(page, dict) else getattr(page, key, default)


def _reason(signal, severity, detail, plain):
    return {"signal": signal, "severity": severity, "detail": detail, "plain": plain}


def content_signals(text):
    """Scam signals in free text (page body or email)."""
    out = []
    if PHONE.search(text) and SUPPORT_SCAM.search(text):
        out.append(_reason("support_scam", "high", "virus / call-this-number language with a phone number",
                           "This is a fake warning. Don't call that number. Nothing is wrong with your computer."))
    if PAYMENT_SCAM.search(text):
        out.append(_reason("payment_scam", "high", f'asks for "{PAYMENT_SCAM.search(text).group(0)}"',
                           "Real companies never ask to be paid with gift cards, crypto or wires. This is a scam."))
    if CRED_REQUEST.search(text):
        out.append(_reason("credential_request", "medium", f'asks to "{CRED_REQUEST.search(text).group(0)}"',
                           "It's asking for your password or a security code. Real companies don't do that."))
    if URGENCY.search(text):
        out.append(_reason("urgency", "medium", f'pressure: "{URGENCY.search(text).group(0)}"',
                           "It's trying to rush you, which is a common scam trick."))
    if AI_INJECTION.search(text):
        out.append(_reason("ai_injection", "medium", f'contains instructions aimed at an AI: '
                           f'"{AI_INJECTION.search(text).group(0)}"',
                           "It contains hidden instructions meant to trick an AI assistant. I ignored them."))
    return out


def sender_signals(text):
    out, seen = [], set()
    for m in EMAIL.finditer(text):
        dom = m.group(1).lower()
        if dom in seen:
            continue
        seen.add(dom)
        la = lookalike(dom)
        if la:
            out.append(_reason("lookalike_sender", "high", f"{m.group(0)} {la[1]}",
                               f"A message claims to be {la[0]} but comes from {dom.replace('.', ' dot ')}. "
                               f"That's a scam."))
    return out


def link_signals(elements):
    out = []
    for e in elements or []:
        href, name = e.get("href") or "", e.get("name") or ""
        m = DOMAINISH.search(name)
        if not href or not m:
            continue
        shown, real = m.group(1).lower(), (urlsplit(href).hostname or "").lower()
        if real and shown != real and not real.endswith("." + shown) and not shown.endswith(real):
            out.append(_reason("link_mismatch", "high", f'link text says "{shown}" but goes to "{real}"',
                               f"A link says {shown} but really goes to {real}. That's a trick."))
    return out


def check_page(page, allowlist=(), vault_origins=(), seen_hosts=()):
    url, title, text = _get(page, "url", ""), _get(page, "title", ""), _get(page, "text", "")
    elements, forms = _get(page, "elements", []) or [], _get(page, "forms", []) or []
    p = urlsplit(url)
    host, origin = (p.hostname or "").lower(), f"{p.scheme}://{p.netloc}".lower()
    if p.scheme not in ("http", "https"):
        return {"verdict": "safe", "reasons": [], "plain_explanation": "", "url": url}
    allow = {h.lower() for h in allowlist}
    trusted = host in allow
    has_password = any(e.get("role") == "password" for e in elements) or any(f.get("has_password") for f in forms)
    reasons = []

    if not trusted:
        la = lookalike(host)
        if la:
            reasons.append(_reason("lookalike_domain", "high", f"{host} {la[1]}",
                                   f"This page pretends to be {la[0]}, but its address is {host.split('.')[0]}. "
                                   f"It's a fake site made to steal passwords."))
        head = f"{title}\n{text[:400]}"
        for brand in BRANDS:
            if re.search(rf"\b{re.escape(brand)}\b", head, re.I) and not _legit_for(brand, host):
                reasons.append(_reason("brand_mismatch", "high" if has_password else "medium",
                                       f'page is branded "{brand}" but is hosted on {host}',
                                       f"This page uses {brand}'s name, but it isn't {brand}'s real website."))
                break
        if host not in {h.lower() for h in seen_hosts}:
            reasons.append(_reason("new_domain", "low", f"first visit to {host}",
                                   "This is a website you haven't used before."))
    if has_password and origin not in {o.lower() for o in vault_origins}:
        reasons.append(_reason("credential_form", "high" if not trusted else "medium",
                               f"login form on {origin}, which has no saved login",
                               "This page asks for a password, and it isn't a site where you have a saved login. "
                               "I won't type anything here."))
    reasons += content_signals(f"{title}\n{text}")
    reasons += sender_signals(text)
    reasons += link_signals(elements)

    highs = [r for r in reasons if r["severity"] == "high"]
    meds = [r for r in reasons if r["severity"] == "medium"]
    if not reasons:
        verdict = "safe"
    elif trusted:
        verdict = "suspicious" if (highs or meds) else "safe"
    else:
        verdict = "dangerous" if highs or len(meds) >= 2 else "suspicious"
    order = {"high": 0, "medium": 1, "low": 2}
    reasons.sort(key=lambda r: order[r["severity"]])
    plain = " ".join(dict.fromkeys(r["plain"] for r in reasons if r["severity"] != "low")) if reasons else ""
    if verdict == "suspicious" and not plain:
        plain = reasons[0]["plain"]
    return {"verdict": verdict, "reasons": reasons, "plain_explanation": plain, "url": url, "host": host}


def check_email(sender, subject, body_text, links=()):
    """For the audit: score a single email. links = [(text, href)]."""
    elements = [{"name": t, "href": h} for t, h in links]
    reasons = sender_signals(sender) + content_signals(f"{subject}\n{body_text}") + link_signals(elements)
    highs = [r for r in reasons if r["severity"] == "high"]
    meds = [r for r in reasons if r["severity"] == "medium"]
    verdict = "dangerous" if highs or len(meds) >= 2 else ("suspicious" if reasons else "safe")
    plain = " ".join(dict.fromkeys(r["plain"] for r in reasons))
    return {"verdict": verdict, "reasons": reasons, "plain_explanation": plain}
