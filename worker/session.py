"""BrowserSession: one persistent Playwright Chromium context per user. Every action goes through a gate.

The gate is a callable `async (Action) -> Decision`. Milestone 2 ships `ConsoleGate` (a simple
stand-in); milestone 3 replaces it with the orchestrator's policy + scam guard.
"""
import asyncio
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from playwright.async_api import async_playwright

from .observe import Snapshot, snapshot
from orchestrator.vault import Vault

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


@dataclass
class Action:
    kind: str                 # goto | click | type | select | login | back
    url: str                  # page the action happens on (for goto: the destination)
    target: dict | None = None
    text: str | None = None   # typed text / selected option (never a password)
    page_text: str = ""       # visible text of the page, for classification


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    tier: int = 0
    classification: str = ""


Gate = Callable[[Action], Awaitable[Decision]]
RISKY = re.compile(r"place order|pay|send|forward|delete|freeze|transfer|add payee|report|save recovery|sign out all", re.I)


class ConsoleGate:
    """Milestone-2 stand-in gate: never types into password fields; asks y/n on the terminal for risky clicks."""

    def __init__(self, auto_yes=False):
        self.auto_yes = auto_yes

    async def __call__(self, a: Action) -> Decision:
        t = a.target or {}
        if a.kind == "type" and t.get("role") == "password":
            return Decision(False, "Warden never types passwords. Use the login tool, which fills saved logins.", 3, "credential")
        if a.kind == "click" and RISKY.search(f'{t.get("name", "")} {t.get("form", "")}'):
            if self.auto_yes:
                return Decision(True, "auto-approved (--yes)", 2, "risky")
            ans = await asyncio.to_thread(input, f'\n  APPROVE? click "{t.get("name")}" on {a.url} [y/N] ')
            ok = ans.strip().lower().startswith("y")
            return Decision(ok, "approved at console" if ok else "denied at console", 2, "risky")
        return Decision(True, "", 0, a.kind)


class Blocked(Exception):
    pass


class GuardStop(Exception):
    """The scam guard judged the current page dangerous. The task must stop."""

    def __init__(self, verdict: dict):
        super().__init__(verdict.get("plain_explanation") or "dangerous page")
        self.verdict = verdict


class BrowserSession:
    def __init__(self, user="margaret", gate: Gate | None = None, headless=True,
                 narrate: Callable[[str], None] = print, task_id="task", on_page=None, screenshots=False):
        self.user, self.gate, self.headless = user, gate or ConsoleGate(), headless
        self.narrate, self.task_id = narrate, task_id
        self.screenshots = screenshots
        self.on_page = on_page  # async (Snapshot) -> guard verdict dict | None; runs before the planner sees a page
        self.vault = Vault()
        self.log: list[dict] = []
        self.last: Snapshot | None = None
        self._pw = self.ctx = self.page = None

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        profile = DATA / "profiles" / self.user
        profile.mkdir(parents=True, exist_ok=True)
        self.ctx = await self._pw.chromium.launch_persistent_context(
            str(profile), headless=self.headless, viewport={"width": 1280, "height": 900})
        self.ctx.set_default_timeout(int(os.getenv("ACTION_TIMEOUT_MS", "8000")))
        self.page = self.ctx.pages[0] if self.ctx.pages else await self.ctx.new_page()
        return self

    async def __aexit__(self, *exc):
        if self.ctx:
            await self.ctx.close()
        if self._pw:
            await self._pw.stop()

    # ---- observation ----
    async def observe(self, screenshot=False) -> Snapshot:
        shots = DATA / "screens" / self.task_id if (screenshot or self.screenshots) else None
        self.last = await snapshot(self.page, shots)
        if self.on_page:
            verdict = await self.on_page(self.last)
            self.last.guard = verdict
            if verdict and verdict.get("verdict") == "dangerous":
                await self.page.goto("about:blank")  # close the dangerous page
                raise GuardStop(verdict)
        return self.last

    async def screenshot(self) -> str:
        return (await self.observe(screenshot=True)).screenshot

    # ---- gated actions ----
    async def _check(self, a: Action):
        d = await self.gate(a)
        self.log.append({"action": asdict(a) | {"page_text": None}, "decision": asdict(d)})
        if not d.allowed:
            raise Blocked(d.reason or "blocked by safety gate")
        return d

    def _locator(self, ref):
        return self.page.locator(f'[data-lend-ref="{ref}"]')

    def _target(self, ref):
        snap = self.last
        el = snap.element(ref) if snap else None
        if not el:
            raise ValueError(f"No element {ref} on the current page. Call read_page to refresh refs.")
        return el

    async def _settle(self):
        try:
            await self.page.wait_for_load_state("load", timeout=5000)
        except Exception:
            pass

    async def goto(self, url):
        if not re.match(r"^https?://", url):
            url = "http://" + url
        await self._check(Action("goto", url, page_text=""))
        self.narrate(f"Opening {url}")
        await self.page.goto(url, wait_until="domcontentloaded")
        return await self.observe()

    async def back(self):
        await self._check(Action("back", self.page.url))
        await self.page.go_back()
        return await self.observe()

    async def click(self, ref):
        el = self._target(ref)
        fields = "\n".join(f'FIELD {e["name"]}={e.get("value", "")}' for e in self.last.elements
                           if e["role"] == "textbox" and e.get("form") == el.get("form") and e.get("value"))
        await self._check(Action("click", self.page.url, el, page_text=f"{fields}\n{self.last.text}"))
        self.narrate(f'Clicking "{el["name"]}"')
        await self._locator(ref).click()
        await self._settle()
        return await self.observe()

    async def type(self, ref, text):
        el = self._target(ref)
        await self._check(Action("type", self.page.url, el, text, page_text=self.last.text))
        self.narrate(f'Typing into "{el["name"]}"')
        await self._locator(ref).fill(text)
        return await self.observe()

    async def select(self, ref, option):
        el = self._target(ref)
        await self._check(Action("select", self.page.url, el, option, page_text=self.last.text))
        self.narrate(f'Choosing "{option}"')
        await self._locator(ref).select_option(label=option)
        return await self.observe()

    async def click_named(self, pattern, role=None):
        snap = self.last or await self.observe()
        el = snap.find(pattern, role)
        if not el:
            raise ValueError(f"Nothing matching {pattern!r} on {snap.url}")
        return await self.click(el["ref"])

    async def login(self):
        """Fill the login form from the vault, only if this exact origin has a saved login."""
        snap = self.last or await self.observe()
        if not snap.has_password_field:
            raise ValueError("There is no login form on this page.")
        cred = self.vault.get(snap.origin)
        if cred is None:
            await self._check(Action("login", snap.url, {"role": "password", "name": "login form"},
                                     page_text=snap.text))
            raise Blocked(f"No saved login for {snap.origin}. Warden only signs in on the exact site a login "
                          f"was saved for, so it will not enter a password here.")
        pw_el = next(e for e in snap.elements if e["role"] == "password")
        await self._check(Action("login", snap.url, pw_el, page_text=snap.text))
        user_el = next((e for e in snap.elements if e["role"] == "textbox" and e.get("form") == pw_el.get("form")
                        and re.search(r"user|email|login", e["name"], re.I)), None)
        self.narrate(f"Signing in to {snap.host} with your saved login")
        if user_el:
            await self._locator(user_el["ref"]).fill(cred[0])
        await self._locator(pw_el["ref"]).fill(cred[1])
        await self._locator(pw_el["ref"]).press("Enter")
        await self._settle()
        snap = await self.observe()
        if snap.has_password_field:
            raise Blocked("The saved login was not accepted.")
        return snap
