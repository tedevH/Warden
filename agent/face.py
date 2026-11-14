"""Lend's on-call face: an animated cartoon published as the agent's camera track.

FaceTime Video calls wait on a holding screen until the agent publishes video (Chert docs, audio-video),
so this also makes video calls work. The face shows:
  * mouth moving while Lend speaks, eyes looking up while it thinks
  * a big caption (what Lend is doing / just said) for people who are hard of hearing
  * a shield badge: green normally, red after Lend blocks a scam
"""
import asyncio
import math
import time
from pathlib import Path

from livekit import rtc
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 720, 960, 12
BG = (14, 22, 32)
SKIN = (255, 214, 170)
INK = (35, 30, 30)
GREEN, RED, AMBER = (34, 197, 94), (239, 68, 68), (245, 158, 11)


def _font(size):
    for p in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Helvetica.ttc",
              "/Library/Fonts/Arial.ttf"):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


class Face:
    def __init__(self):
        self.state = "listening"        # listening | thinking | speaking
        self.caption = "Hi, I'm Lend"
        self.alert = False              # red shield after a blocked scam
        self.source = rtc.VideoSource(W, H)
        self.track = rtc.LocalVideoTrack.create_video_track("lend-face", self.source)
        self._task = None
        self.f_title, self.f_cap, self.f_small = _font(54), _font(40), _font(30)

    async def publish(self, room: rtc.Room):
        opts = rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_CAMERA)
        await room.local_participant.publish_track(self.track, opts)
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        if self._task:
            self._task.cancel()

    async def _loop(self):
        start = time.monotonic()
        while True:
            t = time.monotonic() - start
            img = self.draw(t)
            frame = rtc.VideoFrame(W, H, rtc.VideoBufferType.RGBA, img.tobytes())
            self.source.capture_frame(frame)
            await asyncio.sleep(1 / FPS)

    def _wrap(self, d, text, font, width):
        words, lines, cur = text.split(), [], ""
        for w in words:
            test = f"{cur} {w}".strip()
            if d.textlength(test, font=font) <= width:
                cur = test
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines[:4]

    def draw(self, t: float) -> Image.Image:
        img = Image.new("RGBA", (W, H), BG + (255,))
        d = ImageDraw.Draw(img)
        cx, cy, r = W // 2, 360, 230
        # name + shield
        d.text((40, 36), "Lend", font=self.f_title, fill=(240, 244, 248))
        sc = RED if self.alert else GREEN
        sx, sy = W - 110, 40
        d.polygon([(sx, sy), (sx + 70, sy), (sx + 70, sy + 45), (sx + 35, sy + 80), (sx, sy + 45)], fill=sc)
        d.text((sx + 35, sy + 36), "!" if self.alert else "✓", font=self.f_small, fill=(255, 255, 255), anchor="mm")
        # head (gentle bob)
        bob = 6 * math.sin(t * 1.6)
        cy += bob
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=SKIN, outline=(230, 180, 140), width=6)
        # eyes: blink every ~4 s, look up while thinking
        blink = (t % 4.0) < 0.15
        look = -18 if self.state == "thinking" else 0
        for ex in (cx - 85, cx + 85):
            if blink:
                d.line([ex - 28, cy - 50, ex + 28, cy - 50], fill=INK, width=8)
            else:
                d.ellipse([ex - 30, cy - 85, ex + 30, cy - 15], fill=(255, 255, 255), outline=INK, width=5)
                d.ellipse([ex - 14, cy - 64 + look, ex + 14, cy - 36 + look], fill=INK)
        # mouth
        if self.state == "speaking":
            open_ = 18 + 34 * abs(math.sin(t * 9.0)) * (0.6 + 0.4 * abs(math.sin(t * 2.3)))
            d.ellipse([cx - 70, cy + 70 - open_ / 2, cx + 70, cy + 70 + open_ / 2], fill=(120, 30, 40), outline=INK, width=5)
        elif self.state == "thinking":
            d.line([cx - 50, cy + 85, cx + 50, cy + 85], fill=INK, width=8)
        else:
            d.arc([cx - 90, cy + 10, cx + 90, cy + 120], start=20, end=160, fill=INK, width=9)
        # status pill
        label = {"speaking": "Talking", "thinking": "Working on it", "listening": "Listening"}.get(self.state, "")
        dots = "." * (1 + int(t * 2) % 3) if self.state == "thinking" else ""
        col = AMBER if self.state == "thinking" else (GREEN if self.state == "listening" else (56, 189, 248))
        pill = f"{label}{dots}"
        pw = d.textlength(pill, font=self.f_small) + 50
        d.rounded_rectangle([cx - pw / 2, 640, cx + pw / 2, 694], radius=27, fill=col)
        d.text((cx, 667), pill, font=self.f_small, fill=(10, 10, 10), anchor="mm")
        # caption
        lines = self._wrap(d, self.caption, self.f_cap, W - 80)
        y = 730
        for line in lines:
            d.text((cx, y), line, font=self.f_cap, fill=(240, 244, 248), anchor="mt")
            y += 52
        return img
