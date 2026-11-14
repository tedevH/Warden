"""Warden voice agent: a LiveKit agent that answers the Chert FaceTime line.

    terminal 1:  make orchestrator        (tasks, safety gate, dashboard)
    terminal 2:  make agent               (this file)
    terminal 3:  make chert               (chert dev: connects the line to this agent)

Voice runs on LiveKit Inference (STT -> Grok -> TTS) with the LIVEKIT_* values in .env.local.
All real work goes through the orchestrator via agent/tools.py.

Chert rules followed (chert guide agent): register with AGENT_NAME; join at once but wait for the caller
before starting a model session; greet once on room metadata {"chert_bridge_ready": true}; one audio track.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)
os.environ.setdefault("CHERT_MODE", "live" if os.getenv("CHERT_API_KEY") else "mock")

from livekit import agents, rtc  # noqa: E402
from livekit.agents import (Agent, AgentServer, AgentSession, RunContext, TurnHandlingOptions,  # noqa: E402
                            function_tool, inference, room_io)
from livekit.agents.utils import images  # noqa: E402

from agent import chert_adapter  # noqa: E402
from agent.face import Face  # noqa: E402
from agent.prompts import GREETING, INSTRUCTIONS  # noqa: E402
from agent.tools import LendTools  # noqa: E402

log = logging.getLogger("lend.agent")
AGENT_NAME = os.getenv("AGENT_NAME", "lend-agent")


class Warden(Agent):
    def __init__(self, tools: LendTools):
        super().__init__(instructions=INSTRUCTIONS)
        self.t = tools

    @function_tool()
    async def start_task(self, context: RunContext, goal: str) -> str:
        """Do something on a website for the caller: email, bank, ordering food, opening a link.

        Args:
            goal: What to do, in plain words, e.g. "read my inbox".
        """
        return await self.t.start_task(goal)

    @function_tool()
    async def confirm(self, context: RunContext) -> str:
        """Record the caller's spoken yes for the approval you just read out. Only after they say yes."""
        return await self.t.confirm()

    @function_tool()
    async def wait_for_approval(self, context: RunContext) -> str:
        """After asking the caller to press their approve button, wait until they press it."""
        return await self.t.wait_for_approval()

    @function_tool()
    async def cancel_task(self, context: RunContext) -> str:
        """Stop whatever Warden is doing right now. Use when the caller says stop or cancel."""
        return await self.t.cancel()

    @function_tool()
    async def check_accounts(self, context: RunContext) -> str:
        """Review the caller's bank and email for unusual charges, new sign-ins and scam emails."""
        return await self.t.check_accounts()

    @function_tool()
    async def read_paper(self, context: RunContext) -> str:
        """Look at a letter, text or screen the caller is holding up to the camera and say if it's a scam."""
        return await self.t.read_paper()

    @function_tool()
    async def send_screenshot(self, context: RunContext) -> str:
        """Text the caller a large, high-contrast picture of the page Warden is on (for low vision)."""
        return await self.t.send_screenshot()


def bridge_ready(metadata: str | None) -> bool:
    try:
        return json.loads(metadata or "{}").get("chert_bridge_ready") is True
    except (ValueError, AttributeError):
        return False


server = AgentServer()


@server.rtc_session(agent_name=AGENT_NAME)
async def entry(ctx: agents.JobContext):
    await ctx.connect(auto_subscribe=agents.AutoSubscribe.SUBSCRIBE_ALL)
    try:
        caller = await ctx.wait_for_participant()  # Chert keeps a warm room; don't spend until a caller is here
    except RuntimeError:
        log.info("room closed before a caller joined (warm room or doctor check)")
        return
    log.info("caller joined: %s", caller.identity)
    face = Face()
    await face.publish(ctx.room)  # FaceTime Video waits on a holding screen until the agent publishes video
    log.info("face video published")
    if os.getenv("LEND_LINE_TEST") == "1":
        from agent import linetest
        await linetest.run(ctx, caller, face)
        return
    try:
        opening = json.loads(ctx.job.metadata or "{}").get("opening_line")
    except ValueError:
        opening = None

    if os.getenv("LEND_VOICE_MODE", "grok-voice") == "grok-voice":
        # Grok hears the caller and speaks back itself (xAI Grok Voice via LiveKit Inference).
        session = AgentSession(llm=inference.RealtimeModel(
            model=os.getenv("LEND_GROK_VOICE_MODEL", "xai/grok-voice-3.0"),
            voice=os.getenv("LEND_GROK_VOICE", "eve")))
        realtime = True
    else:
        session = AgentSession(
            stt=inference.STT(model=os.getenv("LEND_STT", "assemblyai/universal-3-6-pro"), language="en"),
            llm=inference.LLM(model=os.getenv("LEND_VOICE_LLM", "xai/grok-4.3")),
            tts=inference.TTS(model=os.getenv("LEND_TTS", "fishaudio/s2.1-pro"),
                              voice=os.getenv("LEND_TTS_VOICE", "fa4c9eb3dccc4806b382b40d61c6b10a")),
            turn_handling=TurnHandlingOptions(turn_detection=inference.TurnDetector()),
        )
        realtime = False
    log.info("voice: %s", "Grok Voice (speech-to-speech)" if realtime else "STT -> Grok -> TTS")

    # Call diagnostics: one INFO line per thing heard, said, or gone wrong.
    session.on("user_state_changed", lambda ev: log.info("CALLER %s", ev.new_state))

    def on_agent_state(ev):
        log.info("WARDEN %s", ev.new_state)
        face.state = ev.new_state if ev.new_state in ("listening", "thinking", "speaking") else "listening"

    def on_item(ev):
        if getattr(ev.item, "role", "") == "assistant" and ev.item.text_content:
            face.caption = ev.item.text_content
            if any(k in ev.item.text_content.lower() for k in ("scam", "fake", "blocked", "don't call", "do not call")):
                face.alert = True

    session.on("agent_state_changed", on_agent_state)
    session.on("conversation_item_added", on_item)
    session.on("user_input_transcribed",
               lambda ev: ev.is_final and log.info("HEARD: %r", ev.transcript))
    session.on("conversation_item_added",
               lambda ev: getattr(ev.item, "role", "") == "assistant" and log.info("SAID: %r", ev.item.text_content))
    session.on("error", lambda ev: log.error("SESSION ERROR from %s: %s", type(ev.source).__name__, ev.error))
    session.on("close", lambda ev: log.info("SESSION CLOSED: %s", ev.reason))

    # Grok Voice speaks for itself; only the classic pipeline can inject exact lines mid-task.
    tools = LendTools(say=(lambda text: None) if realtime else (lambda text: session.say(text, allow_interruptions=True)))
    try:
        profile = (await tools.settings())["profile"]
    except Exception:
        profile = {}
        log.warning("orchestrator not reachable at %s: start it with `make orchestrator`", tools.base)
    deaf = "deaf" in profile.get("accessibility", []) and profile.get("phone")

    def on_narration(line):
        face.caption = line
        if line.startswith(("Stopped for safety", "Blocked")):
            face.alert = True
        if deaf:
            return asyncio.to_thread(chert_adapter.send_imessage, profile["phone"], line)

    tools.on_narration = on_narration

    # Caller camera (FaceTime Video + caller capture enabled on the line): keep the newest frame for read_paper.
    latest: dict = {}

    async def watch(track):
        async for ev in rtc.VideoStream(track):
            latest["frame"] = ev.frame

    for pub in caller.track_publications.values():
        log.info("CALLER TRACK: name=%r kind=%s source=%s muted=%s", pub.name, pub.kind, pub.source, pub.muted)

    async def audio_level(track, name):
        """Diagnostics: log how loud each caller audio track is, every 2 s."""
        import numpy as np
        peak, n, last = 0.0, 0, 0.0
        async for ev in rtc.AudioStream(track):
            data = np.frombuffer(ev.frame.data, dtype=np.int16)
            if data.size:
                peak = max(peak, float(np.abs(data).max()) / 32768)
            n += 1
            now = asyncio.get_running_loop().time()
            if now - last >= 2:
                log.info("CALLER AUDIO %r: peak %.3f over %d frames", name, peak, n)
                peak, n, last = 0.0, 0, now

    def on_track(track, _pub, participant):
        if participant.identity == caller.identity:
            log.info("CALLER TRACK SUBSCRIBED: name=%r kind=%s source=%s", _pub.name, track.kind, _pub.source)
        if track.kind == rtc.TrackKind.KIND_AUDIO and participant.identity == caller.identity:
            latest.setdefault("audio", []).append(asyncio.create_task(audio_level(track, _pub.name)))
        if track.kind == rtc.TrackKind.KIND_VIDEO and participant.identity == caller.identity:
            log.info("caller video track subscribed")
            latest["task"] = asyncio.create_task(watch(track))

    ctx.room.on("track_subscribed", on_track)
    for pub in caller.track_publications.values():
        if pub.track:
            on_track(pub.track, pub, caller)
    chert_adapter.set_frame_source(
        lambda: images.encode(latest["frame"], images.EncodeOptions(format="JPEG")) if latest.get("frame") else None)

    await tools.presence(True)

    async def on_end():
        face.stop()
        chert_adapter.set_frame_source(None)
        if latest.get("task"):
            latest["task"].cancel()
        for t in latest.get("audio", []):
            t.cancel()
        await tools.presence(False)

    ctx.add_shutdown_callback(on_end)
    await session.start(
        room=ctx.room, agent=Warden(tools),
        room_options=room_io.RoomOptions(participant_identity=caller.identity, close_on_disconnect=True),
    )

    greeted = asyncio.Event()

    def maybe_greet(*_):
        if not greeted.is_set() and bridge_ready(ctx.room.metadata):
            greeted.set()
            log.info("FaceTime ready: greeting")
            if opening:
                if realtime:
                    session.generate_reply(instructions=f"Say exactly this to the caller: {opening}")
                else:
                    session.say(opening, allow_interruptions=True)
            else:
                session.generate_reply(instructions=GREETING)

    ctx.room.on("room_metadata_changed", maybe_greet)
    maybe_greet()


if __name__ == "__main__":
    agents.cli.run_app(server)
