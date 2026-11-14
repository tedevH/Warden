"""Scripted flows for the demo tasks. They use the same gated BrowserSession actions as the general loop.

Each skill: async (session, **args) -> str (a plain-language result; page text inside it is untrusted).
"""
import os

from ..observe import format_for_llm

PORT = os.getenv("MOCK_PORT", "8100")
BANK = f"http://maplebank.localhost:{PORT}"
MAIL = f"http://mail.localhost:{PORT}"
PIZZA = f"http://pizza.localhost:{PORT}"


async def _signed_in(session, url):
    snap = await session.goto(url)
    if snap.has_password_field:
        snap = await session.login()
        if not snap.url.startswith(url.split("?")[0]):
            snap = await session.goto(url)
    return snap


async def read_inbox(session):
    snap = await _signed_in(session, f"{MAIL}/inbox")
    return "Inbox loaded.\n" + format_for_llm(snap)


async def bank_transactions(session, count: int = 10):
    count = max(1, min(int(count), 100))
    snap = await _signed_in(session, f"{BANK}/transactions?limit={count}")
    return f"Last {count} transactions loaded.\n" + format_for_llm(snap)


async def pizza_checkout(session, item: str = "Large Pepperoni"):
    await session.goto(f"{PIZZA}/")
    await session.click_named(rf"^Add {item}", role="button")
    await session.goto(f"{PIZZA}/checkout")
    snap = await session.click_named(r"^Place order", role="button")
    return "Checkout finished.\n" + format_for_llm(snap)


SKILLS = {
    "read_inbox": (read_inbox, "Open Postbox Mail and list the inbox. No arguments."),
    "bank_transactions": (bank_transactions, "Open Maple Bank and show recent transactions. Args: count (int)."),
    "pizza_checkout": (pizza_checkout, "Order one item from Slice Street Pizza with the saved address and card. "
                                       "Args: item (menu item name, e.g. 'Large Pepperoni')."),
}
