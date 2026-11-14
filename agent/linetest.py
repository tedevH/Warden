"""Line test: checks Chert's FaceTime audio path with no AI at all.

    LEND_LINE_TEST=1 python agent/agent.py dev      (same agent name, so `chert dev` routes calls here)

On a call it:
  * publishes ONE audio track that beeps (660 Hz, 0.3 s) once a second, plus the face video
  * starts beeping the moment Chert reports FaceTime ready (bridge_ready)
  * logs, once a second, the loudest sample on every audio track the caller sends

If the caller hears beeps, Chert's outbound audio works. If the logged peaks rise when the caller talks,
Chert's inbound audio works. Both silent means the line/bridge isn't carrying sound.
"""
import asyncio
import json
import logging
import math

import numpy as np
from livekit import rtc

log = logging.getLogger("lend.linetest")
SR, CH = 48000, 1
FRAME = SR // 50  # 20 ms


def _beep_frames(on: bool):
    t = np.arange(FRAME) / SR
    while True:
        for i in range(50):  # one second = 50 frames; first 15 frames (0.3 s) beep
            if on and i < 15:
                wave = (0.35 * np.sin(2 * math.pi * 660 * (t + i * FRAME / SR)) * 32767).astype(np.int16)
            else:
                wave = np.zeros(FRAME, dtype=np.int16)
            yield rtc.AudioFrame(wave.tobytes(), SR, CH, FRAME)


async def run(ctx, caller, face):
    source = rtc.AudioSource(SR, CH)
    track = rtc.LocalAudioTrack.create_audio_track("lend-line-test", source)
    await ctx.room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    log.info("LINETEST published beep audio track")
    ready = asyncio.Event()

    def check(*_):
        try:
            if json.loads(ctx.room.metadata or "{}").get("chert_bridge_ready") is True and not ready.is_set():
                log.info("LINETEST FaceTime ready: beeping now")
                face.caption = "Line test: you should hear a beep every second. Say something."
                ready.set()
        except ValueError:
            pass

    ctx.room.on("room_metadata_changed", check)
    check()

    async def play():
        gen_silent, gen_beep = _beep_frames(False), _beep_frames(True)
        while True:
            frame = next(gen_beep if ready.is_set() else gen_silent)
            await source.capture_frame(frame)

    async def levels(trk, name):
        peak, frames, loop = 0.0, 0, asyncio.get_running_loop()
        last = loop.time()
        async for ev in rtc.AudioStream(trk):
            d = np.frombuffer(ev.frame.data, dtype=np.int16)
            if d.size:
                peak = max(peak, float(np.abs(d).max()) / 32768)
            frames += 1
            if loop.time() - last >= 1:
                bar = "#" * int(peak * 40)
                log.info("LINETEST caller %s: peak %.3f %s (%d frames)", name, peak, bar, frames)
                peak, frames, last = 0.0, 0, loop.time()

    tasks = [asyncio.create_task(play())]

    def on_track(trk, pub, participant):
        if trk.kind == rtc.TrackKind.KIND_AUDIO and participant.identity == caller.identity:
            log.info("LINETEST listening to caller track %r", pub.name)
            tasks.append(asyncio.create_task(levels(trk, pub.name)))

    ctx.room.on("track_subscribed", on_track)
    for pub in caller.track_publications.values():
        if pub.track:
            on_track(pub.track, pub, caller)

    async def stop():
        for t in tasks:
            t.cancel()
        face.stop()
        log.info("LINETEST call over")

    ctx.add_shutdown_callback(stop)
