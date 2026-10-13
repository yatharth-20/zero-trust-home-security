"""ESP32 hardware link: magnetic door contact + PIR input, siren output.

Serial protocol (newline separated, 115200 baud) - see ``firmware/``:
    ESP32 -> PC :  ``DOOR:1`` / ``DOOR:0`` / ``PIR:1`` / ``PIR:0`` / ``HELLO``
    PC -> ESP32 :  ``ALARM:1`` / ``ALARM:0``

When no serial port is configured the link runs in *simulated* mode so the
whole system (and the dashboard) can be exercised without hardware.
"""
from __future__ import annotations

import threading
import time
from typing import Optional

from .models import SensorState


class ESP32Link:
    def __init__(self, port: str = "", baud: int = 115200, pir_hold_s: float = 5.0, door_hold_s: float = 0.0):
        self.port, self.baud = port, baud
        self.simulated = not port
        self.pir_hold_s = pir_hold_s
        self._lock = threading.Lock()
        self._door = False
        self._pir_until = 0.0
        self._door_until = 0.0
        self._door_hold_s = door_hold_s
        self.alarm_on = False
        self.online = True
        self._serial = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        if not self.simulated:
            self._connect()

    # ---- hardware ------------------------------------------------------
    def _connect(self) -> None:
        try:
            import serial  # type: ignore
            self._serial = serial.Serial(self.port, self.baud, timeout=0.5)
            self._thread = threading.Thread(target=self._reader, daemon=True)
            self._thread.start()
        except Exception as exc:  # pragma: no cover - hardware dependent
            print(f"[esp32] could not open {self.port}: {exc} -> falling back to simulated sensors")
            self.simulated, self.online = True, True
            self._serial = None

    def _reader(self) -> None:  # pragma: no cover - hardware dependent
        while not self._stop.is_set():
            try:
                line = self._serial.readline().decode(errors="ignore").strip()
            except Exception:
                self.online = False
                time.sleep(1)
                continue
            if not line:
                continue
            self.online = True
            key, _, val = line.partition(":")
            if key == "DOOR":
                self.set(door=(val == "1"))
            elif key == "PIR" and val == "1":
                self.set(pir=True)

    # ---- state ---------------------------------------------------------
    def set(self, door: Optional[bool] = None, pir: Optional[bool] = None) -> None:
        now = time.monotonic()
        with self._lock:
            if door is not None:
                self._door = door
                if door and self._door_hold_s:
                    self._door_until = now + self._door_hold_s
            if pir:
                self._pir_until = now + self.pir_hold_s

    def read(self) -> SensorState:
        now = time.monotonic()
        with self._lock:
            return SensorState(door_open=self._door or now < self._door_until,
                               pir_motion=now < self._pir_until, online=self.online)

    def set_alarm(self, on: bool) -> None:
        self.alarm_on = on
        if self._serial is not None:  # pragma: no cover - hardware dependent
            try:
                self._serial.write(b"ALARM:1\n" if on else b"ALARM:0\n")
            except Exception:
                self.online = False

    def close(self) -> None:
        self._stop.set()
        if self._serial is not None:  # pragma: no cover
            self._serial.close()
