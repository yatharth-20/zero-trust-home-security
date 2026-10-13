"""Project: AI-Based Zero-Trust Smart Home Security And Child Safety System
Authors: Humera Tahzeeb (GE-232023385), Megha Saxena (GE-232023450), Yatharth Verma (GE-232023727)
Supervisor: Dr. Neha Tripathi, Graphic Era Deemed to be University, Dehradun
Academic Year: 2025-2026
Module: Acoustic Anomaly Detection Engine (Distress / Glass Break / Scream)
"""
from __future__ import annotations

import math
import threading
import time
from typing import Optional


class AudioAnomalyDetector:
    """Acoustic monitoring engine for domestic distress and forced entry sounds."""

    def __init__(self, threshold_db: float = 75.0, listen_mic: bool = False):
        self.threshold_db = threshold_db
        self.listen_mic = listen_mic
        self._lock = threading.Lock()
        self._anomaly_active = False
        self._last_event: Optional[str] = None
        self._last_level: float = 40.0
        self._expiry: float = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None

        if self.listen_mic:
            self._start_listener()

    def _start_listener(self) -> None:
        try:
            import pyaudio  # type: ignore
            self._running = True
            self._thread = threading.Thread(target=self._mic_worker, daemon=True)
            self._thread.start()
        except ImportError:
            print("[audio] pyaudio not installed. Running in event/trigger mode.")

    def _mic_worker(self) -> None:  # pragma: no cover - hardware dependent
        try:
            import pyaudio  # type: ignore
            import numpy as np

            p = pyaudio.PyAudio()
            stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000,
                            input=True, frames_per_buffer=1024)
            while self._running:
                data = stream.read(1024, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16).astype(np.float32)
                rms = np.sqrt(np.mean(audio_data ** 2) + 1e-9)
                db = 20 * math.log10(max(rms, 1.0))
                with self._lock:
                    self._last_level = db
                    if db >= self.threshold_db:
                        self._anomaly_active = True
                        self._last_event = "Acoustic decibel spike (scream/crash)"
                        self._expiry = time.monotonic() + 3.0  # latch for 3 seconds
                time.sleep(0.05)
        except Exception as exc:
            print(f"[audio] mic listener stopped: {exc}")

    def trigger_anomaly(self, event_type: str = "Glass shatter / child scream", db_level: float = 85.0, hold_s: float = 3.0) -> None:
        """Manually or simulation-triggered acoustic distress."""
        with self._lock:
            self._anomaly_active = True
            self._last_event = event_type
            self._last_level = db_level
            self._expiry = time.monotonic() + hold_s

    def check(self) -> tuple[bool, Optional[str], float]:
        """Returns (is_anomaly, event_description, current_level_db)."""
        now = time.monotonic()
        with self._lock:
            if self._anomaly_active and now < self._expiry:
                return True, self._last_event, self._last_level
            elif self._anomaly_active and now >= self._expiry:
                self._anomaly_active = False
                self._last_event = None
            return False, None, self._last_level
