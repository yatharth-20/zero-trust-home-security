"""Behaviour baseline: learns household routines and scores deviations.

For every identity (and a shared ``__visitor__`` key for unrecognised people)
we maintain a smoothed 24-bin histogram of arrival hours.  The *surprise* of a
new arrival is ``-ln p(hour) / ln 24`` - 1.0 means "as unlikely as a uniformly
random hour".  Surprise above a floor is converted to risk points, so routine
arrivals cost nothing and sharp departures from the learned rhythm add risk
without any hand-written rule.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

VISITOR_KEY = "__visitor__"


class BehaviorBaseline:
    def __init__(self, path: Optional[Path] = None, alpha: float = 0.5, min_observations: int = 8,
                 surprise_floor: float = 0.9, surprise_span: float = 0.5):
        self.path = Path(path) if path else None
        self.alpha = alpha
        self.min_obs = min_observations
        self.floor = surprise_floor
        self.span = surprise_span
        self.hist: dict[str, np.ndarray] = {}
        if self.path and self.path.exists():
            self.load()

    # ---- learning -----------------------------------------------------
    def observe(self, key: str, ts: datetime, weight: float = 1.0) -> None:
        h = self.hist.setdefault(key, np.zeros(24))
        h[ts.hour] += weight

    def observation_count(self, key: str) -> float:
        h = self.hist.get(key)
        return float(h.sum()) if h is not None else 0.0

    # ---- scoring ------------------------------------------------------
    def _smoothed(self, h: np.ndarray) -> np.ndarray:
        return 0.5 * h + 0.25 * np.roll(h, 1) + 0.25 * np.roll(h, -1)

    def surprise(self, key: str, ts: datetime) -> Optional[float]:
        h = self.hist.get(key)
        if h is None or h.sum() < self.min_obs:
            return None  # cold start: not enough evidence to call anything abnormal
        sm = self._smoothed(h)
        p = (sm[ts.hour] + self.alpha) / (sm.sum() + self.alpha * 24)
        return float(-math.log(p) / math.log(24))

    def deviation_points(self, key: str, ts: datetime, max_points: float) -> tuple[float, Optional[str]]:
        s = self.surprise(key, ts)
        if s is None:
            return 0.0, None
        frac = min(1.0, max(0.0, (s - self.floor) / self.span))
        if frac <= 0:
            return 0.0, None
        label = "visitors" if key == VISITOR_KEY else key
        return max_points * frac, f"Arrival at {ts:%H:%M} is unusual for {label} (surprise {s:.2f})"

    # ---- persistence --------------------------------------------------
    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({k: v.tolist() for k, v in self.hist.items()}), encoding="utf-8")

    def load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.hist = {k: np.array(v, dtype=float) for k, v in raw.items()}

    def seed_routine(self, rng: np.random.Generator, days: int = 30) -> None:
        """Seed a plausible household routine (used by demo/evaluation, not live)."""
        for _ in range(days):
            for _ in range(2):  # homeowner: morning + evening, occasionally late
                self.observe("Homeowner", datetime(2026, 1, 1, int(np.clip(rng.normal(8, 1), 5, 11))))
                self.observe("Homeowner", datetime(2026, 1, 1, int(np.clip(rng.normal(19, 2), 14, 23))))
            self.observe("Spouse", datetime(2026, 1, 1, int(np.clip(rng.normal(9, 1.5), 6, 12))))
            self.observe("Spouse", datetime(2026, 1, 1, int(np.clip(rng.normal(20, 2), 15, 23))))
            self.observe("Child", datetime(2026, 1, 1, int(np.clip(rng.normal(15, 1), 13, 17))))
            if rng.random() < 0.7:  # school pick-up
                self.observe("Spouse", datetime(2026, 1, 1, int(np.clip(rng.normal(15, 1), 13, 17))))
            self.observe("Worker", datetime(2026, 1, 1, int(np.clip(rng.normal(11.5, 2), 9, 16))))
            if rng.random() < 0.6:  # deliveries / visitors mostly in daytime
                self.observe(VISITOR_KEY, datetime(2026, 1, 1, int(np.clip(rng.normal(13, 3), 9, 19))))
