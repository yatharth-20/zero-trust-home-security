"""Live camera runner and face enrolment."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np

from .config import Config, ROOT, data_dir
from .models import HIGH, LOW, MEDIUM, SceneObservation
from .pipeline import SecuritySystem
from .vision.face_engine import FaceEngine, FaceGallery
from .vision.liveness import LivenessChecker
from .vision.tracker import FaceTracker

import cv2

COLORS = {LOW: (110, 210, 100), MEDIUM: (60, 175, 250), HIGH: (70, 70, 245)}  # BGR
ZONE_KEYS = {ord(str(i + 1)): z for i, z in enumerate(["entry", "living_room", "kitchen", "study", "bedroom"])}


def open_camera(source: int | str, width: int, height: int):
    """Open a camera source - supports standard USB indices, RTSP IP camera streams, or video URLs (Limitation #1 Fix)."""
    if isinstance(source, str) and ("://" in source or source.endswith(".mp4")):
        cap = cv2.VideoCapture(source)
    else:
        try:
            idx = int(source)
        except (ValueError, TypeError):
            idx = 0
        cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(idx)
        if not cap.isOpened():
            cap = cv2.VideoCapture(idx)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


class ThreadedCamera:
    """Threaded camera reader to decouple I/O and eliminate frame latency on Core i3 / 8GB RAM (Limitation #5 Fix)."""

    def __init__(self, source: int | str, width: int, height: int):
        import threading
        self.source = source
        self.cap = open_camera(source, width, height)
        self.ret = False
        self.frame = None
        self.running = False
        self.lock = threading.Lock()
        if self.cap.isOpened():
            self.ret, self.frame = self.cap.read()
            self.running = True
            self.thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.thread.start()

    def _capture_loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.ret, self.frame = ok, frame
            else:
                time.sleep(0.01)

    def read(self):
        with self.lock:
            return self.ret, self.frame.copy() if self.frame is not None else None

    def isOpened(self):
        return self.cap.isOpened()

    def release(self):
        self.running = False
        self.cap.release()


def enroll(cfg: Config, name: str, images: Optional[Path] = None, samples: int = 20, camera: Optional[int] = None) -> int:
    """Capture face embeddings for ``name`` from the webcam or a folder of images."""
    engine = FaceEngine(ROOT / "models", cfg["vision"]["detector_score"])
    if not engine.recognition:
        raise SystemExit("Face recognition models are unavailable - cannot enrol.")
    gallery = FaceGallery(data_dir(cfg) / "faces")
    embs = []
    if images:
        for p in sorted(Path(images).glob("*")):
            img = cv2.imread(str(p))
            if img is None:
                continue
            faces = engine.detect(img)
            if len(faces) == 1:
                e = engine.embed(img, faces[0])
                if e is not None:
                    embs.append(e)
    else:
        cap = open_camera(cfg["vision"]["camera_index"] if camera is None else camera, 960, 540)
        last = 0.0
        print(f"Enrolling '{name}': look at the camera, vary your angle slightly. Press q to abort.")
        while len(embs) < samples:
            ok, frame = cap.read()
            if not ok:
                break
            faces = engine.detect(frame)
            msg = f"{len(embs)}/{samples} samples"
            if len(faces) == 1 and time.time() - last > 0.25:
                e = engine.embed(frame, faces[0])
                if e is not None:
                    embs.append(e)
                    last = time.time()
            elif len(faces) != 1:
                msg = "exactly one face must be visible"
            for f in faces:
                x, y, w, h = [int(v) for v in f[:4]]
                cv2.rectangle(frame, (x, y), (x + w, y + h), (110, 210, 100), 2)
            cv2.putText(frame, f"Enrolling {name}: {msg}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.imshow("Enrol", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
        cap.release()
        cv2.destroyAllWindows()
    if embs:
        gallery.add(name, np.vstack(embs))
    return len(embs)


class LiveRunner:
    """Camera -> faces -> tracks -> SceneObservation -> SecuritySystem."""

    def __init__(self, system: SecuritySystem, cfg: Config, show_window: bool = True, camera: Optional[int | str] = None):
        self.system, self.cfg, self.show = system, cfg, show_window
        v = cfg["vision"]
        self.camera_sources = v.get("camera_sources") or [{"id": v.get("camera_index", 0), "zone": v.get("camera_zone", "entry"), "name": "Primary Cam"}]
        self.cam_ptr = 0
        self.camera_index = self.camera_sources[0]["id"] if camera is None else camera
        self.engine = FaceEngine(ROOT / "models", v["detector_score"],
                                 adaptive_clahe=v.get("adaptive_clahe", True),
                                 detection_scale=v.get("detection_scale", 0.5))
        self.gallery = FaceGallery(system.dir / "faces")
        self.liveness = LivenessChecker(v["liveness_window"])
        self.tracker = FaceTracker(cfg["timing"]["confirm_frames"])
        self.running = False
        if not self.gallery.embeddings:
            print("[live] No enrolled faces yet - everyone will be treated as UNRECOGNISED. "
                  "Run:  python main.py enroll --name Homeowner")

    def process(self, frame, now: datetime) -> tuple[SceneObservation, list]:
        faces = self.engine.detect(frame)
        boxes = [tuple(float(v) for v in f[:4]) for f in faces]
        tracks = self.tracker.update(boxes, now)
        thr = self.cfg["risk"]["match_threshold"]
        for t, f in zip(tracks, faces):
            ident, score = None, 0.0
            if self.engine.recognition and self.gallery.embeddings:
                emb = self.engine.embed(frame, f)
                if emb is not None:
                    ident, score = self.gallery.match(emb, thr)
            live = self.liveness.update(t.id, frame, f)
            self.tracker.vote(t, ident, score, live)
        zone = self.system.active_zone
        persons = [self.tracker.to_observation(t, self.cfg["profiles"], zone, now) for t in tracks]
        mean_lum = float(frame.mean())
        camera_ok = mean_lum > 8.0  # covered / blacked-out lens counts as tamper
        obs = SceneObservation(now, persons, self.system.link.read(), zone, camera_ok=camera_ok,
                               lighting_lux=mean_lum)
        return obs, persons

    def annotate(self, frame, persons, assessment) -> None:
        for p in persons:
            x, y, w, h = p.bbox
            spoof = p.liveness < self.cfg["risk"]["liveness_threshold"]
            color = (70, 70, 245) if (not p.known or spoof) else (110, 210, 100)
            if not p.stable:
                color = (180, 180, 180)
            label = (p.identity or "UNKNOWN") + (" [SPOOF?]" if spoof and p.stable else "")
            if not p.stable:
                label = "verifying..."
            cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
            cv2.putText(frame, f"{label}  live {p.liveness:.2f}", (x, max(14, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        if assessment is not None:
            col = COLORS[assessment.level]
            cv2.rectangle(frame, (0, 0), (frame.shape[1], 34), col, -1)
            s = self.system.last_obs.sensors if self.system.last_obs else None
            sens = f"door:{'OPEN' if s and s.door_open else 'closed'} pir:{'MOTION' if s and s.pir_motion else '-'}"
            if s and s.acoustic_anomaly:
                sens += " audio:SPIKE!"
            cv2.putText(frame, f"{assessment.level} {assessment.score:.0f}/100 | {assessment.summary[:42]} | "
                        f"zone:{self.system.active_zone} | {sens}", (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (15, 15, 15), 2)

    def run(self) -> None:
        v = self.cfg["vision"]
        cap = ThreadedCamera(self.camera_index, v["frame_width"], v["frame_height"])
        if not cap.isOpened():
            raise SystemExit(f"Could not open camera {self.camera_index}")
        self.running = True
        n, assessment = 0, None
        print("[live] running. Keys: q quit | 1-5 switch zone | c switch camera | d toggle door | p PIR pulse | a guardian-away toggle | s silence")
        try:
            while self.running:
                ok, frame = cap.read()
                if not ok or frame is None:
                    time.sleep(0.02)
                    continue
                n += 1
                now = datetime.now()
                persons = []
                if n % v["process_every_n"] == 0:
                    obs, persons = self.process(frame, now)
                    self.annotate(frame, persons, assessment)
                    assessment, _ = self.system.ingest(obs, frame)
                    self.annotate(frame, [], assessment)
                else:
                    self.annotate(frame, [], assessment)
                ok2, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                if ok2:
                    self.system.last_jpeg = jpg.tobytes()
                if self.show:
                    cv2.imshow("Zero-Trust Home Security", frame)
                    k = cv2.waitKey(1) & 0xFF
                    if k == ord("q"):
                        break
                    if k in ZONE_KEYS:
                        self.system.active_zone = ZONE_KEYS[k]
                    elif k == ord("c"):
                        # Limitation #1 Fix: Switch camera angle/stream
                        if len(self.camera_sources) > 1:
                            self.cam_ptr = (self.cam_ptr + 1) % len(self.camera_sources)
                            new_source = self.camera_sources[self.cam_ptr]
                            print(f"[live] Switching camera to: {new_source.get('name', new_source['id'])}")
                            cap.release()
                            cap = ThreadedCamera(new_source["id"], v["frame_width"], v["frame_height"])
                            self.system.active_zone = new_source.get("zone", self.system.active_zone)
                    elif k == ord("d"):
                        self.system.link.set(door=not self.system.link.read().door_open)
                    elif k == ord("p"):
                        self.system.link.set(pir=True)
                    elif k == ord("a"):
                        cur = self.system.household.manual_adults_away
                        self.system.set_adults_away(None if cur else True)
                    elif k == ord("s"):
                        self.system.alerts.silence()
                else:
                    time.sleep(0.005)
        finally:
            cap.release()
            cv2.destroyAllWindows()
