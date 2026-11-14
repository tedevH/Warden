"""Slice Street Pizza (legitimate mock): menu, cart, delivery address, saved test card, checkout, confirmation."""
import datetime as dt
import secrets

from fastapi import FastAPI, Form, Request

from ..seed import DELIVERY_FEE, MENU, SAVED_ADDRESS, SAVED_CARD, STATE, TAX_RATE
from ..ui import esc, money, page, redirect

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
BRAND, COLOR = "Slice Street Pizza", "#b3261e"
NAV = [("Menu", "/"), ("Cart", "/cart")]
COOKIE = "slice_cart"


def view(title, body):
    return page(title, body, brand=BRAND, color=COLOR, nav=NAV)


def cart_for(request):
    cid = request.cookies.get(COOKIE)
    return cid, STATE.carts.setdefault(cid, {}) if cid else {}


def with_cart_cookie(request, resp):
    if not request.cookies.get(COOKIE):
        resp.set_cookie(COOKIE, secrets.token_urlsafe(12), httponly=True, samesite="lax")
    return resp


def totals(cart):
    items = [(next(i for i in MENU if i["id"] == k), q) for k, q in cart.items() if q > 0]
    subtotal = round(sum(i["price"] * q for i, q in items), 2)
    tax = round(subtotal * TAX_RATE, 2)
    total = round(subtotal + tax + (DELIVERY_FEE if items else 0), 2)
    return items, subtotal, tax, total


@app.get("/")
def menu(request: Request):
    cards = "".join(f"""
<section class="card" aria-label="{esc(i['name'])}"><h2>{esc(i['name'])}</h2><p>{esc(i['desc'])}</p>
<p><strong>{money(i['price'])}</strong></p>
<form method="post" action="/cart/add"><input type="hidden" name="item_id" value="{i['id']}">
<button type="submit">Add {esc(i['name'])} to cart</button></form></section>""" for i in MENU)
    return with_cart_cookie(request, view("Menu", f"<h1>Menu</h1>{cards}"))


@app.post("/cart/add")
def add(request: Request, item_id: str = Form(...)):
    if not any(i["id"] == item_id for i in MENU):
        return view("Error", '<div class="notice error" role="alert">Unknown item.</div>')
    cid = request.cookies.get(COOKIE) or secrets.token_urlsafe(12)
    cart = STATE.carts.setdefault(cid, {})
    cart[item_id] = cart.get(item_id, 0) + 1
    resp = redirect("/cart")
    resp.set_cookie(COOKIE, cid, httponly=True, samesite="lax")
    return resp


@app.post("/cart/remove")
def remove(request: Request, item_id: str = Form(...)):
    _, cart = cart_for(request)
    cart.pop(item_id, None)
    return redirect("/cart")


@app.get("/cart")
def cart(request: Request):
    _, c = cart_for(request)
    items, subtotal, tax, total = totals(c)
    if not items:
        return with_cart_cookie(request, view("Cart", '<h1>Your cart</h1><p>Your cart is empty.</p>'
                                                       '<a class="button" href="/">Back to menu</a>'))
    rows = "".join(f"""<tr><td>{esc(i['name'])}</td><td>{q}</td><td class="amount">{money(i['price'] * q)}</td>
<td><form class="inline" method="post" action="/cart/remove"><input type="hidden" name="item_id" value="{i['id']}">
<button type="submit" class="secondary">Remove</button></form></td></tr>""" for i, q in items)
    return view("Cart", f"""
<h1>Your cart</h1>
<table aria-label="Cart"><thead><tr><th scope="col">Item</th><th scope="col">Qty</th><th scope="col" class="amount">Price</th>
<th scope="col">Action</th></tr></thead><tbody>{rows}</tbody></table>
<p>Subtotal {money(subtotal)}</p>
<a class="button" href="/checkout">Continue to checkout</a>""")


@app.get("/checkout")
def checkout(request: Request):
    _, c = cart_for(request)
    items, subtotal, tax, total = totals(c)
    if not items:
        return redirect("/cart")
    lines = "".join(f"<li>{q} × {esc(i['name'])}</li>" for i, q in items)
    return view("Checkout", f"""
<h1>Checkout</h1>
<form class="card" method="post" action="/checkout" aria-label="Checkout">
  <h2>Order</h2><ul>{lines}</ul>
  <label for="address">Delivery address</label><input id="address" name="address" value="{esc(SAVED_ADDRESS)}" required>
  <label for="instructions">Delivery instructions</label><input id="instructions" name="instructions" placeholder="Optional">
  <h2>Payment</h2><p id="payment">Saved card: {esc(SAVED_CARD)}</p>
  <p>Subtotal {money(subtotal)}<br>Tax {money(tax)}<br>Delivery {money(DELIVERY_FEE)}<br>
  <strong>Total <span id="order-total">{money(total)}</span></strong></p>
  <button type="submit">Place order for {money(total)}</button>
</form>""")


@app.post("/checkout")
def place_order(request: Request, address: str = Form(...), instructions: str = Form("")):
    cid, c = cart_for(request)
    items, subtotal, tax, total = totals(c)
    if not items:
        return redirect("/cart")
    eta = (dt.datetime.now() + dt.timedelta(minutes=35)).strftime("%I:%M %p").lstrip("0")
    order = {"number": f"SS-{1040 + len(STATE.orders)}", "items": {i["id"]: q for i, q in items},
             "total": total, "address": address, "eta": eta,
             "at": dt.datetime.now().isoformat(timespec="seconds")}
    STATE.orders.append(order)
    STATE.carts.pop(cid, None)
    return view("Order confirmed", f"""
<div class="notice ok" role="status"><h1>Order confirmed</h1>
<p>Order number <strong id="order-number">{order['number']}</strong>. Total {money(total)} charged to your saved card.</p>
<p>Estimated delivery: <strong id="eta">{eta}</strong> (about 35 minutes) to {esc(address)}.</p></div>""")
