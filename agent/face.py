"""Lend's on-call face: a polished illustrated avatar published as the agent's camera track.

FaceTime Video shows the agent's video once it publishes one (Chert docs), so this is what the caller sees:
  * an illustrated helper who blinks, looks up while thinking, and talks with a moving mouth
  * a status pill (Listening / Working on it / Talking) and a large caption card for hard-of-hearing callers
  * a badge: "Protected" in green, or "Scam blocked" in red after Lend stops a scam

Rendering: static layers are drawn once at 3x and downscaled (smooth edges). Each frame only redraws the
eyes, brows and mouth on a small 3x layer, so it stays cheap at 15 fps.
"""
import asyncio
import math
import time
from pathlib import Path

import numpy as np
from livekit import rtc
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, SS = 720, 960, 15, 3                # frame size, frame rate, supersampling factor
CX, CY = W // 2, 400                           # head centre
RX, RY = 138, 162                              # head radii
SKIN, SKIN_SHADE = (241, 196, 160), (214, 160, 124)
HAIR, HAIR_HI = (52, 38, 33), (88, 66, 56)
SWEATER, SWEATER_SHADE = (66, 133, 120), (49, 104, 94)
INK = (45, 32, 30)
IRIS = (58, 104, 140)
GREEN, RED, AMBER, BLUE = (34, 197, 94), (239, 68, 68), (245, 158, 11), (56, 189, 248)
FEAT = (CX - 125, CY - 95, CX + 125, CY + 120)  # region redrawn every frame (eyes, brows, mouth)


def _font(size, rounded=False):
    paths = (["/System/Library/Fonts/SFNSRounded.ttf"] if rounded else []) + [
        "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Avenir Next.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc"]
    for p in paths:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _s(*v):
    return [x * SS for x in v]


def _background():
    y = np.linspace(0, 1, H)[:, None]
    top, bottom = np.array([16, 24, 44]), np.array([24, 52, 74])
    img = np.zeros((H, W, 3))
    for c in range(3):
        img[:, :, c] = top[c] * (1 - y) + bottom[c] * y
    yy, xx = np.mgrid[0:H, 0:W]
    glow = np.exp(-(((xx - CX) / 300.0) ** 2 + ((yy - (CY - 10)) / 280.0) ** 2))
    img += glow[:, :, None] * np.array([40, 90, 100])
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert("RGBA")


def _avatar_layer():
    """Hair, body, neck, ears, head with soft shading, nose and blush. Transparent background."""
    big = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    # shoulders / sweater
    d.rounded_rectangle(_s(CX - 235, CY + 168, CX + 235, H + 200), radius=160 * SS, fill=SWEATER)
    # neck + crew collar
    d.rounded_rectangle(_s(CX - 46, CY + 120, CX + 46, CY + 190), radius=26 * SS, fill=SKIN_SHADE)
    d.chord(_s(CX - 70, CY + 140, CX + 70, CY + 222), 0, 180, fill=SKIN_SHADE)
    d.arc(_s(CX - 76, CY + 134, CX + 76, CY + 230), 0, 180, fill=SWEATER_SHADE, width=13 * SS)
    # hair, back part
    d.ellipse(_s(CX - RX - 26, CY - RY - 34, CX + RX + 26, CY + RY - 10), fill=HAIR)
    d.rounded_rectangle(_s(CX - RX - 26, CY - 40, CX + RX + 26, CY + 120), radius=60 * SS, fill=HAIR)
    # ears
    for sx in (-1, 1):
        ex = CX + sx * (RX - 4)
        d.ellipse(_s(ex - 24, CY - 10, ex + 24, CY + 52), fill=SKIN_SHADE)
        d.ellipse(_s(ex - 14, CY + 2, ex + 14, CY + 40), fill=(226, 172, 138))
    big = big.resize((W, H), Image.LANCZOS)

    # head with radial shading (computed at 1x, it's a smooth gradient anyway)
    yy, xx = np.mgrid[0:H, 0:W]
    nx, ny = (xx - CX) / RX, (yy - CY) / RY
    r = np.sqrt(nx ** 2 + ny ** 2)
    edge = np.clip((1.0 - r) * RX / 1.6, 0, 1)                      # 1px-ish anti-aliased edge
    light = np.clip(1.0 - 0.35 * np.clip(r - 0.35, 0, 1) - 0.12 * np.clip(nx + 0.2, 0, 1), 0, 1)
    rgb = np.array(SKIN_SHADE) + (np.array(SKIN) - np.array(SKIN_SHADE)) * light[:, :, None]
    head = np.dstack([rgb, edge * 255]).astype(np.uint8)
    big.alpha_composite(Image.fromarray(head, "RGBA"))

    top = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(top)
    # side-swept fringe: bottom edge is a curve, top edge follows the hair outline
    pts = []
    for i in range(41):
        u = i / 40                                     # 0 = left temple, 1 = right temple
        x = CX - RX - 6 + u * (2 * RX + 12)
        y = CY - 40 - 62 * math.sin(math.pi * min(1.0, u * 1.15)) ** 0.8 - 18 * u
        pts.append((x * SS, y * SS))
    for i in range(41):
        a = math.pi + math.pi * (1 - i / 40)          # back along the top of the hair, right -> left
        pts.append(((CX + (RX + 18) * math.cos(a)) * SS, (CY - 40 + (RY + 12) * math.sin(a)) * SS))
    d.polygon(pts[::-1], fill=HAIR)
    d.arc(_s(CX - 40, CY - RY - 18, CX + 150, CY - 40), 205, 285, fill=HAIR_HI, width=5 * SS)
    # nose
    d.arc(_s(CX - 16, CY + 10, CX + 16, CY + 42), 20, 160, fill=SKIN_SHADE, width=5 * SS)
    # blush
    blush = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blush)
    for sx in (-1, 1):
        bx = CX + sx * 78
        bd.ellipse(_s(bx - 30, CY + 30, bx + 30, CY + 62), fill=(236, 120, 120, 70))
    blush = blush.filter(ImageFilter.GaussianBlur(10 * SS))
    top.alpha_composite(blush)
    big.alpha_composite(top.resize((W, H), Image.LANCZOS))
    return big


class Face:
    def __init__(self):
        self.state = "listening"        # listening | thinking | speaking
        self.caption = "Hi, I'm Lend. How can I help?"
        self.alert = False              # red badge after a blocked scam
        self.source = rtc.VideoSource(W, H)
        self.track = rtc.LocalVideoTrack.create_video_track("lend-face", self.source)
        self._task = None
        self.f_title, self.f_sub = _font(46, rounded=True), _font(24)
        self.f_cap, self.f_pill = _font(36), _font(26, rounded=True)
        self.bg = _background()
        self.avatar = _avatar_layer()
        self._skin = self.avatar.getpixel((CX, CY - 20))[:3]

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
            t0 = time.monotonic()
            img = await asyncio.to_thread(self.draw, t0 - start)
            self.source.capture_frame(rtc.VideoFrame(W, H, rtc.VideoBufferType.RGBA, img.tobytes()))
            await asyncio.sleep(max(0.0, 1 / FPS - (time.monotonic() - t0)))

    # ---------- per-frame features ----------
    def _features(self, t):
        x0, y0, x1, y1 = FEAT
        w, h = (x1 - x0) * SS, (y1 - y0) * SS
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)

        def p(x, y):  # head-space (relative to CX, CY) -> layer pixels
            return ((CX + x - x0) * SS, (CY + y - y0) * SS)

        def box(xa, ya, xb, yb):
            a, b = p(xa, ya), p(xb, yb)
            return [a[0], a[1], b[0], b[1]]

        blink = (t % 4.2) < 0.13
        look = -7 if self.state == "thinking" else (2 * math.sin(t * 0.7))
        brow = -6 if self.state == "speaking" else (-10 if self.state == "thinking" else 0)
        for sx in (-1, 1):
            ex = sx * 56
            # brows
            d.arc(box(ex - 34, -64 + brow, ex + 34, -30 + brow), 200 if sx < 0 else 210, 330 if sx < 0 else 340,
                  fill=HAIR, width=9 * SS)
            if blink:
                d.arc(box(ex - 24, -24, ex + 24, 2), 20, 160, fill=INK, width=5 * SS)
                continue
            d.ellipse(box(ex - 25, -30, ex + 25, 6), fill=(255, 255, 255))
            ix = ex + look * 0.4
            d.ellipse(box(ix - 14, -24 + look, ix + 14, 4 + look), fill=IRIS)
            d.ellipse(box(ix - 7, -17 + look, ix + 7, -3 + look), fill=(18, 20, 28))
            d.ellipse(box(ix + 2, -20 + look, ix + 8, -14 + look), fill=(255, 255, 255))
            d.arc(box(ex - 27, -33, ex + 27, 8), 195, 345, fill=INK, width=5 * SS)   # upper lash line
        # mouth
        if self.state == "speaking":
            amp = abs(math.sin(t * 11.0)) * (0.55 + 0.45 * abs(math.sin(t * 3.1)))
            o = 8 + 26 * amp
            d.rounded_rectangle(box(-36, 66 - o / 2, 36, 66 + o / 2), radius=int(min(o, 36) / 2 * SS),
                                fill=(120, 40, 50))
            if o > 14:
                d.rounded_rectangle(box(-26, 66 - o / 2, 26, 66 - o / 2 + 7), radius=3 * SS, fill=(250, 248, 245))
                d.ellipse(box(-18, 66 + o / 2 - 12, 18, 66 + o / 2 + 4), fill=(214, 96, 106))
        elif self.state == "thinking":
            d.rounded_rectangle(box(-18, 64, 18, 70), radius=3 * SS, fill=(160, 74, 80))
        else:
            d.arc(box(-44, 30, 44, 84), 25, 155, fill=(165, 72, 78), width=7 * SS)
        return layer.resize((x1 - x0, y1 - y0), Image.LANCZOS)

    def _wrap(self, d, text, font, width, max_lines=3):
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
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(".,") + "…"
        return lines

    def draw(self, t: float) -> Image.Image:
        img = self.bg.copy()
        img.alpha_composite(self.avatar)
        img.alpha_composite(self._features(t), (FEAT[0], FEAT[1]))
        ui = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ui)
        # header
        d.text((40, 34), "Lend", font=self.f_title, fill=(244, 247, 250))
        d.text((42, 90), "Your online safety helper", font=self.f_sub, fill=(160, 180, 196))
        label = "Scam blocked" if self.alert else "Protected"
        col = RED if self.alert else GREEN
        bw = d.textlength(label, font=self.f_pill) + 74
        d.rounded_rectangle([W - 40 - bw, 40, W - 40, 92], radius=26, fill=(10, 16, 28, 190), outline=col, width=3)
        sx, sy = W - 40 - bw + 22, 52
        d.polygon([(sx, sy), (sx + 24, sy), (sx + 24, sy + 15), (sx + 12, sy + 28), (sx, sy + 15)], fill=col)
        d.text((sx + 38, 66), label, font=self.f_pill, fill=(244, 247, 250), anchor="lm")
        # status pill
        name = {"speaking": "Talking", "thinking": "Working on it", "listening": "Listening"}.get(self.state, "")
        dot = {"speaking": BLUE, "thinking": AMBER, "listening": GREEN}.get(self.state, GREEN)
        pw = d.textlength(name, font=self.f_pill) + 70
        py = 640
        d.rounded_rectangle([CX - pw / 2, py, CX + pw / 2, py + 50], radius=25, fill=(10, 16, 28, 200))
        pulse = 7 + 2 * math.sin(t * 6) if self.state != "listening" else 7
        d.ellipse([CX - pw / 2 + 22 - pulse, py + 25 - pulse, CX - pw / 2 + 22 + pulse, py + 25 + pulse], fill=dot)
        d.text((CX - pw / 2 + 42, py + 25), name, font=self.f_pill, fill=(244, 247, 250), anchor="lm")
        # caption card
        lines = self._wrap(d, self.caption, self.f_cap, W - 120)
        card_h = 40 + 48 * max(1, len(lines))
        d.rounded_rectangle([36, 714, W - 36, 714 + card_h], radius=28, fill=(255, 255, 255, 252))
        y = 734
        for line in lines:
            d.text((CX, y), line, font=self.f_cap, fill=(22, 30, 42), anchor="mt")
            y += 48
        img.alpha_composite(ui)
        return img
