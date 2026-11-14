"""Self-test of Lend's call audio without Chert: act like Chert's FaceTime bridge in a fresh LiveKit room.

    .venv/bin/python scripts/fake_caller.py ["what to say"]

Dispatches the running agent (AGENT_NAME) into a new room, joins as `chert-bridge-selftest` publishing a
`facetime-remote-audio` track, sets {"chert_bridge_ready": true} like chert dev does, then:
  1. measures Lend's greeting audio, 2. speaks a line (TTS), 3. measures Lend's reply audio.
Prints a PASS/FAIL line for each direction.
"""
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

from livekit import api, rtc  # noqa: E402
from livekit.agents import inference  # noqa: E402
from livekit.agents.utils import http_context  # noqa: E402

URL, KEY, SECRET = (os.environ[k] for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))
AGENT = os.getenv("AGENT_NAME", "lend-agent")
LINE = sys.argv[1] if len(sys.argv) > 1 else "Check my email please."


async def main():
    room_name = f"lend-selftest-{uuid.uuid4().hex[:8]}"
    lk = api.LiveKitAPI(URL, KEY, SECRET)
    await lk.room.create_room(api.CreateRoomRequest(name=room_name, empty_timeout=60))
    await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(agent_name=AGENT, room=room_name))
    token = (api.AccessToken(KEY, SECRET).with_identity("chert-bridge-selftest")
             .with_grants(api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True))
             .to_jwt())
    room = rtc.Room()
    heard = {"peak": 0.0, "loud_frames": 0, "since": 0.0}

    async def measure(track):
        async for ev in rtc.AudioStream(track):
            d = np.frombuffer(ev.frame.data, dtype=np.int16)
            if d.size:
                p = float(np.abs(d).max()) / 32768
                heard["peak"] = max(heard["peak"], p)
                if p > 0.02:
                    heard["loud_frames"] += 1

    def on_track(track, pub, participant):
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            print(f"  subscribed to {participant.identity} audio track {pub.name!r}")
            asyncio.create_task(measure(track))
        elif track.kind == rtc.TrackKind.KIND_VIDEO:
            print(f"  {participant.identity} publishes video {pub.name!r}")

    room.on("track_subscribed", on_track)
    await room.connect(URL, token)
    print(f"Joined {room_name} as the fake Chert bridge")

    # our "phone microphone"
    async with http_context.open():
        tts = inference.TTS(model="fishaudio/s2.1-pro", voice="fa4c9eb3dccc4806b382b40d61c6b10a")
        frames = [ev.frame async for ev in tts.synthesize(LINE)]
    sr = frames[0].sample_rate
    mic = rtc.AudioSource(sr, 1)
    await room.local_participant.publish_track(
        rtc.LocalAudioTrack.create_audio_track("facetime-remote-audio", mic),
        rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    silence = rtc.AudioFrame(b"\0\0" * (sr // 50), sr, 1, sr // 50)

    async def feed_silence(seconds):
        for _ in range(int(seconds * 50)):
            await mic.capture_frame(silence)

    agent_seen = time.time() + 30
    while time.time() < agent_seen and not any(p.identity != "chert-bridge-selftest"
                                                for p in room.remote_participants.values()):
        await feed_silence(0.2)
    agents = [p.identity for p in room.remote_participants.values()]
    print(f"  agent in room: {agents or 'NONE'}")
    await feed_silence(2)
    await lk.room.update_room_metadata(api.UpdateRoomMetadataRequest(
        room=room_name, metadata=json.dumps({"chert_call": "selftest", "chert_bridge_ready": True})))
    print("  sent chert_bridge_ready")
    await feed_silence(10)
    greet = dict(heard)
    print(f"1. Lend -> caller (greeting): peak {greet['peak']:.3f}, {greet['loud_frames']} loud frames  "
          f"{'PASS' if greet['loud_frames'] > 20 else 'FAIL'}")

    heard.update(peak=0.0, loud_frames=0)
    print(f"  saying: {LINE!r}")
    for f in frames:
        await mic.capture_frame(f)
    await feed_silence(20)
    print(f"2. caller -> Lend -> caller (reply): peak {heard['peak']:.3f}, {heard['loud_frames']} loud frames  "
          f"{'PASS' if heard['loud_frames'] > 20 else 'FAIL'}  (check the agent log for HEARD/SAID)")
    await room.disconnect()
    await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
    await lk.aclose()


asyncio.run(main())
