"""All mock sites in one process, routed by hostname (every *.localhost name resolves to this machine).

    uvicorn mocksites.app:app --host :: --port 8100     (or: make mocks)

    http://localhost:8100                         admin: links, state, inject fraud/phishing, reset
    http://maplebank.localhost:8100               legit bank
    http://mail.localhost:8100                    legit webmail
    http://pizza.localhost:8100                   legit pizza shop
    http://secure-maplebankk-login.localhost:8100 scam: look-alike bank login
    http://paypa1-support.localhost:8100          scam: look-alike PayPal login
    http://pc-security-alert.localhost:8100       scam: fake virus warning
    http://refund-center.localhost:8100           scam: gift-card refund
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from starlette.applications import Starlette
from starlette.routing import Host

from . import bank, inbox, pizza, scams
from .seed import HOSTS, LEGIT, SCAMS, STATE, url
from .ui import esc

admin = FastAPI(title="Lend mock sites admin", docs_url=None, redoc_url=None)


def reset_all():
    STATE.reset()
    for s in (bank.sessions, inbox.sessions):
        s.clear()


@admin.post("/admin/reset")
def reset():
    reset_all()
    return {"ok": True, "state": STATE.summary()}


@admin.post("/admin/inject_fraud")
def inject_fraud():
    added = STATE.inject_fraud()
    return {"ok": True, "added": [{**t, "date": t["date"].isoformat()} for t in added]}


@admin.post("/admin/inject_phishing")
def inject_phishing():
    m = STATE.inject_phishing()
    return {"ok": True, "message_id": m["id"], "subject": m["subject"]}


@admin.get("/admin/state")
def state():
    return STATE.summary()


@admin.get("/", response_class=HTMLResponse)
def index():
    def links(keys):
        return "".join(f'<li><a href="{url(k)}">{esc(HOSTS[k])}</a></li>' for k in keys)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Lend mock sites</title>
<style>body{{font:18px/1.5 -apple-system,sans-serif;max-width:760px;margin:40px auto;padding:0 16px}}
button{{font:inherit;padding:8px 16px;margin:4px 8px 4px 0;cursor:pointer}} pre{{background:#f3f4f6;padding:12px;overflow:auto}}</style>
</head><body><h1>Lend mock sites</h1>
<h2>Legitimate</h2><ul>{links(LEGIT)}</ul>
<h2>Attacker (for the guard to catch)</h2><ul>{links(SCAMS)}</ul>
<h2>Demo controls</h2>
<button onclick="act('inject_fraud')">Inject fraud</button>
<button onclick="act('inject_phishing')">Inject phishing</button>
<button onclick="act('reset')">Reset everything</button>
<pre id="out"></pre>
<script>async function act(a){{const r=await fetch('/admin/'+a,{{method:'POST'}});
document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2)}}</script>
</body></html>"""


app = Starlette(routes=[
    Host(HOSTS["bank"], app=bank.app),
    Host(HOSTS["mail"], app=inbox.app),
    Host(HOSTS["pizza"], app=pizza.app),
    Host(HOSTS["bank_phish"], app=scams.bank_phish),
    Host(HOSTS["paypal_phish"], app=scams.paypal_phish),
    Host(HOSTS["techsupport"], app=scams.techsupport),
    Host(HOSTS["giftcard"], app=scams.giftcard),
    Host("{any}", app=admin),
])
