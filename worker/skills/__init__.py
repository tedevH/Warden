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


async def pizza_menu(session):
    snap = await session.goto(f"{PIZZA}/")
    return ("Menu loaded. Nothing has been ordered. Tell the person the choices and prices so they can pick.\n"
            + format_for_llm(snap))


async def pizza_checkout(session, items: list | str | None = None, item: str | None = None):
    """Add each named menu item to the cart (repeat a name for two of it), then check out."""
    import re
    names = [items] if isinstance(items, str) else list(items or [])
    if item:
        names.append(item)
    if not names:
        return "No item was named. Ask the person what they want; use pizza_menu to read them the choices."
    for name in names:
        await session.goto(f"{PIZZA}/")
        await session.click_named(rf"^Add {re.escape(name.strip())}", role="button")
    await session.goto(f"{PIZZA}/checkout")
    snap = await session.click_named(r"^Place order", role="button")
    return "Checkout finished.\n" + format_for_llm(snap)


SKILLS = {
    "read_inbox": (read_inbox, "Open Postbox Mail and list the inbox. No arguments."),
    "bank_transactions": (bank_transactions, "Open Maple Bank and show recent transactions. Args: count (int)."),
    "pizza_menu": (pizza_menu, "Read the Slice Street Pizza menu and prices without ordering. No arguments."),
    "pizza_checkout": (pizza_checkout, "Order from Slice Street Pizza with the saved address and card. Only when "
                                       "the person named exactly what they want. Args: items (list of menu item "
                                       "names as written on the menu, e.g. ['Large Cheese Pizza', '2-Liter Soda'])."),
}
