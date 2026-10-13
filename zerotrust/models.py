"""Shared data structures that flow between vision, context, risk and alerting."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

LOW, MEDIUM, HIGH = "LOW", "MEDIUM", "HIGH"
LEVEL_RANK = {LOW: 0, MEDIUM: 1, HIGH: 2}

GUARDIAN_ROLES = {"owner", "family"}  # supervising adults
TRUST_COMPONENTS = ("identity", "liveness", "schedule", "location", "behavior")


@dataclass
class PersonObservation:
    """One tracked person in the current scene."""

    track_id: int
    identity: Optional[str] = None      # profile name, None => unrecognised
    role: str = "unknown"               # owner|family|child|worker|guest|unknown
    match_score: float = 0.0            # cosine similarity of the best face match
    liveness: float = 1.0               # 0..1 (1 = confidently a live human)
    zone: str = "entry"
    first_seen: Optional[datetime] = None
    dwell_s: float = 0.0
    approx_age: str = "unknown"         # adult|child|unknown
    bbox: tuple = (0, 0, 0, 0)
    stable: bool = True                 # identity vote has settled

    @property
    def known(self) -> bool:
        return self.identity is not None

    @property
    def is_child(self) -> bool:
        return self.role == "child" or (self.identity is None and self.approx_age == "child")

    def to_dict(self) -> dict:
        return {
            "track_id": self.track_id, "identity": self.identity, "role": self.role,
            "match_score": round(self.match_score, 3), "liveness": round(self.liveness, 3),
            "zone": self.zone, "dwell_s": round(self.dwell_s, 1), "approx_age": self.approx_age,
            "bbox": list(self.bbox), "stable": self.stable,
        }


@dataclass
class SensorState:
    door_open: bool = False
    pir_motion: bool = False
    online: bool = True
    acoustic_anomaly: bool = False
    sound_level_db: float = 0.0

    def to_dict(self) -> dict:
        return {"door_open": self.door_open, "pir_motion": self.pir_motion, "online": self.online,
                "acoustic_anomaly": self.acoustic_anomaly, "sound_level_db": round(self.sound_level_db, 1)}


@dataclass
class SceneObservation:
    timestamp: datetime
    persons: list[PersonObservation] = field(default_factory=list)
    sensors: SensorState = field(default_factory=SensorState)
    camera_zone: str = "entry"
    camera_ok: bool = True
    # Acoustic anomaly detection in visual blind spots
    acoustic_event: Optional[str] = None
    lighting_lux: float = 100.0
    # Optional ground-truth hints (simulation / manual guardian presence toggle).
    adult_home_hint: Optional[bool] = None
    child_home_hint: Optional[bool] = None


@dataclass
class Signal:
    name: str
    category: str            # identity|liveness|schedule|location|behavior|sensor|context|tailgating
    points: float
    reason: str
    person_ids: tuple = ()

    def to_dict(self) -> dict:
        return {"name": self.name, "category": self.category, "points": round(self.points, 1),
                "reason": self.reason, "person_ids": list(self.person_ids)}


@dataclass
class Assessment:
    timestamp: datetime
    score: float
    level: str
    signals: list[Signal]
    trust: dict                       # components (0-1) + "overall" (0-100)
    persons: list[dict]
    children_alone: bool
    summary: str
    action: str
    latency_ms: float = 0.0

    @property
    def rank(self) -> int:
        return LEVEL_RANK[self.level]

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(), "score": round(self.score, 1), "level": self.level,
            "signals": [s.to_dict() for s in self.signals], "trust": self.trust,
            "persons": self.persons, "children_alone": self.children_alone,
            "summary": self.summary, "action": self.action, "latency_ms": round(self.latency_ms, 3),
        }
