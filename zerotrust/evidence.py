"""Automatic evidence log: SQLite event journal + snapshot + pre/post-roll video."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import Config
from .models import Assessment

try:  # OpenCV is only needed for media; the journal works without it.
    import cv2
    import numpy as np
except Exception:  # pragma: no cover
    cv2, np = None, None

LEVEL_COLORS = {"LOW": (120, 200, 90), "MEDIUM": (60, 180, 245), "HIGH": (70, 70, 240)}  # BGR


def render_scene_card(a: Assessment, width: int = 800, height: int = 450):
    """Synthetic evidence frame used when there is no live camera image (demo/simulation)."""
    if cv2 is None:
        return None
    img = np.full((height, width, 3), (28, 22, 18), np.uint8)
    color = LEVEL_COLORS[a.level]
    cv2.rectangle(img, (0, 0), (width, 64), color, -1)
    cv2.putText(img, f"{a.level} RISK  {a.score:.0f}/100", (20, 44), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (20, 20, 20), 3)
    cv2.putText(img, a.summary[:70], (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (240, 240, 240), 2)
    y = 140
    for s in sorted(a.signals, key=lambda s: -abs(s.points))[:7]:
        cv2.putText(img, f"{s.points:+.0f}  {s.reason[:78]}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 210, 220), 1)
        y += 28
    cv2.putText(img, a.timestamp.strftime("%Y-%m-%d %H:%M:%S"), (20, height - 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (160, 170, 180), 1)
    return img


class EvidenceStore:
    def __init__(self, data_dir: Path, cfg: Config):
        self.dir = Path(data_dir)
        self.media = self.dir / "evidence"
        self.media.mkdir(parents=True, exist_ok=True)
        ev = cfg["evidence"]
        self.fps = ev["fps"]
        self.post_roll_s = ev["post_roll_s"]
        self.buffer: deque = deque(maxlen=max(1, int(ev["pre_roll_s"] * self.fps)))
        self._lock = threading.Lock()
        self.db = sqlite3.connect(self.dir / "events.db", check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, incident_id INTEGER, level TEXT, score REAL,
            summary TEXT, reasons TEXT, persons TEXT, trust REAL, actions TEXT,
            snapshot TEXT, video TEXT, decision TEXT, decided_ts TEXT)""")
        self.db.commit()
        self._writer = None
        self._writer_end = 0.0
        self._writer_event: Optional[int] = None
        self._writer_path: Optional[str] = None

    # ------------------------------------------------------------ journal
    def log_event(self, a: Assessment, incident_id: Optional[int], actions: list[str]) -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO events(ts,incident_id,level,score,summary,reasons,persons,trust,actions) VALUES(?,?,?,?,?,?,?,?,?)",
                (a.timestamp.isoformat(), incident_id, a.level, a.score, a.summary,
                 json.dumps([s.to_dict() for s in a.signals]), json.dumps(a.persons),
                 a.trust.get("overall"), json.dumps(actions)))
            self.db.commit()
            return int(cur.lastrowid)

    def set_decision(self, event_id: int, decision: str) -> None:
        with self._lock:
            self.db.execute("UPDATE events SET decision=?, decided_ts=? WHERE id=?",
                            (decision, datetime.now().isoformat(timespec="seconds"), event_id))
            self.db.commit()

    def _row(self, r) -> dict:
        cols = ["id", "ts", "incident_id", "level", "score", "summary", "reasons", "persons", "trust",
                "actions", "snapshot", "video", "decision", "decided_ts"]
        d = dict(zip(cols, r))
        for k in ("reasons", "persons", "actions"):
            d[k] = json.loads(d[k]) if d[k] else []
        return d

    def recent(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def get(self, event_id: int) -> Optional[dict]:
        with self._lock:
            r = self.db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        return self._row(r) if r else None

    def count(self) -> int:
        with self._lock:
            return self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def _set_media(self, event_id: int, **cols) -> None:
        with self._lock:
            for k, v in cols.items():
                self.db.execute(f"UPDATE events SET {k}=? WHERE id=?", (v, event_id))
            self.db.commit()

    # -------------------------------------------------------------- media
    def feed_frame(self, frame) -> None:
        """Call for every processed camera frame (keeps the pre-roll buffer + records post-roll)."""
        if frame is None or cv2 is None:
            return
        self.buffer.append(frame.copy())
        if self._writer is not None:
            self._writer.write(frame)
            if time.monotonic() >= self._writer_end:
                self._finish_video()

    def capture(self, event_id: int, a: Assessment, frame=None) -> dict:
        """Save a snapshot and (when live frames exist) start the video clip."""
        if cv2 is None:
            return {}
        stamp = a.timestamp.strftime("%Y%m%d_%H%M%S")
        live = frame is not None
        img = frame if live else render_scene_card(a)
        snap = self.media / f"event{event_id}_{stamp}.jpg"
        out = img.copy()
        cv2.rectangle(out, (0, 0), (out.shape[1], 30), LEVEL_COLORS[a.level], -1)
        cv2.putText(out, f"#{event_id} {a.level} {a.score:.0f}/100  {a.timestamp:%Y-%m-%d %H:%M:%S}", (8, 21),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (15, 15, 15), 2)
        cv2.imwrite(str(snap), out)
        media = {"snapshot": snap.name}
        if live and self._writer is None:
            h, w = img.shape[:2]
            path = self.media / f"event{event_id}_{stamp}.mp4"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), self.fps, (w, h))
            if writer.isOpened():
                for f in self.buffer:
                    writer.write(f)
                self._writer, self._writer_end = writer, time.monotonic() + self.post_roll_s
                self._writer_event, self._writer_path = event_id, path.name
                media["video"] = path.name
        self._set_media(event_id, **media)
        return media

    def _finish_video(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None

    def close(self) -> None:
        self._finish_video()
        self.db.close()
