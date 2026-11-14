"""Postbox (legitimate mock webmail): login, inbox list, message view, forward, delete, sent."""
import datetime as dt
import hmac

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse

from ..seed import STATE, creds
from ..ui import Sessions, esc, login_redirect, page, redirect

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
sessions = Sessions("postbox_sid")
BRAND, COLOR = "Postbox Mail", "#3b3fb6"
NAV = [("Inbox", "/inbox"), ("Sent", "/sent"), ("Sign out", "/logout")]


def view(title, body, signed_in=True):
    return page(title, body, brand=BRAND, color=COLOR, nav=NAV if signed_in else ())


def _msg(mid):
    return next((m for m in STATE.messages if m["id"] == mid and not m["deleted"]), None)


@app.get("/")
def home(request: Request):
    return redirect("/inbox" if sessions.user(request) else "/login")


@app.get("/login")
def login_form(next: str = "/inbox", error: str = ""):
    msg = '<p class="notice error" role="alert">Incorrect email or password.</p>' if error else ""
    return view("Sign in", f"""
<h1>Sign in to Postbox</h1>{msg}
<form class="card" method="post" action="/login" aria-label="Sign in">
  <input type="hidden" name="next" value="{esc(next)}">
  <label for="username">Email or username</label><input id="username" name="username" autocomplete="username" required>
  <label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>
</form>""", signed_in=False)


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), next: str = Form("/inbox")):
    user, pw = creds("mail")
    if hmac.compare_digest(username, user) and hmac.compare_digest(password, pw):
        target = next if next.startswith("/") and not next.startswith("//") else "/inbox"
        return sessions.start(redirect(target), username)
    return redirect("/login?error=1")


@app.get("/logout")
def logout(request: Request):
    return sessions.end(request, redirect("/login"))


@app.get("/inbox")
def inbox(request: Request):
    if not sessions.user(request):
        return login_redirect(request)
    msgs = sorted((m for m in STATE.messages if not m["deleted"]), key=lambda m: m["date"], reverse=True)
    rows = "".join(
        f'<tr data-message-id="{m["id"]}"><td>{"" if m["read"] else "<strong>New</strong>"}</td>'
        f'<td>{esc(m["from_name"])} &lt;{esc(m["from_addr"])}&gt;</td>'
        f'<td><a href="/message/{m["id"]}">{esc(m["subject"])}</a></td>'
        f'<td>{m["date"].strftime("%b %d, %I:%M %p")}</td></tr>' for m in msgs)
    return view("Inbox", f"""
<h1>Inbox</h1>
<table aria-label="Messages"><thead><tr><th scope="col">Status</th><th scope="col">From</th>
<th scope="col">Subject</th><th scope="col">Received</th></tr></thead><tbody>{rows}</tbody></table>""")


@app.get("/message/{mid}")
def message(request: Request, mid: int):
    if not sessions.user(request):
        return login_redirect(request)
    m = _msg(mid)
    if not m:
        return view("Not found", "<h1>Message not found</h1>")
    m["read"] = True
    return view(m["subject"], f"""
<article class="card" aria-label="Message">
  <h1>{esc(m["subject"])}</h1>
  <p><strong>From:</strong> <span id="from">{esc(m["from_name"])} &lt;{esc(m["from_addr"])}&gt;</span><br>
     <strong>Date:</strong> {m["date"].strftime("%A, %B %d at %I:%M %p")}</p>
  <div id="message-body">{m["body"]}</div>
</article>
<section class="card" aria-label="Message actions">
  <form method="post" action="/message/{mid}/forward" aria-label="Forward message">
    <label for="to">Forward to</label><input id="to" name="to" type="email" required>
    <button type="submit">Forward</button>
  </form>
  <form method="post" action="/message/{mid}/delete" aria-label="Delete message">
    <button type="submit" class="danger">Delete message</button>
  </form>
</section>
<a href="/inbox">Back to inbox</a>""")


@app.post("/message/{mid}/forward")
def forward(request: Request, mid: int, to: str = Form(...)):
    if not sessions.user(request):
        return login_redirect(request)
    m = _msg(mid)
    if not m:
        return view("Not found", "<h1>Message not found</h1>")
    STATE.sent.append({"to": to, "subject": f"Fwd: {m['subject']}", "message_id": mid,
                       "at": dt.datetime.now().isoformat(timespec="seconds")})
    return view("Sent", f'<div class="notice ok" role="status">Message forwarded to {esc(to)}.</div>'
                        f'<a href="/inbox">Back to inbox</a>')


@app.post("/message/{mid}/delete")
def delete(request: Request, mid: int):
    if not sessions.user(request):
        return login_redirect(request)
    m = _msg(mid)
    if m:
        m["deleted"] = True
    return redirect("/inbox")


@app.get("/sent")
def sent(request: Request) -> HTMLResponse:
    if not sessions.user(request):
        return login_redirect(request)
    rows = "".join(f"<tr><td>{esc(s['to'])}</td><td>{esc(s['subject'])}</td><td>{esc(s['at'])}</td></tr>"
                   for s in reversed(STATE.sent)) or '<tr><td colspan="3">Nothing sent.</td></tr>'
    return view("Sent", f"""<h1>Sent</h1><table aria-label="Sent messages"><thead><tr><th scope="col">To</th>
<th scope="col">Subject</th><th scope="col">When</th></tr></thead><tbody>{rows}</tbody></table>""")
