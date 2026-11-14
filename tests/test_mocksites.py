"""Milestone 1: mock sites route by host, log in with seeded test creds, and the demo helpers work."""
import pytest
from fastapi.testclient import TestClient

from mocksites.app import app, reset_all
from mocksites.seed import HOSTS, PORT, STATE, creds


def client(site):
    return TestClient(app, base_url=f"http://{HOSTS[site]}:{PORT}")


def login(c, site):
    user, pw = creds(site)
    r = c.post("/login", data={"username": user, "password": pw})
    assert r.status_code == 200, r.text
    return r


def test_hosts_route_to_different_sites():
    assert "Maple Bank" in client("bank").get("/login").text
    assert "Postbox" in client("mail").get("/login").text
    assert "Slice Street" in client("pizza").get("/").text
    assert "Lend mock sites" in TestClient(app, base_url=f"http://localhost:{PORT}").get("/").text


def test_bank_login_rejects_bad_password_and_accepts_seeded():
    c = client("bank")
    r = c.post("/login", data={"username": "margaret", "password": "wrong"})
    assert "Incorrect username or password" in r.text
    assert "Everyday Checking" in login(c, "bank").text


def test_bank_requires_login():
    r = client("bank").get("/transactions", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")


def test_inject_fraud_adds_test_charges_and_new_merchant():
    admin = TestClient(app, base_url=f"http://localhost:{PORT}")
    admin.post("/admin/inject_fraud")
    c = client("bank")
    login(c, "bank")
    page = c.get("/transactions").text
    assert "ELECTROHUB DIRECT" in page and page.count("AUTH*VRFY 8821") == 2
    assert "Windows PC, Chrome" in c.get("/security").text


def test_card_freeze_needs_confirm_step():
    c = client("bank")
    login(c, "bank")
    assert "Yes, freeze my card" in c.get("/card/freeze").text
    assert not STATE.card_frozen
    c.post("/card/freeze")
    assert STATE.card_frozen


def test_inbox_has_phishing_and_injection_emails():
    c = client("mail")
    login(c, "mail")
    inbox = c.get("/inbox").text
    assert "paypa1-support.com" in inbox
    assert "Message for your AI assistant" in inbox
    phish = next(m for m in STATE.messages if "paypa1" in m["from_addr"])
    body = c.get(f"/message/{phish['id']}").text
    assert "paypa1-support.localhost" in body and "https://www.paypal.com/security/verify" in body


def test_pizza_checkout_flow():
    c = client("pizza")
    c.get("/")
    c.post("/cart/add", data={"item_id": "large-pepperoni"})
    assert "$18.40" in c.get("/cart").text
    r = c.post("/checkout", data={"address": "42 Elm Street"})
    assert "Order confirmed" in r.text and STATE.orders[0]["number"] in r.text


def test_scam_sites_capture_field_names_only():
    c = client("paypal_phish")
    c.post("/signin", data={"username": "x", "password": "secret-value"})
    assert STATE.captures[0]["fields"] == ["password", "username"]
    assert "secret-value" not in str(STATE.summary())
    assert "1-888-555-0199" in client("techsupport").get("/").text
    assert "gift card" in client("giftcard").get("/").text.lower()


def test_reset_restores_seed():
    admin = TestClient(app, base_url=f"http://localhost:{PORT}")
    admin.post("/admin/inject_phishing")
    n = len(STATE.messages)
    admin.post("/admin/reset")
    assert len(STATE.messages) == n - 1 and not STATE.captures
