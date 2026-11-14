"""Warden's on-call screen: what the caller sees on FaceTime Video (published as the agent's camera track).

A clean product-style call screen rather than a cartoon:
  * a glowing orb with the Warden shield: breathes while listening, spins an arc while working,
    ripples and shows a live waveform while talking, turns red when a scam or a stranger is detected
  * a status line (Listening / Working on it / Speaking) and a security chip
    (Protected / Checking it's you / Owner verified / Not the owner / Scam blocked)
  * a large caption card so hard-of-hearing callers can read what Warden says

Rendering: the background, glows and shield are drawn once. Each frame redraws only the orb's rings on a
small 2x layer plus the text, so it stays cheap at 15 fps.
"""
import asyncio
import math
import time
from pathlib import Path

import numpy as np
from livekit import rtc
from PIL import Image, ImageDraw, ImageFont

W, H, FPS, SS = 720, 960, 15, 2                # frame size, frame rate, supersampling factor for the orb
CX, CY = W // 2, 372                           # orb centre
R = 118                                        # orb radius
ORB = 300                                      # half-size of the orb layer redrawn each frame
TEAL, RED, AMBER, BLUE = (45, 212, 191), (248, 82, 82), (251, 176, 52), (96, 165, 250)
TEXT, MUTED = (240, 245, 250), (138, 154, 176)


def _font(size, rounded=False, bold=False):
    paths = (["/System/Library/Fonts/SFNSRounded.ttf"] if rounded else []) + [
        "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Avenir Next.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc", "/System/Library/Fonts/Helvetica.ttc"]
    for p in paths:
        if Path(p).exists():
            try:
                f = ImageFont.truetype(p, size)
                if bold:
                    try:
                        f.set_variation_by_axes([700])
                    except Exception:
                        pass
                return f
            except OSError:
                continue
    return ImageFont.load_default()


def _background():
    y = np.linspace(0, 1, H)[:, None]
    top, bottom = np.array([8, 12, 24]), np.array([13, 22, 40])
    img = np.zeros((H, W, 3))
    for c in range(3):
        img[:, :, c] = top[c] * (1 - y) + bottom[c] * y
    yy, xx = np.mgrid[0:H, 0:W]
    vignette = 1 - 0.35 * np.clip(np.hypot((xx - CX) / (W * 0.75), (yy - H / 2) / (H * 0.75)), 0, 1) ** 2
    return Image.fromarray(np.clip(img * vignette[:, :, None], 0, 255).astype(np.uint8)).convert("RGBA")


def _glow(color):
    """Soft halo + lit sphere for one accent colour, on a transparent (2*ORB)^2 layer."""
    n = 2 * ORB
    yy, xx = np.mgrid[0:n, 0:n]
    d = np.hypot(xx - ORB, yy - ORB)
    halo = np.exp(-((d / (R * 1.25)) ** 2)) * 0.55
    out = np.zeros((n, n, 4))
    out[:, :, :3] = color
    out[:, :, 3] = halo * 255
    img = Image.fromarray(out.astype(np.uint8), "RGBA")
    # sphere: dark glass core, lit from the top-left, with a coloured rim
    light = np.clip(1 - np.hypot(xx - (ORB - R * 0.35), yy - (ORB - R * 0.45)) / (R * 1.9), 0, 1)
    rim = np.clip((d - R * 0.62) / (R * 0.38), 0, 1) ** 2
    base = np.array([14, 22, 40])[None, None, :] * (0.7 + 0.9 * light[:, :, None])
    rgb = base + rim[:, :, None] * np.array(color)[None, None, :] * 0.55
    edge = np.clip(R - d, 0, 1)
    sphere = np.dstack([np.clip(rgb, 0, 255), edge * 255]).astype(np.uint8)
    img.alpha_composite(Image.fromarray(sphere, "RGBA"))
    return img


def _shield(color, size=92, check=True):
    """The Warden mark: a shield with a tick (or a cross), drawn at 4x and smoothed down."""
    k = 4
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = s / 2
    pts = [(cx, s * 0.04), (s * 0.88, s * 0.18), (s * 0.88, s * 0.50)]
    for i in range(1, 13):                       # right side curving down to the point
        u = i / 12
        pts.append((cx + (s * 0.38) * math.cos(u * math.pi / 2) ** 0.8, s * 0.50 + (s * 0.46) * math.sin(u * math.pi / 2)))
    pts += [(2 * cx - x, y) for x, y in reversed(pts[1:-1])]
    d.polygon(pts, fill=(244, 248, 252))
    w = int(s * 0.085)
    if check:
        d.line([(s * 0.31, s * 0.47), (s * 0.45, s * 0.62), (s * 0.70, s * 0.33)], fill=color, width=w, joint="curve")
    else:
        d.line([(s * 0.34, s * 0.32), (s * 0.66, s * 0.64)], fill=color, width=w)
        d.line([(s * 0.66, s * 0.32), (s * 0.34, s * 0.64)], fill=color, width=w)
    return img.resize((size, size), Image.LANCZOS)


class Face:
    def __init__(self):
        self.state = "listening"        # listening | thinking | speaking
        self.caption = "Hi, I'm Warden. How can I help?"
        self._alert_at = -1e9          # red for 30 s after a blocked scam, then back to normal
        self.badge = None               # owner check: text that replaces "Protected" (e.g. "Owner verified")
        self.badge_bad = False          # ... drawn in red (a stranger is on the call)
        self.source = rtc.VideoSource(W, H)
        self.track = rtc.LocalVideoTrack.create_video_track("lend-face", self.source)
        self._task = None
        self.f_brand, self.f_sub = _font(30, bold=True), _font(22)
        self.f_status, self.f_chip = _font(34, rounded=True), _font(24, rounded=True)
        self.f_cap = _font(36)
        self.bg = _background()
        self.glows = {c: _glow(c) for c in (TEAL, RED, AMBER, BLUE)}
        self.shields = {c: _shield(c) for c in (TEAL, AMBER, BLUE)}
        self.shields[RED] = _shield(RED, check=False)
        self.logo = _shield(TEAL, size=40)

    @property
    def alert(self):
        return time.monotonic() - self._alert_at < 30

    @alert.setter
    def alert(self, on):
        self._alert_at = time.monotonic() if on else -1e9

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

    # ---------- per-frame orb ----------
    def _accent(self):
        if self.alert or self.badge_bad:
            return RED
        return {"speaking": BLUE, "thinking": AMBER}.get(self.state, TEAL)

    def _rings(self, t, color):
        n = 2 * ORB * SS
        layer = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        c = ORB * SS

        def ring(r, alpha, width):
            if alpha > 0:
                d.ellipse([c - r * SS, c - r * SS, c + r * SS, c + r * SS], outline=color + (int(alpha),), width=int(width * SS))

        if self.state == "speaking":
            for i in range(3):                     # ripples moving outward
                u = (t * 0.9 + i / 3) % 1
                ring(R + 10 + u * 120, 170 * (1 - u) ** 1.5, 3)
            ring(R + 4, 230, 3)
        elif self.state == "thinking":
            ring(R + 16, 60, 2)
            a = (t * 220) % 360                    # a bright arc circling the orb
            box = [c - (R + 16) * SS, c - (R + 16) * SS, c + (R + 16) * SS, c + (R + 16) * SS]
            d.arc(box, a, a + 95, fill=color + (255,), width=5 * SS)
            d.arc(box, a + 180, a + 215, fill=color + (150,), width=5 * SS)
            ring(R + 4, 150, 2)
        else:
            breathe = 0.5 + 0.5 * math.sin(t * 1.6)
            ring(R + 4, 150 + 60 * breathe, 3)
            ring(R + 22 + 6 * breathe, 55, 2)
            ring(R + 48 + 10 * breathe, 26, 2)
        return layer.resize((2 * ORB, 2 * ORB), Image.LANCZOS)

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
        color = self._accent()
        img = self.bg.copy()
        img.alpha_composite(self.glows[color], (CX - ORB, CY - ORB))
        img.alpha_composite(self._rings(t, color), (CX - ORB, CY - ORB))
        sh = self.shields[color]
        img.alpha_composite(sh, (CX - sh.width // 2, CY - sh.height // 2))
        ui = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(ui)

        # brand bar
        ui.alpha_composite(self.logo, (36, 34))
        d.text((88, 38), "WARDEN", font=self.f_brand, fill=TEXT, spacing=0, features=None)
        d.text((W - 36, 56), "AI security guardian", font=self.f_sub, fill=MUTED, anchor="rm")
        d.line([(36, 96), (W - 36, 96)], fill=(255, 255, 255, 22), width=1)

        # status line + live waveform
        name = {"speaking": "Speaking", "thinking": "Working on it", "listening": "Listening"}.get(self.state, "")
        d.text((CX, 566), name, font=self.f_status, fill=TEXT, anchor="mm")
        bars, bw, gap = 17, 6, 8
        x0 = CX - (bars * bw + (bars - 1) * gap) / 2
        for i in range(bars):
            if self.state == "speaking":
                env = math.sin(math.pi * (i + 0.5) / bars)
                hgt = 5 + 30 * env * abs(math.sin(t * 9 + i * 0.9)) * (0.6 + 0.4 * abs(math.sin(t * 2.3 + i)))
            elif self.state == "thinking":
                hgt = 5 + 9 * (0.5 + 0.5 * math.sin(t * 6 - i * 0.55))
            else:
                hgt = 4
            x = x0 + i * (bw + gap)
            d.rounded_rectangle([x, 612 - hgt, x + bw, 612 + hgt], radius=3, fill=color + (230,))

        # security chip
        label = "Scam blocked" if self.alert else (self.badge or "Protected")
        chip = RED if self.alert or self.badge_bad else (AMBER if label.startswith(("Checking", "Learning")) else TEAL)
        cw = d.textlength(label, font=self.f_chip) + 62
        cy0 = 664
        d.rounded_rectangle([CX - cw / 2, cy0, CX + cw / 2, cy0 + 46], radius=23, fill=chip + (34,), outline=chip + (200,), width=2)
        d.ellipse([CX - cw / 2 + 20, cy0 + 16, CX - cw / 2 + 34, cy0 + 30], fill=chip)
        d.text((CX - cw / 2 + 46, cy0 + 23), label, font=self.f_chip, fill=TEXT, anchor="lm")

        # caption card
        lines = self._wrap(d, self.caption, self.f_cap, W - 128)
        card_h = 44 + 48 * max(1, len(lines))
        top = 744
        d.rounded_rectangle([36, top, W - 36, top + card_h], radius=26, fill=(22, 32, 54, 235), outline=(255, 255, 255, 30), width=1)
        y = top + 22
        for line in lines:
            d.text((CX, y), line, font=self.f_cap, fill=TEXT, anchor="mt")
            y += 48
        img.alpha_composite(ui)
        return img
