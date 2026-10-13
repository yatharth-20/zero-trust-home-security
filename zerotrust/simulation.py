"""Scenario simulator: synthetic household events for demos, tests and evaluation.

Scenarios produce ``SceneObservation`` sequences (one per second) *after* a
noisy recognition layer has been applied - household members are occasionally
rejected, strangers occasionally accepted, liveness scores overlap, sensors
drop out - so System A (face-only) and System B (fusion) are compared on
identical, imperfect inputs.  Ground-truth labels come from the scenario
design: ``threat`` = a situation a guardian should be told about.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

import numpy as np

from .config import Config
from .models import PersonObservation, SceneObservation, SensorState

BASE_DATE = datetime(2026, 3, 2)  # a Monday
STEP_S = 1.0
N_FRAMES = 14


@dataclass
class Scenario:
    key: str
    title: str
    label: str            # "benign" | "threat"
    description: str
    frames: list[SceneObservation]


@dataclass
class _Spec:
    truth: Optional[str]          # true identity (None = stranger)
    zone: str
    arrive: float = 0.0           # seconds after scenario start
    spoof: bool = False


class ScenarioFactory:
    def __init__(self, cfg: Config, seed: int = 7, false_reject: float = 0.04, false_accept: float = 0.01,
                 sensor_dropout: float = 0.05):
        self.cfg = cfg
        self.rng = np.random.default_rng(seed)
        self.fr, self.fa, self.drop = false_reject, false_accept, sensor_dropout
        self.profiles = cfg["profiles"]
        self.confirm = cfg["timing"]["confirm_frames"]
        self._households = [n for n, p in self.profiles.items() if p["role"] in ("owner", "family")]

    # ------------------------------------------------------------ utilities
    def _when(self, hour: float, day: Optional[int] = None) -> datetime:
        d = int(self.rng.integers(0, 6)) if day is None else day
        return BASE_DATE + timedelta(days=d, hours=float(hour))

    def _hour(self, lo: float, hi: float) -> float:
        return float(self.rng.uniform(lo, hi))

    def _recognise(self, spec: _Spec):
        """Noisy recognition layer -> (identity, match_score, liveness)."""
        r = self.rng
        if spec.truth is None:
            if r.random() < self.fa:
                ident = self._households[int(r.integers(len(self._households)))]
                return ident, float(np.clip(r.normal(0.5, 0.05), 0.4, 0.7)), float(np.clip(r.normal(0.85, 0.08), 0, 1))
            return None, float(np.clip(r.normal(0.2, 0.06), 0, 0.35)), float(np.clip(r.normal(0.85, 0.08), 0, 1))
        live = float(np.clip(r.normal(0.25, 0.15), 0, 1)) if spec.spoof else float(np.clip(r.normal(0.85, 0.08), 0, 1))
        if r.random() < self.fr and not spec.spoof:
            return None, float(np.clip(r.normal(0.25, 0.06), 0, 0.35)), live
        return spec.truth, float(np.clip(r.normal(0.66, 0.07), 0.4, 0.95)), live

    def _frames(self, specs: list[_Spec], start: datetime, *, door: tuple = (), pir: bool = True,
                adult_home: Optional[bool] = True, child_home: Optional[bool] = False,
                camera_zone: str = "entry", sensors_always: bool = False) -> list[SceneObservation]:
        recognised = [self._recognise(s) for s in specs]
        dropout = self.rng.random() < self.drop
        frames = []
        for i in range(N_FRAMES):
            t = i * STEP_S
            persons = []
            for tid, (s, (ident, match, live)) in enumerate(zip(specs, recognised), start=1):
                if t < s.arrive:
                    continue
                role = self.profiles[ident]["role"] if ident else "unknown"
                persons.append(PersonObservation(
                    track_id=tid, identity=ident, role=role, match_score=match, liveness=live, zone=s.zone,
                    first_seen=start + timedelta(seconds=s.arrive), dwell_s=t - s.arrive,
                    approx_age="child" if role == "child" else "unknown", bbox=(100 + 90 * tid, 80, 90, 120),
                    stable=(t - s.arrive) >= (self.confirm - 1) * STEP_S))
            door_open = (door[0] <= i < door[1]) if door else False
            pir_on = pir and (i < N_FRAMES - 3 or sensors_always) and (bool(persons) or sensors_always)
            sensors = SensorState(door_open=door_open and not dropout, pir_motion=pir_on and not dropout)
            frames.append(SceneObservation(start + timedelta(seconds=t), persons, sensors, camera_zone,
                                           adult_home_hint=adult_home, child_home_hint=child_home))
        return frames

    def _make(self, key, title, label, desc, frames) -> Scenario:
        return Scenario(key, title, label, desc, frames)

    # --------------------------------------------------------------- benign
    def owner_arrival(self) -> Scenario:
        hour = self._hour(7, 9) if self.rng.random() < 0.5 else self._hour(18, 21)
        who = ["Homeowner", "Spouse"][int(self.rng.integers(2))]
        f = self._frames([_Spec(who, "entry")], self._when(hour), door=(0, 4))
        return self._make("owner_arrival", "Household member arrives", "benign",
                          "A resident comes home during their normal routine.", f)

    def family_evening(self) -> Scenario:
        f = self._frames([_Spec("Spouse", "living_room"), _Spec("Child", "living_room", 1)],
                         self._when(self._hour(17, 21)), camera_zone="living_room")
        return self._make("family_evening", "Family in the living room", "benign",
                          "Parent and child relaxing together in an open zone.", f)

    def worker_scheduled(self) -> Scenario:
        f = self._frames([_Spec("Worker", "entry"), _Spec("Worker", "kitchen", 5)],
                         self._when(self._hour(9.5, 15.5)), door=(0, 4), adult_home=True)
        return self._make("worker_scheduled", "Approved worker, normal hours", "benign",
                          "Cleaner arrives inside the approved window and stays in permitted zones.", f)

    def delivery_visitor(self) -> Scenario:
        f = self._frames([_Spec(None, "entry")], self._when(self._hour(9.5, 18)), door=(0, 3), adult_home=True)
        return self._make("delivery_visitor", "Delivery at the door", "benign",
                          "Unrecognised courier at the entry in daytime; adult is home.", f)

    def late_resident(self) -> Scenario:
        f = self._frames([_Spec("Homeowner", "entry")], self._when(self._hour(20.5, 22.0)), door=(0, 4))
        return self._make("late_resident", "Resident home late", "benign",
                          "Homeowner returns later than average, but still within a learned pattern.", f)

    def child_with_parent(self) -> Scenario:
        f = self._frames([_Spec("Child", "entry"), _Spec("Spouse", "entry", 1)], self._when(self._hour(14.5, 16)),
                         door=(0, 4), child_home=True, adult_home=True)
        return self._make("child_with_parent", "Child arrives with parent", "benign",
                          "School run - a guardian is present throughout.", f)

    def child_alone_quiet(self) -> Scenario:
        f = self._frames([_Spec("Child", "living_room")], self._when(self._hour(15, 17)), child_home=True,
                         adult_home=False, camera_zone="living_room")
        return self._make("child_alone_quiet", "Child home alone, nobody else", "benign",
                          "Child after school with no visitors - normal, no alert needed.", f)

    def phantom_detection(self) -> Scenario:
        f = self._frames([_Spec(None, "living_room")], self._when(self._hour(9, 20)), pir=False,
                         camera_zone="living_room")
        return self._make("phantom_detection", "Phantom camera detection", "benign",
                          "Poster/reflection triggers a face detection; no PIR or door activity.", f)

    def pet_motion(self) -> Scenario:
        f = self._frames([], self._when(self._hour(8, 20)), pir=True, sensors_always=True, camera_zone="living_room")
        return self._make("pet_motion", "Pet triggers PIR", "benign",
                          "PIR fires, door closed, no person in view - minor, log only.", f)

    # --------------------------------------------------------------- threats
    def stranger_bedroom(self) -> Scenario:
        f = self._frames([_Spec(None, "bedroom")], self._when(self._hour(1, 23.5)), door=(0, 3),
                         camera_zone="bedroom")
        return self._make("stranger_bedroom", "Stranger in the bedroom", "threat",
                          "An unrecognised person is inside a restricted room.", f)

    def photo_spoof(self) -> Scenario:
        f = self._frames([_Spec("Homeowner", "entry", spoof=True)], self._when(self._hour(0.5, 23)), door=(0, 3))
        return self._make("photo_spoof", "Photo / screen spoof", "threat",
                          "A printed photo or tablet of the homeowner is held up to the camera.", f)

    def tailgating(self) -> Scenario:
        who = ["Homeowner", "Spouse", "Worker"][int(self.rng.integers(3))]
        hour = self._hour(9.5, 15) if who == "Worker" else self._hour(7, 21)
        f = self._frames([_Spec(who, "entry"), _Spec(None, "entry", float(self.rng.uniform(1, 4)))],
                         self._when(hour), door=(0, 6))
        return self._make("tailgating", "Tailgating at the door", "threat",
                          "A cleared person enters and an unrecognised person slips in behind.", f)

    def worker_after_hours(self) -> Scenario:
        f = self._frames([_Spec("Worker", "entry"), _Spec("Worker", "living_room", 4)],
                         self._when(self._hour(22.8, 26.5)), door=(0, 4), adult_home=False)
        return self._make("worker_after_hours", "Worker outside approved hours", "threat",
                          "The recognised worker appears near midnight, owners away.", f)

    def worker_restricted(self) -> Scenario:
        zone = ["study", "bedroom"][int(self.rng.integers(2))]
        f = self._frames([_Spec("Worker", "entry"), _Spec("Worker", zone, 4)], self._when(self._hour(10, 15)),
                         door=(0, 3), adult_home=False)
        return self._make("worker_restricted", "Worker enters restricted room", "threat",
                          f"A cleared worker walks into the {zone}, outside their permitted zones.", f)

    def child_alone_worker(self) -> Scenario:
        f = self._frames([_Spec("Worker", "entry")], self._when(self._hour(10, 15)), door=(0, 4),
                         child_home=True, adult_home=False)
        return self._make("child_alone_worker", "Worker arrives, child alone", "threat",
                          "Same arrival as a routine visit - but a child is home with no guardian.", f)

    def child_alone_stranger(self) -> Scenario:
        f = self._frames([_Spec(None, "entry")], self._when(self._hour(10, 21)), door=(0, 4),
                         child_home=True, adult_home=False)
        return self._make("child_alone_stranger", "Stranger, child home alone", "threat",
                          "Unrecognised visitor at the door while a child is alone.", f)

    def blind_spot_entry(self) -> Scenario:
        f = self._frames([], self._when(self._hour(0.5, 4.5)), door=(0, 6), pir=True, sensors_always=True,
                         adult_home=False)
        return self._make("blind_spot_entry", "Entry outside camera view", "threat",
                          "Door contact and PIR fire at night but the camera sees no one.", f)

    def night_visitor(self) -> Scenario:
        f = self._frames([_Spec(None, "entry")], self._when(self._hour(0.5, 4.5)), door=(0, 4), adult_home=False)
        return self._make("night_visitor", "Unknown visitor at night", "threat",
                          "An unrecognised person at the door in the small hours.", f)

    # --------------------------------------------------------------- catalogue
    @property
    def catalogue(self) -> dict[str, Callable[[], Scenario]]:
        return {k: getattr(self, k) for k in BENIGN + THREAT}

    def random(self, label: Optional[str] = None) -> Scenario:
        if label is None:
            label = "threat" if self.rng.random() < 0.45 else "benign"
        pool = THREAT if label == "threat" else BENIGN
        return getattr(self, pool[int(self.rng.integers(len(pool)))])()


BENIGN = ["owner_arrival", "family_evening", "worker_scheduled", "delivery_visitor", "late_resident",
          "child_with_parent", "child_alone_quiet", "phantom_detection", "pet_motion"]
THREAT = ["stranger_bedroom", "photo_spoof", "tailgating", "worker_after_hours", "worker_restricted",
          "child_alone_worker", "child_alone_stranger", "blind_spot_entry", "night_visitor"]
