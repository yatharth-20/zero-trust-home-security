"""Project: AI-Based Zero-Trust Smart Home Security And Child Safety System
Authors: Humera Tahzeeb (GE-232023385), Megha Saxena (GE-232023450), Yatharth Verma (GE-232023727)
Supervisor: Dr. Neha Tripathi, Graphic Era Deemed to be University, Dehradun
Academic Year: 2025-2026
Module: Top-Level Multi-Modal Pipeline Orchestrator
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from .alerts import AlertDecision, AlertManager
from .baseline import VISITOR_KEY, BehaviorBaseline
from .config import Config, data_dir as resolve_data_dir
from .context import ContextModel, HouseholdState
from .evidence import EvidenceStore
from .models import LEVEL_RANK, MEDIUM, Assessment, SceneObservation
from .risk import RiskEngine
from .sensors import ESP32Link


class SecuritySystem:
    def __init__(self, cfg: Config, data_dir: Optional[Path] = None, baseline: Optional[BehaviorBaseline] = None,
                 local_beep: Optional[bool] = None, link: Optional[ESP32Link] = None, mode: str = "live"):
        self.cfg = cfg
        self.mode = mode
        self.dir = Path(data_dir) if data_dir else resolve_data_dir(cfg)
        self.dir.mkdir(parents=True, exist_ok=True)
        b = cfg["baseline"]
        self.baseline = baseline or BehaviorBaseline(self.dir / "baseline.json", b["alpha"], b["min_observations"],
                                                     b["surprise_floor"], b["surprise_span"])
        self.ctx = ContextModel(cfg)
        self.household = HouseholdState(cfg["timing"]["presence_timeout_s"])
        self.engine = RiskEngine(cfg, self.baseline, self.ctx, self.household)
        self.link = link or ESP32Link(cfg["alerts"]["esp32_port"], cfg["alerts"]["esp32_baud"])
        self.alerts = AlertManager(cfg, self.link, self.dir, local_beep=local_beep)
        self.evidence = EvidenceStore(self.dir, cfg)
        from .audio import AudioAnomalyDetector
        a_cfg = cfg.get("audio", {})
        self.audio = AudioAnomalyDetector(threshold_db=a_cfg.get("threshold_db", 75.0),
                                          listen_mic=a_cfg.get("listen_mic", False))
        self.lock = threading.RLock()
        self.last: Optional[Assessment] = None
        self.last_obs: Optional[SceneObservation] = None
        self.timeline: deque = deque(maxlen=180)
        self.last_jpeg: Optional[bytes] = None
        self.active_zone: str = cfg["vision"]["camera_zone"]
        self.scenario_name: Optional[str] = None

    # ------------------------------------------------------------- pipeline
    def ingest(self, obs: SceneObservation, frame=None) -> tuple[Assessment, AlertDecision]:
        with self.lock:
            # Check audio sensor for blind-spot distress/glass breaking (Limitation #6 Fix)
            if not obs.sensors.acoustic_anomaly and not obs.acoustic_event:
                is_anom, desc, db = self.audio.check()
                if is_anom:
                    obs.sensors.acoustic_anomaly = True
                    obs.sensors.sound_level_db = db
                    obs.acoustic_event = desc
            a = self.engine.assess(obs)
            self.engine.learn(obs, a)

            # Generate camera frame with persons & faces if no physical webcam frame is supplied (demo / simulation)
            if frame is None:
                try:
                    from .vision.synthetic_camera import render_scene_frame
                    import cv2
                    synth = render_scene_frame(obs, a)
                    ok, jpg = cv2.imencode(".jpg", synth, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        self.last_jpeg = jpg.tobytes()
                        frame = synth
                except Exception:
                    pass
            elif frame is not None:
                try:
                    import cv2
                    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok:
                        self.last_jpeg = jpg.tobytes()
                except Exception:
                    pass

            decision = self.alerts.process(a)
            if decision.fire:
                event_id = self.evidence.log_event(a, decision.incident_id, decision.actions)
                if decision.capture_evidence:
                    self.evidence.capture(event_id, a, frame)
            self.evidence.feed_frame(frame)
            self.last, self.last_obs = a, obs
            self.timeline.append({"t": obs.timestamp.isoformat(timespec="seconds"),
                                  "score": round(a.score, 1), "level": a.level})
            return a, decision

    # ------------------------------------------------------------- guardian
    def override(self, event_id: int, decision: str) -> dict:
        decision = decision.lower()
        if decision not in ("allow", "deny"):
            return {"ok": False, "error": "decision must be allow|deny"}
        with self.lock:
            ev = self.evidence.get(event_id)
            if not ev:
                return {"ok": False, "error": "unknown event"}
            self.evidence.set_decision(event_id, decision)
            self.alerts.guardian_decision(decision)
            if decision == "allow":  # teach the baseline: this was legitimate
                ts = datetime.fromisoformat(ev["ts"])
                for p in ev["persons"]:
                    self.baseline.observe(p.get("identity") or VISITOR_KEY, ts)
            self.baseline.save()
            return {"ok": True, "event": event_id, "decision": decision}

    def set_adults_away(self, away: Optional[bool]) -> None:
        self.household.manual_adults_away = away

    # ------------------------------------------------------------ dashboard
    def snapshot(self) -> dict:
        with self.lock:
            a = self.last
            events = self.evidence.recent(25)
            pending = [e for e in events if LEVEL_RANK[e["level"]] >= LEVEL_RANK[MEDIUM] and not e["decision"]][:5]
            slim = [{k: e[k] for k in ("id", "ts", "level", "score", "summary", "decision", "snapshot", "video", "actions")}
                    for e in events]
            inc = self.alerts.incident
            return {
                "mode": self.mode,
                "scenario": self.scenario_name,
                "assessment": a.to_dict() if a else None,
                "sensors": self.last_obs.sensors.to_dict() if self.last_obs else {},
                "zone": self.active_zone,
                "zones": {k: {"label": v["label"], "access": v["access"]} for k, v in self.cfg["zones"].items()},
                "timeline": list(self.timeline),
                "pending": pending,
                "events": slim,
                "incident": ({"id": inc.id, "max_rank": inc.max_rank, "suppressed": inc.suppressed,
                              "confirmed": inc.confirmed} if inc else None),
                "alarm_active": bool(self.alerts.alarm.active or self.link.alarm_on),
                "stats": {"alerts": self.alerts.total_alerts, "suppressed": self.alerts.total_suppressed,
                          "events": self.evidence.count(),
                          "offline_buffered": len(self.alerts.sms.queue.load())},
                "adults_away": self.household.manual_adults_away,
                "sms_outbox": self.alerts.sms.sent[-5:],
                "offline_queue_count": len(self.alerts.sms.queue.load()),
                "lighting_lux": self.last_obs.lighting_lux if self.last_obs else 100.0,
                "camera_sources": self.cfg["vision"].get("camera_sources", [{"id": 0, "name": "Main Entrance", "zone": "entry"}]),
            }

    def close(self) -> None:
        self.baseline.save()
        self.alerts.silence()
        self.link.close()
        self.evidence.close()
