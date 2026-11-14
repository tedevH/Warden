"""Maple Bank (legitimate mock): login, accounts, transactions, card freeze, report, transfer, security."""
import datetime as dt
import hmac

from fastapi import FastAPI, Form, Request

from ..seed import STATE, creds
from ..ui import Sessions, esc, login_redirect, money, page, redirect

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
sessions = Sessions("maple_sid")
BRAND, COLOR = "Maple Bank", "#0b5d3b"
NAV = [("Accounts", "/accounts"), ("Transactions", "/transactions"), ("Card", "/card"),
       ("Transfer", "/transfer"), ("Security", "/security"), ("Sign out", "/logout")]


def view(title, body, signed_in=True):
    return page(title, body, brand=BRAND, color=COLOR, nav=NAV if signed_in else ())


@app.get("/")
def home(request: Request):
    return redirect("/accounts" if sessions.user(request) else "/login")


@app.get("/login")
def login_form(next: str = "/accounts", error: str = ""):
    msg = '<p class="notice error" role="alert">Incorrect username or password.</p>' if error else ""
    return view("Sign in", f"""
<h1>Sign in to Maple Bank</h1>{msg}
<form class="card" method="post" action="/login" aria-label="Sign in">
  <input type="hidden" name="next" value="{esc(next)}">
  <label for="username">Username</label><input id="username" name="username" autocomplete="username" required>
  <label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>
</form>
<p class="muted">Maple Bank will never ask for your password by email, text or phone.</p>""", signed_in=False)


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), next: str = Form("/accounts")):
    user, pw = creds("bank")
    if hmac.compare_digest(username, user) and hmac.compare_digest(password, pw):
        target = next if next.startswith("/") and not next.startswith("//") else "/accounts"
        return sessions.start(redirect(target), username)
    return redirect("/login?error=1")


@app.get("/logout")
def logout(request: Request):
    return sessions.end(request, redirect("/login"))


@app.get("/accounts")
def accounts(request: Request):
    if not sessions.user(request):
        return login_redirect(request)
    card = "Frozen" if STATE.card_frozen else "Active"
    return view("Accounts", f"""
<h1>Good day, Margaret</h1>
<section class="card" aria-label="Checking account">
  <h2>Everyday Checking ••••6612</h2>
  <p>Available balance: <strong id="balance">{money(STATE.balance())}</strong></p>
  <p>Debit card ••••4471: <strong id="card-status">{card}</strong></p>
  <a class="button" href="/transactions">View transactions</a>
</section>
<section class="card" aria-label="Savings account">
  <h2>Savings ••••0934</h2><p>Available balance: <strong>{money(12650.00)}</strong></p>
</section>""")


@app.get("/transactions")
def transactions(request: Request, limit: int = 50):
    if not sessions.user(request):
        return login_redirect(request)
    rows = sorted(STATE.txns, key=lambda t: (t["date"], t["id"]), reverse=True)[: max(1, min(limit, 500))]
    body = "".join(
        f'<tr data-txn-id="{t["id"]}"><td>{t["date"].isoformat()}</td><td>{esc(t["merchant"])}</td>'
        f'<td>{esc(t["category"])}</td><td class="amount {"neg" if t["amount"] < 0 else "pos"}">{money(t["amount"])}</td>'
        f'<td><a href="/transactions/{t["id"]}/report">Report</a></td></tr>' for t in rows)
    return view("Transactions", f"""
<h1>Transactions</h1>
<p>Everyday Checking ••••6612. Balance {money(STATE.balance())}.</p>
<table aria-label="Transactions">
<thead><tr><th scope="col">Date</th><th scope="col">Merchant</th><th scope="col">Category</th>
<th scope="col" class="amount">Amount</th><th scope="col">Action</th></tr></thead>
<tbody>{body}</tbody></table>""")


@app.get("/transactions/{tid}/report")
def report_form(request: Request, tid: int):
    if not sessions.user(request):
        return login_redirect(request)
    t = next((x for x in STATE.txns if x["id"] == tid), None)
    if not t:
        return view("Not found", "<h1>Transaction not found</h1>")
    return view("Report transaction", f"""
<h1>Report a transaction</h1>
<div class="card"><p><strong>{esc(t["merchant"])}</strong> on {t["date"].isoformat()} for {money(t["amount"])}</p>
<form method="post" action="/transactions/{tid}/report" aria-label="Report transaction">
  <label for="reason">What's wrong?</label>
  <select id="reason" name="reason"><option>I don't recognize this charge</option><option>Duplicate charge</option>
  <option>Wrong amount</option></select>
  <button type="submit" class="danger">Report transaction</button>
</form></div>""")


@app.post("/transactions/{tid}/report")
def report(request: Request, tid: int, reason: str = Form(...)):
    if not sessions.user(request):
        return login_redirect(request)
    STATE.reports.append({"txn_id": tid, "reason": reason, "at": dt.datetime.now().isoformat(timespec="seconds")})
    return view("Reported", f'<div class="notice ok" role="status">Transaction {tid} reported. '
                            f'Our fraud team will contact you within 1 business day.</div>'
                            f'<a href="/transactions">Back to transactions</a>')


@app.get("/card")
def card(request: Request):
    if not sessions.user(request):
        return login_redirect(request)
    if STATE.card_frozen:
        action = ('<form method="post" action="/card/unfreeze"><button type="submit" class="secondary">'
                  'Unfreeze card</button></form>')
    else:
        action = '<a class="button danger" href="/card/freeze">Freeze card</a>'
    return view("Card", f"""
<h1>Debit card ••••4471</h1>
<div class="card"><p>Status: <strong id="card-status">{"Frozen" if STATE.card_frozen else "Active"}</strong></p>
<p class="muted">Freezing stops new purchases and withdrawals. You can unfreeze at any time.</p>{action}</div>""")


@app.get("/card/freeze")
def freeze_confirm(request: Request):
    if not sessions.user(request):
        return login_redirect(request)
    return view("Freeze card", """
<h1>Freeze debit card ••••4471?</h1>
<div class="card"><p>New purchases and withdrawals will be declined until you unfreeze it.</p>
<form method="post" action="/card/freeze" aria-label="Confirm freeze">
<button type="submit" class="danger">Yes, freeze my card</button></form>
<a href="/card">Cancel</a></div>""")


@app.post("/card/freeze")
def freeze(request: Request):
    if not sessions.user(request):
        return login_redirect(request)
    STATE.card_frozen = True
    return view("Card frozen", '<div class="notice ok" role="status">Your debit card ••••4471 is now frozen.</div>'
                               '<a href="/accounts">Back to accounts</a>')


@app.post("/card/unfreeze")
def unfreeze(request: Request):
    if not sessions.user(request):
        return login_redirect(request)
    STATE.card_frozen = False
    return redirect("/card")


@app.get("/transfer")
def transfer_form(request: Request):
    if not sessions.user(request):
        return login_redirect(request)
    opts = "".join(f"<option>{esc(p)}</option>" for p in STATE.payees)
    return view("Transfer", f"""
<h1>Send money</h1>
<form class="card" method="post" action="/transfer" aria-label="Send money">
  <label for="payee">Payee</label><select id="payee" name="payee">{opts}</select>
  <label for="amount">Amount</label><input id="amount" name="amount" inputmode="decimal" required>
  <button type="submit">Send money</button>
</form>
<p><a href="/payees/new">Add a new payee</a></p>""")


@app.post("/transfer")
def transfer(request: Request, payee: str = Form(...), amount: float = Form(...)):
    if not sessions.user(request):
        return login_redirect(request)
    if payee not in STATE.payees or amount <= 0:
        return view("Transfer", '<div class="notice error" role="alert">Invalid payee or amount.</div>')
    STATE.add_txn(f"Transfer to {payee}", -amount, "Transfer")
    STATE.transfers.append({"payee": payee, "amount": amount})
    return view("Sent", f'<div class="notice ok" role="status">Sent {money(amount)} to {esc(payee)}.</div>')


@app.get("/payees/new")
def payee_form(request: Request):
    if not sessions.user(request):
        return login_redirect(request)
    return view("Add payee", """
<h1>Add a new payee</h1>
<form class="card" method="post" action="/payees/new" aria-label="Add payee">
  <label for="name">Payee name</label><input id="name" name="name" required>
  <label for="account">Account number</label><input id="account" name="account" required>
  <button type="submit">Add payee</button>
</form>""")


@app.post("/payees/new")
def add_payee(request: Request, name: str = Form(...), account: str = Form(...)):
    if not sessions.user(request):
        return login_redirect(request)
    STATE.payees.append(name)
    return redirect("/transfer")


@app.get("/security")
def security(request: Request):
    if not sessions.user(request):
        return login_redirect(request)
    rows = "".join(f'<tr><td>{s["when"].strftime("%Y-%m-%d %H:%M")}</td><td>{esc(s["device"])}</td>'
                   f'<td>{esc(s["location"])}</td></tr>' for s in STATE.signins)
    other = "Other devices are signed in." if STATE.other_sessions_active else "Only this device is signed in."
    return view("Security", f"""
<h1>Security settings</h1>
<section class="card" aria-label="Recent sign-ins"><h2>Recent sign-ins</h2>
<table aria-label="Recent sign-ins"><thead><tr><th scope="col">When</th><th scope="col">Device</th>
<th scope="col">Location</th></tr></thead><tbody>{rows}</tbody></table>
<p id="sessions-status">{other}</p>
<form method="post" action="/security/signout-others"><button type="submit" class="danger">Sign out all other devices</button></form>
</section>
<section class="card" aria-label="Recovery email"><h2>Recovery email</h2>
<form method="post" action="/security/recovery" aria-label="Change recovery email">
  <label for="recovery_email">Recovery email</label>
  <input id="recovery_email" name="recovery_email" type="email" value="{esc(STATE.recovery_email)}">
  <button type="submit">Save recovery email</button>
</form></section>""")


@app.post("/security/signout-others")
def signout_others(request: Request):
    if not sessions.user(request):
        return login_redirect(request)
    STATE.other_sessions_active = False
    return redirect("/security")


@app.post("/security/recovery")
def change_recovery(request: Request, recovery_email: str = Form(...)):
    if not sessions.user(request):
        return login_redirect(request)
    STATE.recovery_email = recovery_email
    return redirect("/security")
