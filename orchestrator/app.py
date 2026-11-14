"""Warden orchestrator: task API, safety gate, events, caregiver dashboard, approve-button page.

    python -m orchestrator            (make orchestrator)   http://127.0.0.1:8200

Listens on loopback only. The voice agent, harness, dashboard and button page all talk to this.
"""
import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

from agent import chert_adapter  # noqa: E402
from orchestrator.store import Store  # noqa: E402
from orchestrator.tasks import TERMINAL, TaskManager  # noqa: E402

logging.basicConfig(level=logging.INFO, format="[%(name)s %(asctime)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("lend.app")
PORT = int(os.getenv("ORCH_PORT", "8200"))
AUDIT_INTERVAL_S = float(os.getenv("AUDIT_INTERVAL_S", "0"))
SCREENS = ROOT / "data" / "screens"
SCREENS.mkdir(parents=True, exist_ok=True)
tm: TaskManager | None = None


def make_app(manager: TaskManager | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        global tm
        tm = manager or TaskManager(Store(), headless=os.getenv("HEADED", "0") != "1", adapter=chert_adapter)
        loop = None
        if AUDIT_INTERVAL_S > 0 and manager is None:
            async def watch():
                while True:
                    await asyncio.sleep(AUDIT_INTERVAL_S)
                    if not tm.active("margaret"):
                        tm.create("Account check", "margaret", kind="audit")
            loop = asyncio.create_task(watch())
        yield
        if loop:
            loop.cancel()
        tm.kill_all()

    app = FastAPI(title="Warden orchestrator", lifespan=lifespan)
    app.mount("/screens", StaticFiles(directory=str(SCREENS)), name="screens")

    def task_or_404(tid):
        t = tm.get(tid)
        if not t:
            raise HTTPException(404, "No such task")
        return t

    @app.get("/")
    async def dashboard():
        return FileResponse(ROOT / "dashboard" / "index.html")

    @app.get("/button")
    async def button_page():
        return FileResponse(ROOT / "dashboard" / "button.html")

    @app.post("/tasks")
    async def create_task(payload: dict = Body(...)):
        goal = (payload.get("goal") or "").strip()
        if not goal:
            raise HTTPException(400, "goal is required")
        t = tm.create(goal[:500], payload.get("user_id", "margaret"), callback=bool(payload.get("callback")))
        return {"id": t.id, "state": t.state}

    @app.get("/tasks/{tid}")
    async def get_task(tid: str):
        return task_or_404(tid).public()

    @app.get("/tasks/{tid}/events")
    async def task_events(tid: str):
        task_or_404(tid)

        async def stream():
            i = 0
            while True:
                while i < len(tm.events):
                    e = tm.events[i]
                    i += 1
                    if e["task_id"] == tid:
                        yield f"data: {json.dumps(e)}\n\n"
                if tm.get(tid).state in TERMINAL:
                    return
                await tm.wait_change(15)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/tasks/{tid}/confirm")
    async def confirm(tid: str, payload: dict = Body(...)):
        task_or_404(tid)
        return tm.confirm(tid, payload.get("source", ""))

    @app.post("/tasks/{tid}/deny")
    async def deny(tid: str, payload: dict = Body(default={})):
        task_or_404(tid)
        return tm.deny(tid, payload.get("source", "caregiver"))

    @app.post("/tasks/{tid}/cancel")
    async def cancel(tid: str):
        task_or_404(tid)
        return {"cancelled": tm.cancel(tid)}

    @app.post("/audit")
    async def audit(payload: dict = Body(default={})):
        t = tm.create("Account check", payload.get("user_id", "margaret"), kind="audit",
                      callback=bool(payload.get("callback")))
        return {"id": t.id, "state": t.state}

    @app.post("/button")
    async def button(payload: dict = Body(default={})):
        return tm.button(payload.get("user_id", "margaret"))

    @app.get("/pending")
    async def pending(user_id: str = "margaret"):
        return [{"task_id": t.id, **t.pending} for t in tm.tasks.values()
                if t.user_id == user_id and t.pending]

    @app.post("/presence")
    async def presence(payload: dict = Body(...)):
        tm.on_call[payload.get("user_id", "margaret")] = bool(payload.get("on_call"))
        return {"ok": True}

    @app.post("/kill")
    async def kill():
        return {"cancelled": tm.kill_all()}

    @app.get("/findings")
    async def findings():
        return tm.store.findings()

    @app.get("/actions")
    async def actions(task_id: str | None = None):
        return tm.store.actions(task_id)

    @app.get("/settings")
    async def get_settings():
        return tm.store.settings()

    @app.post("/settings")
    async def set_settings(payload: dict = Body(...)):
        try:
            return tm.store.update_settings(payload)
        except KeyError as e:
            raise HTTPException(400, f"unknown setting {e}")

    @app.post("/admin/reset")
    async def reset():
        tm.kill_all()
        tm.tasks.clear()
        tm.store.wipe()
        return {"ok": True}

    @app.get("/state")
    async def state():
        """Everything the dashboard needs, in one poll."""
        tasks = sorted(tm.tasks.values(), key=lambda t: t.created, reverse=True)[:15]
        return {"tasks": [t.public() for t in tasks],
                "pending": [{"task_id": t.id, "goal": t.goal, **t.pending} for t in tasks if t.pending],
                "findings": tm.store.findings(40), "actions": tm.store.actions(limit=80),
                "notifications": tm.store.notifications(20), "settings": tm.store.settings(),
                "on_call": tm.on_call, "chert_mode": chert_adapter.mode()}

    return app


app = make_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
