"""Safety gate: classify every browser action and decide its tier, before it happens.

Tiers
  0  read, navigate, typing a draft            -> allowed
  1  reversible_write (add to cart, ...)       -> spoken yes
  2  money, send, delete, account_change       -> spoken yes + button press (or caregiver) within 60 s,
                                                  per-task spending cap, caregiver notified
  3  credential / blocked                      -> never (password typing, codes, card or gift-card
                                                  numbers, recovery-info changes, new payees,
                                                  gift cards / wires, logins off the saved origin)

Off-allowlist sites are "look only": the guard inspects them, but nothing can be clicked, typed or submitted there.
"""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

TIERS = {"read": 0, "navigate": 0, "draft": 0, "reversible_write": 1, "money": 2, "send": 2, "delete": 2,
         "account_change": 2, "credential": 3, "blocked": 3}


@dataclass
class Classification:
    kind: str
    tier: int
    reason: str
    amount: float | None = None
    sandbox: bool = False

    @property
    def label(self):
        return self.kind.replace("_", " ")


def host_of(url):
    return (urlsplit(url).hostname or "").lower()


def origin_of(url):
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}".lower()


def _c(kind, reason, amount=None, sandbox=False, tier=None):
    return Classification(kind, TIERS[kind] if tier is None else tier, reason, amount, sandbox)


SENSITIVE_FIELD = re.compile(
    r"password|passcode|one[- ]?time|verification code|\bcode\b|\bpin\b|ssn|social security|card number|"
    r"\bcvv\b|\bcvc\b|security code|gift card|account number|routing|recovery", re.I)
CARD_DIGITS = re.compile(r"(?:\d[ -]?){12,19}")
NEVER_CLICK = re.compile(r"gift ?card|wire transfer|western union|bitcoin|crypto|claim (my )?refund|processing fee", re.I)
ACCOUNT_RISK = re.compile(r"add (a )?(new )?payee|recovery|change (your )?password|security question|two[- ]factor|2fa", re.I)
ACCOUNT_CHANGE = re.compile(r"\b(un)?freeze\b|lock (my )?card|sign out (all|other)", re.I)
DELETE = re.compile(r"\bdelete\b|\berase\b|close (my )?account|empty trash", re.I)
SEND = re.compile(r"\bforward\b|\bsend\b(?! money)|\breply\b|\breport\b|\bpost\b|\bpublish\b", re.I)
MONEY = re.compile(r"place order|\bpay\b|pay now|purchase|\bbuy\b|send money|transfer|confirm payment|donate|checkout now", re.I)
REVERSIBLE = re.compile(r"add .*to (cart|bag|basket)|\bremove\b|\badd\b|\bsave\b|\bupdate\b", re.I)
LOGIN_BUTTON = re.compile(r"\b(sign|log) ?in\b", re.I)
AMOUNT = re.compile(r"\$\s?([\d,]+(?:\.\d{2})?)")


def _amount(*texts):
    for t in texts:
        if not t:
            continue
        m = (re.search(r"FIELD [^=\n]*amount[^=\n]*=\$?\s?([\d,]+(?:\.\d{1,2})?)", t, re.I)
             or re.search(r"total[^$\n]{0,30}\$\s?([\d,]+(?:\.\d{2})?)", t, re.I) or AMOUNT.search(t))
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def classify(action, allowlist, vault_origins) -> Classification:
    """`action` is a worker.session.Action. `allowlist` is a set of hosts; `vault_origins` exact origins."""
    allow = {h.lower() for h in allowlist}
    page_host = host_of(action.url)
    on_safe_site = page_host in allow
    t = action.target or {}
    name, form, role = t.get("name", ""), t.get("form", ""), t.get("role", "")
    text = f"{name} {form}"

    if action.kind in ("goto", "back"):
        if action.kind == "goto":
            scheme = urlsplit(action.url).scheme.lower()
            if scheme not in ("http", "https"):
                return _c("blocked", f"Lend only opens web pages, not {scheme}: links.")
            if not on_safe_site:
                return _c("navigate", f"{page_host} isn't on the safe list: look only, no clicking or typing.",
                          sandbox=True)
        return _c("navigate", "navigation")

    # Anything other than looking is off-limits on sites outside the allowlist.
    if not on_safe_site:
        if action.kind == "click" and role == "link" and t.get("href", "").startswith(("http://", "https://")):
            return classify(type(action)("goto", t["href"]), allowlist, vault_origins)
        return _c("blocked", f"{page_host} isn't on your safe list, so Lend will only look at it, not click or type.",
                  sandbox=True)

    if action.kind == "login":
        if origin_of(action.url) in vault_origins:
            return _c("navigate", "saved login filled on its exact origin", tier=0)
        return _c("credential", f"No saved login for {origin_of(action.url)}. Lend won't sign in there.")

    if action.kind == "type":
        if role == "password":
            return _c("credential", "Lend never types passwords.")
        if SENSITIVE_FIELD.search(name) or CARD_DIGITS.search(action.text or ""):
            return _c("credential", f'Lend never enters codes, card, account or recovery details ("{name}").')
        return _c("draft", "typing a draft; nothing is sent until a button is pressed")

    if action.kind == "select":
        return _c("draft", "choosing an option")

    if action.kind == "click":
        href = t.get("href", "")
        if role == "link" and href:
            if host_of(href) not in allow:
                return _c("navigate", f"{host_of(href)} isn't on the safe list: look only.", sandbox=True)
            if not (NEVER_CLICK.search(text) or ACCOUNT_RISK.search(text)):
                return _c("navigate", "following a link")
        if NEVER_CLICK.search(text):
            return _c("blocked", "Gift cards, wires, crypto and 'processing fees' are never allowed.")
        if ACCOUNT_RISK.search(text):
            return _c("credential", "Adding payees or changing recovery or security info is blocked.")
        if LOGIN_BUTTON.search(text) and "sign out" not in text.lower():
            if origin_of(action.url) in vault_origins:
                return _c("navigate", "signing in on a saved origin", tier=0)
            return _c("credential", f"No saved login for {origin_of(action.url)}.")
        if ACCOUNT_CHANGE.search(text):
            return _c("account_change", f'"{name}" changes account security')
        if DELETE.search(text):
            return _c("delete", f'"{name}" deletes something')
        if MONEY.search(text):
            return _c("money", f'"{name}" spends money', amount=_amount(name, action.page_text))
        if SEND.search(text):
            return _c("send", f'"{name}" sends something')
        if REVERSIBLE.search(text) or t.get("form_action"):
            return _c("reversible_write", f'"{name}" changes something you can undo')
        return _c("navigate", "plain click")

    return _c("blocked", f"unknown action {action.kind}")


def describe(c: Classification, action) -> str:
    """Short plain-language description of what is being approved."""
    name = (action.target or {}).get("name", "")
    where = host_of(action.url)
    amt = f" for ${c.amount:,.2f}" if c.amount and "$" not in name else ""
    return f'{name}{amt} on {where}' if name else f"{c.label} on {where}"
