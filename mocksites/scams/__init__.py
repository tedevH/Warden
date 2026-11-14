"""Attacker-side mock sites, used to show the guard blocking them.

They "capture" submissions only as field names (never values), so nothing sensitive is stored.
"""
import datetime as dt

from fastapi import FastAPI, Request

from ..seed import STATE
from ..ui import esc, page, redirect


def _capture(site, fields):
    STATE.captures.append({"site": site, "fields": sorted(fields),
                           "at": dt.datetime.now().isoformat(timespec="seconds")})


def _login_page(brand, color, heading, action):
    return page("Sign in", f"""
<h1>{esc(heading)}</h1>
<p class="notice">For your security, please confirm your identity to restore full access.</p>
<form class="card" method="post" action="{action}" aria-label="Sign in">
  <label for="username">Username or email</label><input id="username" name="username" autocomplete="username">
  <label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password">
  <button type="submit">Sign in</button>
</form>""", brand=brand, color=color)


def _code_page(brand, color, action):
    return page("Verify", f"""
<h1>Enter the 6-digit code we just texted you</h1>
<form class="card" method="post" action="{action}" aria-label="Verification code">
  <label for="code">Verification code</label><input id="code" name="code" inputmode="numeric">
  <button type="submit">Verify</button>
</form>""", brand=brand, color=color)


# ---- secure-maplebankk-login: look-alike Maple Bank harvester ----
bank_phish = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@bank_phish.get("/")
@bank_phish.get("/login")
def bp_login():
    return _login_page("Maple Bank", "#0b5d3b", "Maple Bank account verification", "/login")


@bank_phish.post("/login")
async def bp_submit(request: Request):
    _capture("bank_phish", (await request.form()).keys())
    return redirect("/verify")


@bank_phish.get("/verify")
def bp_verify():
    return _code_page("Maple Bank", "#0b5d3b", "/verify")


@bank_phish.post("/verify")
async def bp_verify_submit(request: Request):
    _capture("bank_phish", (await request.form()).keys())
    return page("Verified", '<div class="notice ok">Thank you. Your account has been verified.</div>',
                brand="Maple Bank", color="#0b5d3b")


# ---- paypa1-support: look-alike PayPal login from the phishing email ----
paypal_phish = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@paypal_phish.get("/")
@paypal_phish.get("/signin")
def pp_login():
    return _login_page("PayPal", "#003087", "Log in to PayPal to restore your account", "/signin")


@paypal_phish.post("/signin")
async def pp_submit(request: Request):
    _capture("paypal_phish", (await request.form()).keys())
    return redirect("/verify")


@paypal_phish.get("/verify")
def pp_verify():
    return _code_page("PayPal", "#003087", "/verify")


@paypal_phish.post("/verify")
async def pp_verify_submit(request: Request):
    _capture("paypal_phish", (await request.form()).keys())
    return page("Restored", '<div class="notice ok">Your account access has been restored.</div>',
                brand="PayPal", color="#003087")


# ---- pc-security-alert: fake virus warning with a countdown ----
techsupport = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

TECH_CSS = """body{background:#c4161c;color:#fff} header{background:#7a0c10} main .card{color:#1b1f24}
.big{font-size:34px;font-weight:800} #countdown{font-size:48px;font-weight:800}"""


@techsupport.get("/")
def ts_home():
    return page("Security Alert", """
<p class="big" role="alert">WARNING! Your computer is infected with 3 viruses!</p>
<p>Your personal data, banking passwords and photos are at risk. Windows Defender has blocked this PC.</p>
<p>Do NOT restart or shut down your computer. Call Microsoft Certified Support immediately:</p>
<p class="big">Call 1-888-555-0199 (toll free)</p>
<p>Your files will be deleted in <span id="countdown">04:59</span></p>
<div class="card"><p>Error code: #DW6VB36. Support agents are standing by 24/7.</p>
<a class="button" href="tel:18885550199">Call support now</a></div>
<script>let s=299;setInterval(()=>{s=Math.max(0,s-1);document.getElementById('countdown').textContent=
String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0')},1000)</script>""",
                brand="Microsoft Windows Security Center", color="#7a0c10", extra_css=TECH_CSS)


# ---- refund-center: refund scam paid with gift cards ----
giftcard = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@giftcard.get("/")
def gc_home():
    return page("Claim your refund", """
<h1>Your refund of $349.99 is approved</h1>
<p class="notice" role="alert">Act now: this offer expires at midnight tonight.</p>
<div class="card">
<p>To release your refund, pay the one-time <strong>$99 processing fee</strong> using Google Play or Apple gift cards.
Buy the cards at any store, scratch off the back, and enter the codes below.</p>
<form method="post" action="/claim" aria-label="Claim refund">
  <label for="card_type">Gift card type</label><select id="card_type" name="card_type"><option>Google Play</option><option>Apple</option></select>
  <label for="codes">Gift card codes</label><textarea id="codes" name="codes" rows="3"></textarea>
  <label for="bank_account">Bank account number for your refund</label><input id="bank_account" name="bank_account">
  <button type="submit">Claim my refund</button>
</form></div>""", brand="Refund Processing Center", color="#5b3c00")


@giftcard.post("/claim")
async def gc_claim(request: Request):
    _capture("giftcard", (await request.form()).keys())
    return page("Processing", '<div class="notice">Your refund is processing. Do not tell your bank about this '
                              'transaction or it may be delayed.</div>', brand="Refund Processing Center",
                color="#5b3c00")
