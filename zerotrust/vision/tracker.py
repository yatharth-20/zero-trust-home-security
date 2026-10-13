"""Multi-person tracker with temporal identity voting.

Every person gets an independent track.  Identity is only declared *stable*
after ``confirm_frames`` agreeing votes, which suppresses one-frame
mis-recognitions (and the alarms they would cause).
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

from ..models import PersonObservation


def iou(a, b) -> float:
    ax2, ay2, bx2, by2 = a[0] + a[2], a[1] + a[3], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax2, bx2) - max(a[0], b[0]))
    ih = max(0.0, min(ay2, by2) - max(a[1], b[1]))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


@dataclass
class Track:
    id: int
    bbox: tuple
    first_seen: datetime
    last_seen: datetime
    votes: deque = field(default_factory=lambda: deque(maxlen=12))
    liveness: deque = field(default_factory=lambda: deque(maxlen=6))
    frames: int = 0
    scores: dict = field(default_factory=dict)


class FaceTracker:
    def __init__(self, confirm_frames: int = 3, max_missing_s: float = 1.5, iou_min: float = 0.2):
        self.confirm = confirm_frames
        self.max_missing = timedelta(seconds=max_missing_s)
        self.iou_min = iou_min
        self.tracks: dict[int, Track] = {}
        self._next = 1

    def update(self, boxes: list[tuple], now: datetime) -> list[Track]:
        """Associate detections with tracks (greedy IoU, then centroid distance). Returns track per box."""
        assigned: dict[int, Track] = {}
        used: set[int] = set()
        pairs = sorted(((iou(t.bbox, b), tid, i) for tid, t in self.tracks.items() for i, b in enumerate(boxes)),
                       reverse=True)
        for ov, tid, i in pairs:
            if ov < self.iou_min or tid in used or i in assigned:
                continue
            used.add(tid)
            assigned[i] = self.tracks[tid]
        # fall back on centroid distance for fast-moving faces
        for i, b in enumerate(boxes):
            if i in assigned:
                continue
            cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
            best, best_d = None, 1e9
            for tid, t in self.tracks.items():
                if tid in used:
                    continue
                d = np.hypot(cx - (t.bbox[0] + t.bbox[2] / 2), cy - (t.bbox[1] + t.bbox[3] / 2))
                if d < best_d and d < max(b[2], b[3]) * 1.2:
                    best, best_d = tid, d
            if best is not None:
                used.add(best)
                assigned[i] = self.tracks[best]
        out = []
        for i, b in enumerate(boxes):
            t = assigned.get(i)
            if t is None:
                t = Track(self._next, b, now, now)
                self.tracks[t.id] = t
                self._next += 1
            t.bbox, t.last_seen = tuple(b), now
            t.frames += 1
            out.append(t)
        for tid in [tid for tid, t in self.tracks.items() if now - t.last_seen > self.max_missing]:
            del self.tracks[tid]
        return out

    def vote(self, track: Track, identity: Optional[str], score: float, liveness: float) -> None:
        track.votes.append(identity)
        track.liveness.append(liveness)
        track.scores.setdefault(identity, deque(maxlen=12)).append(score)

    def resolve(self, track: Track) -> tuple[Optional[str], float, float, bool]:
        """(identity, mean match score, liveness, stable)."""
        if not track.votes:
            return None, 0.0, 1.0, False
        counts = Counter(track.votes)
        identity, n = counts.most_common(1)[0]
        stable = len(track.votes) >= self.confirm and n / len(track.votes) >= 0.6
        score = float(np.mean(track.scores.get(identity, [0.0])))
        live = float(np.mean(track.liveness)) if track.liveness else 1.0
        return identity, score, live, stable

    def to_observation(self, track: Track, profiles: dict, zone: str, now: datetime) -> PersonObservation:
        identity, score, live, stable = self.resolve(track)
        role = profiles.get(identity, {}).get("role", "unknown") if identity else "unknown"
        return PersonObservation(
            track_id=track.id, identity=identity, role=role, match_score=score, liveness=live, zone=zone,
            first_seen=track.first_seen, dwell_s=(now - track.first_seen).total_seconds(),
            approx_age="child" if role == "child" else "unknown", bbox=tuple(int(v) for v in track.bbox), stable=stable)
