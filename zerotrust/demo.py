"""Demo mode: plays simulated scenarios through the real pipeline (no camera needed)."""
from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np

from .config import Config
from .pipeline import SecuritySystem
from .simulation import BENIGN, THREAT, ScenarioFactory


class DemoPlayer:
    def __init__(self, system: SecuritySystem, cfg: Config, speed: float = 1.0, seed: int = 5):
        self.system, self.cfg, self.speed = system, cfg, speed
        self.factory = ScenarioFactory(cfg, seed=seed, false_reject=0.0, false_accept=0.0, sensor_dropout=0.0)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._auto = threading.Event()
        self._stop = threading.Event()
        self.playing: Optional[str] = None

    def catalogue(self) -> dict:
        out = {"benign": [], "threat": []}
        for key in BENIGN + THREAT:
            sc = getattr(self.factory, key)()
            out[sc.label].append({"key": key, "title": sc.title, "description": sc.description})
        return out

    def play(self, key: str) -> bool:
        if key not in BENIGN + THREAT or (self._thread and self._thread.is_alive()):
            return False
        sc = getattr(self.factory, key)()
        self._thread = threading.Thread(target=self._run, args=(sc,), daemon=True)
        self._thread.start()
        return True

    def _run(self, sc) -> None:
        with self._lock:
            self.playing = sc.key
            self.system.scenario_name = sc.title
            for obs in sc.frames:
                if self._stop.is_set():
                    break
                frame = None
                self.system.ingest(obs, frame)
                time.sleep(1.0 / max(self.speed, 0.05))
            self.playing = None

    def start_auto(self, pause_s: float = 4.0) -> None:
        """Continuously play random scenarios (hands-free demo)."""
        self._auto.set()

        def loop():
            rng = np.random.default_rng(1)
            while self._auto.is_set() and not self._stop.is_set():
                if not (self._thread and self._thread.is_alive()):
                    pool = THREAT if rng.random() < 0.5 else BENIGN
                    self.play(pool[int(rng.integers(len(pool)))])
                    time.sleep(pause_s)
                time.sleep(0.5)
        threading.Thread(target=loop, daemon=True).start()

    def stop(self) -> None:
        self._auto.clear()
        self._stop.set()
