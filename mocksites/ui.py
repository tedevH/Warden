"""Tiny HTML helpers shared by the mock sites. Plain, semantic, server-rendered."""
import secrets
from html import escape as esc

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

BASE_CSS = """
*{box-sizing:border-box} body{margin:0;font:17px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#1b1f24;background:#f5f6f8}
header{display:flex;align-items:center;gap:24px;padding:14px 28px;color:#fff;background:var(--brand)}
header .logo{font-weight:800;font-size:22px;color:#fff;text-decoration:none} header nav a{color:#fff;margin-right:18px}
main{max-width:980px;margin:24px auto;padding:0 20px} h1{font-size:28px;margin:8px 0 16px}
.card{background:#fff;border:1px solid #dde1e6;border-radius:10px;padding:20px;margin-bottom:18px}
label{display:block;font-weight:600;margin:12px 0 4px} input,select,textarea{font:inherit;padding:8px 10px;width:100%;max-width:420px;border:1px solid #b9c0c8;border-radius:6px}
button,.button{font:inherit;font-weight:600;padding:9px 18px;border-radius:6px;border:0;background:var(--brand);color:#fff;cursor:pointer;text-decoration:none;display:inline-block;margin-top:14px}
button.secondary{background:#e8ebef;color:#1b1f24} button.danger{background:#b42318}
table{border-collapse:collapse;width:100%;background:#fff} th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #e3e6ea} td.amount,th.amount{text-align:right;font-variant-numeric:tabular-nums}
.neg{color:#b42318}.pos{color:#067647} .notice{padding:12px 16px;border-radius:8px;background:#fff7e0;border:1px solid #f0c36d;margin-bottom:16px}
.ok{background:#e7f6ec;border-color:#7cc596} .muted{color:#5d6670} .error{background:#fde8e7;border-color:#f29b94}
form.inline{display:inline} form.inline button{margin:0;padding:5px 12px;font-size:15px}
"""


def page(title, body, *, brand="Site", color="#1f4e8c", nav=(), extra_css=""):
    links = "".join(f'<a href="{esc(h)}">{esc(t)}</a>' for t, h in nav)
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{esc(title)} - {esc(brand)}</title>
<style>:root{{--brand:{color}}}{BASE_CSS}{extra_css}</style></head>
<body><header><a class="logo" href="/">{esc(brand)}</a><nav aria-label="Main">{links}</nav></header>
<main>{body}</main></body></html>"""
    return HTMLResponse(html)


def money(amount):
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"


class Sessions:
    """Cookie sessions for one mock site (in memory, cleared by reset)."""

    def __init__(self, cookie):
        self.cookie, self.tokens = cookie, {}

    def start(self, resp, user):
        token = secrets.token_urlsafe(16)
        self.tokens[token] = user
        resp.set_cookie(self.cookie, token, httponly=True, samesite="lax")
        return resp

    def user(self, request: Request):
        return self.tokens.get(request.cookies.get(self.cookie, ""))

    def end(self, request: Request, resp):
        self.tokens.pop(request.cookies.get(self.cookie, ""), None)
        resp.delete_cookie(self.cookie)
        return resp

    def clear(self):
        self.tokens.clear()


def redirect(url):
    return RedirectResponse(url, status_code=303)


def login_redirect(request: Request):
    return redirect(f"/login?next={request.url.path}")
