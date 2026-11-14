"""Task state machine + safety gate + approvals. The single source of truth for what Warden is doing.

    planning -> running -> awaiting_confirm -> running -> done | failed | cancelled

Every browser action from the worker passes through `TaskManager._gate` (policy tiers + approvals) and every
page load through `_on_page` (scam guard) before the planner model sees it.
"""
import asyncio
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass, field

from . import guard, policy
from .store import TASK_COLS, Store

log = logging.getLogger("lend.tasks")
TERMINAL = ("done", "failed", "cancelled")


@dataclass
class Task:
    id: str
    user_id: str
    goal: str
    kind: str = "task"                 # task | audit
    state: str = "planning"
    outcome: str = ""                  # ok | blocked | needs_user | ""
    step: str = ""
    narration: list = field(default_factory=list)
    screenshot: str | None = None
    summary: str = ""
    question: str = ""
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    pending: dict | None = None        # the approval being waited on
    spent: float = 0.0
    callback: bool = False             # phone the person if this finishes while they're off the call
    cancel_requested: bool = False

    def public(self):
        d = asdict(self)
        d["last_narration"] = self.narration[-1] if self.narration else ""
        d["screenshot_url"] = self.screenshot
        return d


class TaskManager:
    def __init__(self, store: Store | None = None, vault=None, planner=None, headless=True, adapter=None):
        self.store = store or Store()
        self.vault = vault
        self.planner = planner            # async (goal, session) -> worker TaskResult
        self.headless = headless
        self.adapter = adapter            # agent.chert_adapter-like module (calls + iMessage)
        self.tasks: dict[str, Task] = {}
        self.events: list[dict] = []
        self.on_call: dict[str, bool] = {}
        self.lockdown_until = 0.0         # safety box: while in the future, only looking is allowed
        self.box_cap: float | None = None  # safety box knob: can lower the spending limit, never raise it
        self.alert_at = 0.0               # last time the scam guard stopped a page (the box flashes)
        self._tick = asyncio.Event()
        self._locks: dict[str, asyncio.Lock] = {}
        self._runners: dict[str, asyncio.Task] = {}
        self.store.fail_interrupted()

    # ---------- events ----------
    def emit(self, task: Task | None, type_, text=""):
        if task:
            task.updated = time.time()
            self.store.save_task({c: getattr(task, c) for c in TASK_COLS})
        self.events.append({"seq": len(self.events), "ts": time.time(), "task_id": task.id if task else None,
                            "type": type_, "text": text, "state": task.state if task else None})
        tick, self._tick = self._tick, asyncio.Event()
        tick.set()

    async def wait_change(self, timeout=None):
        try:
            await asyncio.wait_for(self._tick.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    def narrate(self, task: Task, text: str):
        task.narration.append(text)
        task.step = text
        self.emit(task, "narration", text)

    def notify(self, user_id, text, audience="caregiver"):
        self.store.notify(user_id, audience, text)
        self.emit(None, "notification", text)
        cg = self.store.settings()["caregiver"]
        if audience == "caregiver" and self.adapter and cg.get("phone"):
            asyncio.get_running_loop().run_in_executor(None, self._safe, self.adapter.send_imessage, cg["phone"],
                                                       f"Warden alert for {self.store.settings()['profile']['name']}: {text}")

    @staticmethod
    def _safe(fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            log.warning("adapter call failed: %s", e)

    # ---------- lifecycle ----------
    def create(self, goal, user_id="margaret", kind="task", callback=False) -> Task:
        t = Task(id=uuid.uuid4().hex[:8], user_id=user_id, goal=goal, kind=kind, callback=callback)
        self.tasks[t.id] = t
        self.emit(t, "created", goal)
        self._runners[t.id] = asyncio.create_task(self._run(t))
        return t

    def get(self, tid) -> Task | None:
        return self.tasks.get(tid)

    def active(self, user_id=None):
        return [t for t in self.tasks.values() if t.state not in TERMINAL and (not user_id or t.user_id == user_id)]

    def cancel(self, tid, why="Stopped."):
        t = self.tasks.get(tid)
        if not t or t.state in TERMINAL:
            return False
        t.cancel_requested, t.pending = True, None
        t.state, t.summary = "cancelled", why
        r = self._runners.get(tid)
        if r:
            r.cancel()
        self.emit(t, "state", why)
        return True

    def kill_all(self):
        n = sum(self.cancel(t.id, "Stopped by the kill switch.") for t in list(self.tasks.values()))
        if n:
            self.notify("*", f"Kill switch used: {n} task(s) cancelled.")
        return n

    # ---------- safety box (hardware button, knob and light) ----------
    def locked(self):
        return max(0.0, self.lockdown_until - time.time())

    def lockdown(self, user_id="margaret", minutes=30.0):
        """Panic button: stop everything, refuse every action except looking, tell the caregiver, check accounts."""
        already = self.locked() > 0
        for t in list(self.tasks.values()):
            self.cancel(t.id, "Stopped: the safety button was pressed.")
        self.lockdown_until = time.time() + minutes * 60
        if not already:
            self.notify(user_id, f"Safety button pressed. Everything is locked for {minutes:g} minutes "
                                 "and Warden is checking the accounts.")
            self.create("Account check after the safety button", user_id, kind="audit", callback=True)
        self.emit(None, "lockdown", "locked")
        return {"locked_s": round(self.locked())}

    def unlock(self, source="caregiver"):
        was = self.locked() > 0
        self.lockdown_until = 0.0
        if was:
            self.notify("*", f"Lockdown cleared by {source}.")
        self.emit(None, "lockdown", "cleared")
        return {"locked_s": 0}

    def box_press(self, user_id="margaret"):
        """One button, two jobs: approve what Warden is waiting on, otherwise call for help (lock down)."""
        if self.locked() <= 0 and any(t.user_id == user_id and t.pending for t in self.tasks.values()):
            return {"did": "approve", **self.button(user_id)}
        return {"did": "lockdown", **self.lockdown(user_id)}

    def box_knob(self, raw: int):
        """Knob position 0-1023 -> a limit from $0 to the family's cap, in $5 steps. It can only lower the cap."""
        cap = float(self.store.settings()["spending_cap"])
        self.box_cap = min(cap, round(max(0, min(1023, raw)) / 1023 * cap / 5) * 5)
        self._tick.set()
        return {"limit": self.box_cap}

    def spending_limit(self):
        cap = float(self.store.settings()["spending_cap"])
        return cap if self.box_cap is None else min(cap, self.box_cap)

    def box_state(self, user_id="margaret"):
        pend = next((t.pending for t in self.tasks.values() if t.user_id == user_id and t.pending), None)
        light = ("locked" if self.locked() > 0 else "alert" if time.time() - self.alert_at < 12
                 else "approve" if pend and pend["tier"] >= 2 else "ok")
        return {"light": light, "locked_s": round(self.locked()), "limit": self.spending_limit(),
                "pending": pend["description"] if pend else None}

    # ---------- approvals ----------
    def confirm(self, tid, source):
        t = self.tasks.get(tid)
        if not t or not t.pending:
            return {"ok": False, "reason": "Nothing is waiting for approval."}
        if source not in ("voice", "button", "caregiver"):
            return {"ok": False, "reason": "unknown source"}
        t.pending["got"][source] = time.time()
        self.emit(t, "confirm", source)
        return {"ok": True, "still_needed": self._missing(t.pending)}

    def deny(self, tid, source="caregiver"):
        t = self.tasks.get(tid)
        if not t or not t.pending:
            return {"ok": False, "reason": "Nothing is waiting for approval."}
        t.pending["denied"] = source
        self.emit(t, "deny", source)
        return {"ok": True}

    def button(self, user_id):
        """A press of the person's approve button applies to whichever task is waiting for them."""
        for t in self.tasks.values():
            if t.user_id == user_id and t.state == "awaiting_confirm" and t.pending:
                return {"applied": True, "task_id": t.id, **self.confirm(t.id, "button")}
        return {"applied": False}

    @staticmethod
    def _missing(p):
        got = p["got"]
        if "caregiver" in got:
            return []
        if p["tier"] == 1:
            return [] if got else ["voice"]
        return [s for s in ("voice", "button") if s not in got]

    async def _approve(self, task: Task, c, desc, window):
        tier2 = c.tier >= 2
        task.pending = {"description": desc, "tier": c.tier, "kind": c.kind, "amount": c.amount,
                        "need": ["voice", "button"] if tier2 else ["voice"], "got": {},
                        "expires": time.time() + window}
        task.state = "awaiting_confirm"
        self.narrate(task, f"This needs your approval: {desc}. Say yes, then press your approve button."
                     if tier2 else f"I'd like to: {desc}. Is that okay? Say yes.")
        if tier2:
            self.notify(task.user_id, f"Approval requested: {desc}")
        try:
            while True:
                p = task.pending
                if p is None or task.cancel_requested:
                    return False, "cancelled"
                if p.get("denied"):
                    return False, f"denied by {p['denied']}"
                if not self._missing(p):
                    return True, "approved by " + " + ".join(sorted(p["got"]))
                left = p["expires"] - time.time()
                if left <= 0:
                    return False, "not approved in time"
                await self.wait_change(min(left, 1.0))
        finally:
            task.pending = None
            if task.state == "awaiting_confirm":
                task.state = "running"
                self.emit(task, "state")

    # ---------- safety gate (called before every browser action) ----------
    def _make_gate(self, task: Task, session):
        from worker.session import Decision

        async def gate(action):
            s = self.store.settings()
            c = policy.classify(action, s["allowlist"], session.vault.origins())
            t = action.target or {}
            el = {k: t.get(k) for k in ("role", "name", "href", "form") if t.get(k)} or None

            def decide(ok, decision, reason):
                self.store.log_action(task.id, action.kind, action.url, el, c.kind, c.tier, decision, reason)
                self.emit(task, "action", f"{decision}: {action.kind} {t.get('name', action.url)}")
                return Decision(ok, reason, c.tier, c.kind)

            if task.cancel_requested:
                return decide(False, "blocked", "The task was cancelled.")
            if c.tier == 0:
                return decide(True, "allowed", c.reason)
            if self.locked() > 0:
                return decide(False, "blocked", "Your safety button was pressed, so everything is locked. "
                                                "I can look, but I won't click, send or pay until the lock is cleared.")
            if c.tier >= 3:
                self.notify(task.user_id, f"Blocked: {c.reason} ({policy.host_of(action.url)})")
                return decide(False, "blocked", c.reason)
            desc = policy.describe(c, action)
            if c.kind == "money":
                cap = self.spending_limit()
                if c.amount is None:
                    return decide(False, "blocked", "I couldn't tell how much this would cost, so I won't pay.")
                if task.spent + c.amount > cap:
                    why = f"${c.amount:,.2f} is over the ${cap:,.2f} spending limit."
                    self.notify(task.user_id, f"Blocked payment over the limit: {desc}")
                    return decide(False, "blocked", why)
            ok, how = await self._approve(task, c, desc, float(s["confirm_window_s"]))
            if not ok:
                return decide(False, "denied", f"Not approved ({how}), so I didn't do it: {desc}")
            if c.kind == "money":
                task.spent += c.amount
            if c.tier >= 2:
                self.notify(task.user_id, f"Approved and done: {desc} ({how})")
            return decide(True, "approved", how)

        return gate

    # ---------- scam guard (called on every page load, before the planner sees the page) ----------
    def _make_on_page(self, task: Task, session):
        async def on_page(snap):
            s = self.store.settings()
            if snap.screenshot:
                task.screenshot = "/screens/" + "/".join(snap.screenshot.replace("\\", "/").split("/")[-2:])
            v = guard.check_page(snap, s["allowlist"], session.vault.origins(), self.store.seen_hosts())
            host = v.get("host")
            if host:
                self.store.mark_seen(host)
            if v["verdict"] == "safe":
                return v
            stop = v["verdict"] == "dangerous"
            self.store.log_action(task.id, "guard", snap.url, None, v["verdict"], 3 if stop else 0,
                                  "stopped" if stop else "flagged",
                                  "; ".join(r["detail"] for r in v["reasons"])[:500])
            if stop:
                self.alert_at = time.time()
                if self.store.add_finding(task.user_id, task.id, "scam_page", "high", f"Scam page blocked: {host}",
                                          v["reasons"], v["plain_explanation"], fkey=f"scam_page:{host}"):
                    self.notify(task.user_id, f"Warden stopped a scam page: {host}. {v['plain_explanation']}")
                else:
                    self.emit(task, "guard", host)
            return v

        return on_page

    # ---------- runner ----------
    async def _run(self, task: Task):
        from worker.session import BrowserSession

        lock = self._locks.setdefault(task.user_id, asyncio.Lock())
        try:
            async with lock:  # one browser profile per person, so one task at a time
                if task.cancel_requested:
                    return
                task.state = "running"
                self.emit(task, "state")
                async with BrowserSession(task.user_id, None, headless=self.headless, task_id=task.id,
                                          narrate=lambda s: self.narrate(task, s), screenshots=True) as session:
                    if self.vault is not None:
                        session.vault = self.vault
                    session.gate = self._make_gate(task, session)
                    session.on_page = self._make_on_page(task, session)
                    if task.kind == "audit":
                        from .audit import run_audit
                        task.summary = await run_audit(self, task, session)
                        task.state, task.outcome = "done", "ok"
                    else:
                        planner = self.planner
                        if planner is None:
                            from worker.browser_worker import run_task as planner
                        link = re.search(r"(?:https?://)?[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}(?::\d+)?(?:/[^\s\"'<>]*)?", task.goal, re.I)
                        r = None
                        if link:  # always look at a link the person asked about; the guard decides, not the model
                            from worker.browser_worker import TaskResult
                            from worker.session import Blocked, GuardStop
                            try:
                                await session.goto(link.group(0).rstrip(".,)"))
                            except GuardStop as g:
                                r = TaskResult(status="blocked", summary=g.verdict.get("plain_explanation", ""))
                                self.narrate(task, f"Stopped for safety: {r.summary}")
                            except Blocked:
                                pass
                        if r is None:
                            r = await planner(task.goal, session)
                        task.summary, task.question = r.summary, r.question
                        if r.status == "done":
                            task.state, task.outcome = "done", "ok"
                        elif r.status == "needs_user":
                            task.state, task.outcome, task.summary = "done", "needs_user", r.question
                        elif r.status == "blocked":
                            task.state, task.outcome = "done", "blocked"
                        else:
                            task.state = "failed"
                            task.summary = r.summary or "I couldn't finish that."
        except asyncio.CancelledError:
            task.state = "cancelled"
            task.summary = task.summary or "Stopped."
        except Exception as e:
            log.exception("task %s failed", task.id)
            task.state, task.summary = "failed", f"Something went wrong: {e.__class__.__name__}."
        finally:
            task.pending = None
            self.emit(task, "state", task.summary)
            self._after(task)

    def _after(self, task: Task):
        """If the person isn't on a call when a voice task ends, phone them with the result."""
        if not (task.callback and task.state in ("done", "failed") and self.adapter):
            return
        if self.on_call.get(task.user_id):
            return
        phone = self.store.settings()["profile"].get("phone", "")
        line = f"Hi, it's Warden. {task.summary}"
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, self._safe, self.adapter.place_outbound_call, phone, line)
        loop.run_in_executor(None, self._safe, self.adapter.send_imessage, phone, line)
