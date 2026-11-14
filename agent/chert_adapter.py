"""Everything Chert-specific lives here. CHERT_MODE=mock (default) needs no Chert access.

    capture_frame()                          latest caller video frame as JPEG/PNG bytes
    send_imessage(to, text, image_path=None)
    place_outbound_call(to, opening_line)
    show_on_call(image_path)

Sources: https://app.trychert.com/skills.md and https://docs.trychert.com/facetime/outbound, /audio-video.
Mock mode prints, appends to data/chert_mock.log, and serves frames from tests/fixtures/.

TODO(chert) list (also in README):
  1. send_imessage images: the trial "shared-messages" API documents text only. Images are skipped live.
  2. show_on_call: no documented way to show an image to the caller mid-call; falls back to send_imessage.
  3. place_outbound_call: implemented from the docs but NOT yet verified on a real line (needs CHERT_API_KEY).
  4. capture_frame: needs "caller capture" enabled on the line; without a video track it returns None.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

log = logging.getLogger("lend.chert")
API_BASE = "https://app.trychert.com/api/v1"   # the key is never sent anywhere else
MOCK_LOG = ROOT / "data" / "chert_mock.log"
FIXTURES = ROOT / "tests" / "fixtures"
_frame_source = None   # set by the live agent: () -> bytes | None


def mode():
    # live as soon as a project API key is present; otherwise calls and messages are only printed
    return os.getenv("CHERT_MODE", "live" if os.getenv("CHERT_API_KEY") else "mock").strip().lower()


def _mock(kind, **fields):
    print(f"[chert-mock] {kind}: {json.dumps(fields)[:400]}", flush=True)
    MOCK_LOG.parent.mkdir(parents=True, exist_ok=True)
    with MOCK_LOG.open("a") as f:
        f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), "kind": kind, **fields}) + "\n")
    return {"status": "mocked", "kind": kind}


def _request(method, path, body=None):
    key, project = os.getenv("CHERT_API_KEY"), os.getenv("CHERT_PROJECT_ID")
    if not key or not project:
        raise RuntimeError("CHERT_API_KEY and CHERT_PROJECT_ID are required for CHERT_MODE=live")
    headers = {"Authorization": f"Bearer {key}", "X-Chert-Project-Id": project, "Accept": "application/json"}
    data = None
    if body is not None:
        data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
    if method == "POST":
        headers["Idempotency-Key"] = f"lend-{uuid.uuid4()}"
    req = urllib.request.Request(API_BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Chert {method} {path} -> HTTP {e.code}: {e.read().decode(errors='ignore')[:300]}") from None


def _line_id():
    if os.getenv("CHERT_LINE_ID"):
        return os.environ["CHERT_LINE_ID"]
    res = _request("GET", "/lines")
    lines = res.get("lines") or res.get("data") or res if isinstance(res, dict) else res
    return lines[0]["id"]


def set_frame_source(fn):
    global _frame_source
    _frame_source = fn


def capture_frame() -> bytes | None:
    """Latest frame of the caller's camera. Mock: a fixture image ($MOCK_FRAME, default scam_letter.png)."""
    if _frame_source is not None:
        frame = _frame_source()
        if frame:
            return frame
    if mode() == "mock":
        p = FIXTURES / os.getenv("MOCK_FRAME", "scam_letter.png")
        _mock("capture_frame", fixture=p.name)
        return p.read_bytes() if p.exists() else None
    return None  # TODO(chert) 4: no caller video track on this call


def send_imessage(to, text, image_path=None):
    text = text if len(text) <= 4000 else text[:3980] + " …(cut short)"
    if mode() == "mock" or not to:
        return _mock("send_imessage", to=to, text=text, image=str(image_path) if image_path else None)
    if image_path:
        log.info("TODO(chert) 1: image not sent (text-only API): %s", image_path)
        text += "\n(I couldn't attach the picture yet.)"
    return _request("POST", "/shared-messages", {"line_id": _line_id(), "recipient": to, "text": text})


def show_on_call(image_path, to=None):
    """TODO(chert) 2: unsupported, so fall back to sending the image by iMessage."""
    return send_imessage(to or os.getenv("USER_PHONE", ""), "Here is the page I'm looking at.", image_path)


def place_outbound_call(to, opening_line):
    """FaceTime Audio `to` from the Chert line; our agent speaks `opening_line` once Chert reports bridge_ready.

    Follows docs.trychert.com/facetime/outbound: put the agent in a fresh room with its audio track published,
    mint a bridge token for that room, POST /calls, then watch the call's events for bridge_ready.
    Needs CHERT_API_KEY (facetime:write + facetime:read), CHERT_PROJECT_ID, and a phone number verified on the
    project. First proven on a real line: see README "What is verified".
    """
    if mode() == "mock" or not to:
        return _mock("place_outbound_call", to=to, opening_line=opening_line)
    import asyncio
    import datetime
    from livekit import api
    url, key, secret = (os.environ[k] for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))
    agent_name = os.getenv("AGENT_NAME", "lend-agent")
    room = f"lend-callback-{uuid.uuid4().hex[:10]}"
    bridge_identity = f"chert-bridge-{room}"

    async def prepare():
        """Dispatch the agent and wait until it has joined the room. Returns its identity.

        The agent publishes its audio the moment the bridge joins, exactly as it does on inbound calls.
        """
        lk = api.LiveKitAPI(url, key, secret)
        try:
            await lk.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=120))
            await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                agent_name=agent_name, room=room, metadata=json.dumps(
                    {"outbound": True, "opening_line": opening_line, "bridge_identity": bridge_identity})))
            for _ in range(60):
                await asyncio.sleep(0.5)
                people = (await lk.room.list_participants(api.ListParticipantsRequest(room=room))).participants
                if people:
                    return people[0].identity
            return None
        finally:
            await lk.aclose()

    async def set_ready(call_id):
        lk = api.LiveKitAPI(url, key, secret)
        try:
            await lk.room.update_room_metadata(api.UpdateRoomMetadataRequest(
                room=room, metadata=json.dumps({"chert_call": call_id, "chert_bridge_ready": True})))
        finally:
            await lk.aclose()

    agent_identity = asyncio.run(prepare())
    if not agent_identity:
        raise RuntimeError("the agent did not join the callback room; is `make agent` running?")
    bridge = (api.AccessToken(key, secret).with_identity(bridge_identity)
              .with_grants(api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True))
              .with_ttl(datetime.timedelta(minutes=30)).to_jwt())
    res = _request("POST", "/calls", {
        "direction": "outbound", "mode": "customer_managed", "line_id": _line_id(),
        "destination": to, "destination_type": "phone", "media": {"audio": True, "video": False},
        "livekit_url": url, "participant_token": bridge, "remote_participant_identity": agent_identity})
    call_id = (res.get("data") or res).get("id")
    log.info("outbound call %s allocated to %s (agent %s)", call_id, to[:5] + "…", agent_identity)
    deadline = time.time() + 90   # ringing: speak only once Chert says the call is really connected
    while call_id and time.time() < deadline:
        blob = json.dumps(_request("GET", f"/calls/{call_id}/events"))
        if "bridge_ready" in blob:
            asyncio.run(set_ready(call_id))
            log.info("outbound call %s answered", call_id)
            break
        if any(s in blob for s in ('"failed"', '"ended"', '"declined"', '"no_answer"')):
            log.info("outbound call %s was not answered", call_id)
            break
        time.sleep(2)
    return res
