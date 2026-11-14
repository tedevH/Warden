"""Owner check: only the enrolled owner's face AND voice unlock Warden's tools.

Runs locally on this computer, nothing is sent anywhere:
  face   OpenCV YuNet (find the face) + SFace (face embedding), compared with the enrolled owner
  voice  WeSpeaker ResNet34 speaker embedding (via sherpa-onnx), compared with the enrolled owner

Enrollment happens on a real FaceTime Video call (`make enroll`, then call), so the enrolled face and voice come
through the same camera and microphone path as every later call. The enrolled embeddings live in data/owner/
(gitignored); no photos or recordings are kept.

Limits, stated plainly: this is identity matching, not liveness detection. A good photo held to the camera or a
recording of the owner's voice could fool it. It is one layer on top of the approval rules, not a replacement.
"""
import asyncio
import logging
import os
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("lend.verify")
ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
OWNER = ROOT / "data" / "owner"
SR = 16000
FACE_MIN = float(os.getenv("LEND_FACE_MIN", "0.36"))    # SFace cosine; 0.363 is the model's published threshold
VOICE_MIN = float(os.getenv("LEND_VOICE_MIN", "0.62"))  # speaker cosine on ~3 s of speech
VOICE_CHUNK_S = 3.0                                      # speech needed for one voice decision
SPEECH_PEAK = 0.03                                       # a 10 ms frame louder than this counts as speech
FACE_FRESH_S = 4.0                                       # a face match older than this no longer counts


def models_present():
    return all((MODELS / n).exists() for n in ("yunet.onnx", "sface.onnx", "speaker.onnx"))


def _unit(v):
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    return v / (np.linalg.norm(v) + 1e-9)


class OwnerCheck:
    """Feed it the caller's video frames and audio; read `.status`: "checking" | "owner" | "stranger"."""

    def __init__(self, on_change=None):
        self.on_change = on_change or (lambda status, why: None)
        self.status, self.why = "checking", "Waiting to see and hear the caller."
        self.face_ref = self.voice_ref = None
        self._frame = None
        self._speech: list[np.ndarray] = []
        self._speech_n = 0
        self._face_ok_at = 0.0
        self._face_miss = 0          # consecutive checks where a face was visible but was not the owner
        self._voice_ok: bool | None = None
        self._task = None
        self._det = self._rec = self._spk = None

    # ---------- setup ----------
    def load(self):
        """Load the models (takes about a second; call it off the event loop)."""
        import cv2
        import sherpa_onnx
        self._cv2 = cv2
        self._det = cv2.FaceDetectorYN.create(str(MODELS / "yunet.onnx"), "", (320, 320), 0.8)
        self._rec = cv2.FaceRecognizerSF.create(str(MODELS / "sface.onnx"), "")
        self._spk = sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODELS / "speaker.onnx"), num_threads=2))
        if self.enrolled():
            self.face_ref = np.load(OWNER / "face.npy")
            self.voice_ref = np.load(OWNER / "voice.npy")

    @staticmethod
    def enrolled():
        return (OWNER / "face.npy").exists() and (OWNER / "voice.npy").exists()

    @staticmethod
    def enroll_requested():
        return (OWNER / "ENROLL").exists()

    # ---------- inputs ----------
    def feed_frame(self, frame):
        self._frame = frame          # newest livekit rtc.VideoFrame; converted only when checked

    def feed_audio(self, pcm: np.ndarray):
        """`pcm`: int16 mono at 16 kHz. Keeps only the frames that contain speech."""
        if pcm.size and float(np.abs(pcm).max()) / 32768 > SPEECH_PEAK:
            self._speech.append(pcm.astype(np.float32) / 32768)
            self._speech_n += pcm.size

    # ---------- embeddings ----------
    def face_embedding(self, bgr):
        """Embedding of the largest face in a BGR image, or None if there is no face."""
        cv2 = self._cv2
        h, w = bgr.shape[:2]
        if w > 640:
            bgr = cv2.resize(bgr, (640, int(h * 640 / w)))
            h, w = bgr.shape[:2]
        self._det.setInputSize((w, h))
        _, faces = self._det.detect(bgr)
        if faces is None or not len(faces):
            return None
        face = max(faces, key=lambda f: f[2] * f[3])
        if face[2] < 60:             # too small / too far to trust
            return None
        return _unit(self._rec.feature(self._rec.alignCrop(bgr, face)))

    def voice_embedding(self, samples: np.ndarray):
        s = self._spk.create_stream()
        s.accept_waveform(sample_rate=SR, waveform=samples)
        s.input_finished()
        return _unit(self._spk.compute(s))

    def _bgr(self):
        from livekit import rtc
        f = self._frame
        if f is None:
            return None
        rgb = f.convert(rtc.VideoBufferType.RGB24)
        img = np.frombuffer(rgb.data, dtype=np.uint8).reshape(rgb.height, rgb.width, 3)
        return self._cv2.cvtColor(img, self._cv2.COLOR_RGB2BGR)

    def _take_speech(self, seconds):
        if self._speech_n < seconds * SR:
            return None
        out = np.concatenate(self._speech)
        self._speech, self._speech_n = [], 0
        return out

    # ---------- enrollment ----------
    async def enroll(self, timeout=45.0):
        """Learn the caller as the owner: about 8 face samples and 9 s of speech. Returns (ok, message)."""
        faces, voice, end = [], None, time.time() + timeout
        self._speech, self._speech_n = [], 0
        while time.time() < end and (len(faces) < 8 or voice is None):
            await asyncio.sleep(0.5)
            if len(faces) < 8:
                img = await asyncio.to_thread(self._bgr)
                e = await asyncio.to_thread(self.face_embedding, img) if img is not None else None
                if e is not None:
                    faces.append(e)
            if voice is None:
                speech = self._take_speech(9.0)
                if speech is not None:
                    voice = await asyncio.to_thread(self.voice_embedding, speech)
        if len(faces) < 4:
            return False, "I couldn't see a face clearly. Call on FaceTime Video and look at the camera."
        if voice is None:
            return False, "I didn't hear enough of your voice. Keep talking for about fifteen seconds."
        OWNER.mkdir(parents=True, exist_ok=True)
        self.face_ref, self.voice_ref = _unit(np.mean(faces, axis=0)), voice
        np.save(OWNER / "face.npy", self.face_ref)
        np.save(OWNER / "voice.npy", self.voice_ref)
        (OWNER / "ENROLL").unlink(missing_ok=True)
        self._face_ok_at, self._voice_ok = time.time(), True
        self._set("owner", "Just enrolled as the owner.")
        log.info("OWNER ENROLLED: %d face samples, voice embedding saved", len(faces))
        return True, "Enrolled."

    # ---------- continuous check ----------
    def start(self):
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        if self._task:
            self._task.cancel()

    def _set(self, status, why):
        self.why = why
        if status != self.status:
            self.status = status
            log.info("OWNER CHECK: %s (%s)", status.upper(), why)
            try:
                self.on_change(status, why)
            except Exception:
                log.exception("on_change failed")

    async def _loop(self):
        while True:
            await asyncio.sleep(1.0)
            try:
                await self._check()
            except Exception:
                log.exception("owner check failed")

    async def _check(self):
        now = time.time()
        img = await asyncio.to_thread(self._bgr)
        if img is not None:
            e = await asyncio.to_thread(self.face_embedding, img)
            if e is not None:
                score = float(e @ self.face_ref)
                if score >= FACE_MIN:
                    self._face_ok_at, self._face_miss = now, 0
                else:
                    self._face_miss += 1
                log.info("FACE score %.2f (need %.2f)", score, FACE_MIN)
        speech = self._take_speech(VOICE_CHUNK_S)
        if speech is not None:
            score = float(await asyncio.to_thread(self.voice_embedding, speech) @ self.voice_ref)
            self._voice_ok = score >= VOICE_MIN
            log.info("VOICE score %.2f (need %.2f)", score, VOICE_MIN)

        face_ok = now - self._face_ok_at < FACE_FRESH_S
        if self._face_miss >= 2:
            self._set("stranger", "The face on camera is not the owner's.")
        elif self._voice_ok is False:
            self._set("stranger", "The voice is not the owner's.")
        elif face_ok and self._voice_ok:
            self._set("owner", "Face and voice both match the owner.")
        elif self._frame is None:
            self._set("checking", "No camera. Call on FaceTime Video so I can see it's you.")
        elif not face_ok:
            self._set("checking", "I can't see the owner's face. Look at the camera.")
        else:
            self._set("checking", "I need to hear a few more words to check the voice.")
