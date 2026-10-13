"""Passive liveness / anti-spoofing heuristics.

Three cheap cues are fused into a 0..1 score (1 = confidently a live person):

* **temporal** - landmark geometry of a live face changes non-rigidly (blinks,
  expressions, micro-movements); a held photo/screen moves as one rigid sheet.
* **texture**  - recaptured prints/screens are blurrier than a live face.
* **moire**    - screens add periodic high-frequency peaks to the spectrum.

This is a lightweight baseline, *not* a certified PAD system.  Swap in a
trained anti-spoof network by subclassing :class:`LivenessChecker` and
overriding :meth:`score_crop` / :meth:`temporal_score`.
"""
from __future__ import annotations

from collections import defaultdict, deque

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

WARMUP_SCORE = 0.75  # neutral-pass until enough frames have been observed


class LivenessChecker:
    def __init__(self, window: int = 15):
        self.window = window
        self.history: dict[int, deque] = defaultdict(lambda: deque(maxlen=window))

    # ---- cues ----------------------------------------------------------
    @staticmethod
    def _shape_features(face_row: np.ndarray):
        re, le, nose, rm, lm = (face_row[4:6], face_row[6:8], face_row[8:10], face_row[10:12], face_row[12:14])
        eye = np.linalg.norm(re - le) + 1e-6
        if eye < 4:  # no landmarks (Haar fallback)
            return None
        mouth = np.linalg.norm(rm - lm) / eye
        eye_mid = (re + le) / 2
        nose_drop = np.linalg.norm(nose - eye_mid) / eye
        mouth_drop = np.linalg.norm((rm + lm) / 2 - nose) / eye
        asym = (np.linalg.norm(nose - re) - np.linalg.norm(nose - le)) / eye
        return np.array([mouth, nose_drop, mouth_drop, asym])

    def temporal_score(self, track_id: int) -> float:
        hist = self.history[track_id]
        if len(hist) < self.window // 2:
            return WARMUP_SCORE
        spread = float(np.mean(np.std(np.vstack(hist), axis=0)))
        return float(np.clip(spread / 0.02, 0.0, 1.0))

    @staticmethod
    def score_crop(gray: np.ndarray) -> tuple[float, float]:
        crop = cv2.resize(gray, (112, 112))
        sharp = cv2.Laplacian(crop, cv2.CV_64F).var()
        texture = float(np.clip((sharp - 20) / 120.0, 0.0, 1.0))
        spec = np.abs(np.fft.fftshift(np.fft.fft2(crop.astype(np.float32) - crop.mean())))
        yy, xx = np.ogrid[:112, :112]
        r = np.hypot(yy - 56, xx - 56)
        band = spec[(r > 30) & (r < 55)]
        peak_ratio = float(band.max() / (np.median(band) + 1e-6))
        moire = float(np.clip(1.0 - (peak_ratio - 12.0) / 25.0, 0.0, 1.0))
        return texture, moire

    # ---- API -----------------------------------------------------------
    def update(self, track_id: int, frame, face_row: np.ndarray) -> float:
        feats = self._shape_features(face_row)
        if feats is not None:
            self.history[track_id].append(feats)
        x, y, w, h = [int(v) for v in face_row[:4]]
        x, y = max(0, x), max(0, y)
        crop = frame[y:y + h, x:x + w]
        if crop.size == 0 or w < 40 or h < 40:
            return WARMUP_SCORE
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        texture, moire = self.score_crop(gray)
        temporal = self.temporal_score(track_id) if feats is not None else WARMUP_SCORE
        return float(0.45 * temporal + 0.30 * texture + 0.25 * moire)

    def forget(self, track_id: int) -> None:
        self.history.pop(track_id, None)
