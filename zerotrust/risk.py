"""Project: AI-Based Zero-Trust Smart Home Security And Child Safety System
Authors: Humera Tahzeeb (GE-232023385), Megha Saxena (GE-232023450), Yatharth Verma (GE-232023727)
Supervisor: Dr. Neha Tripathi, Graphic Era Deemed to be University, Dehradun
Academic Year: 2025-2026
Module: Multi-Factor Zero-Trust Risk Fusion Engine

Cumulative, explainable risk scoring (the fusion engine).
Every signal contributes weighted points toward one running score; several
small anomalies can therefore add up to a serious alert even when no single
factor would have triggered one alone. Each point is attributed to a named
signal so a guardian can always see *why* a score was produced.
"""
from __future__ import annotations

import time as _time
from typing import Optional

from .baseline import VISITOR_KEY, BehaviorBaseline
from .config import Config
from .context import ContextModel, HouseholdState, detect_tailgating
from .models import (GUARDIAN_ROLES, HIGH, LOW, MEDIUM, TRUST_COMPONENTS, Assessment,
                     PersonObservation, SceneObservation, Signal)

TITLES = {
    "unknown_person": "Unrecognised Person",
    "spoof_suspected": "Spoofing Suspected (Liveness Failed)",
    "tailgating": "Tailgating",
    "outside_schedule": "Outside Approved Hours",
    "restricted_zone": "Unapproved Zone Entry",
    "low_confidence_identity": "Weak Identity Match",
    "behavior_anomaly": "Unusual Behaviour",
    "multi_unknown": "Multiple Unknown People",
    "unseen_motion_both": "Door + Motion With Nobody Visible",
    "unseen_motion_single": "Unexplained Sensor Activity",
    "quiet_hours_visitor": "Visitor During Quiet Hours",
    "child_alone_visitor": "Child Alone With Visitor",
    "child_alone_amplifier": "Child-Alone Status",
    "sensor_confirmed": "Sensor-Confirmed",
    "sensor_unconfirmed": "Unconfirmed By Sensors",
    "acoustic_anomaly": "Acoustic Anomaly (Scream/Glass Break in Blind Spot)",
}

ACTIONS = {
    LOW: "Log only - no notification",
    MEDIUM: "Notify guardian for review (no siren)",
    HIGH: "Sound alarm, SMS guardian, capture evidence",
}


class RiskEngine:
    def __init__(self, cfg: Config, baseline: Optional[BehaviorBaseline] = None,
                 ctx: Optional[ContextModel] = None, household: Optional[HouseholdState] = None):
        self.cfg = cfg
        self.risk = cfg["risk"]
        self.baseline = baseline or BehaviorBaseline()
        self.ctx = ctx or ContextModel(cfg)
        self.household = household or HouseholdState(cfg["timing"]["presence_timeout_s"])
        self._learned: set = set()
        self._consecutive_high_frames: int = 0

    # ------------------------------------------------------------------ main
    def assess(self, obs: SceneObservation) -> Assessment:
        t0 = _time.perf_counter()
        r, w = self.risk, self.risk["weights"]
        ts = obs.timestamp
        signals: list[Signal] = []
        loss: dict[int, dict[str, float]] = {}
        stable = [p for p in obs.persons if p.stable]

        children_alone = self.household.update(obs) if r["use_context"] else False

        for p in stable:
            pl = loss.setdefault(p.track_id, {c: 0.0 for c in TRUST_COMPONENTS})
            who = p.identity or f"person #{p.track_id}"
            zone = self.ctx.zone_label(p.zone)
            spoof = r["use_liveness"] and p.liveness < r["liveness_threshold"]

            if spoof:
                signals.append(Signal("spoof_suspected", "liveness", w["spoof_suspected"],
                                      f"{who}: liveness {p.liveness:.2f} below {r['liveness_threshold']} "
                                      "(photo/screen/mask replay suspected)", (p.track_id,)))
                pl["liveness"] = 1.0
                pl["identity"] = 1.0  # a spoofed identity is not a verified identity

            if not p.known:
                factor = self.ctx.unknown_factor(p.zone) if r["use_context"] else 1.0
                signals.append(Signal("unknown_person", "identity", w["unknown_person"] * factor,
                                      f"Unrecognised person in {zone}", (p.track_id,)))
                pl["identity"] = 1.0
                if r["use_context"] and self.ctx.is_restricted(p.zone):
                    signals.append(Signal("restricted_zone", "location", w["restricted_zone"],
                                          f"Unrecognised person inside restricted zone: {zone}", (p.track_id,)))
                    pl["location"] = 1.0
                if r["use_context"] and self.ctx.is_quiet_hours(ts):
                    signals.append(Signal("quiet_hours_visitor", "schedule", w["quiet_hours_visitor"],
                                          f"Unrecognised person during quiet hours ({ts:%H:%M})", (p.track_id,)))
                    pl["schedule"] = 0.6
                if r["use_behavior"]:
                    self._behavior(signals, pl, p, VISITOR_KEY, ts)
                continue

            if p.match_score < r["low_match_score"]:
                signals.append(Signal("low_confidence_identity", "identity", w["low_confidence_identity"],
                                      f"{who}: weak face match ({p.match_score:.2f})", (p.track_id,)))
                pl["identity"] = max(pl["identity"], 0.4)

            if r["use_context"]:
                within = self.ctx.within_schedule(p.identity, ts)
                if within is False:
                    signals.append(Signal("outside_schedule", "schedule", w["outside_schedule"],
                                          f"{who} seen at {ts:%a %H:%M}, outside approved hours", (p.track_id,)))
                    pl["schedule"] = 1.0
                if not self.ctx.zone_allowed(p.identity, p.zone):
                    signals.append(Signal("restricted_zone", "location", w["restricted_zone"],
                                          f"{who} entered {zone}, which is not approved for this profile", (p.track_id,)))
                    pl["location"] = 1.0
            if r["use_behavior"]:
                self._behavior(signals, pl, p, p.identity, ts)

        # ----- scene level: tailgating / multiple strangers
        if r["use_tailgating"]:
            for verified, follower in detect_tailgating(obs, self.ctx, self.cfg["timing"]["tailgate_window_s"]):
                signals.append(Signal("tailgating", "tailgating", w["tailgating"],
                                      f"{follower.identity or 'Unrecognised person'} entered alongside verified "
                                      f"{verified.identity}", (verified.track_id, follower.track_id)))
        unknown = [p for p in stable if not p.known]
        if len(unknown) >= 2:
            signals.append(Signal("multi_unknown", "identity", w["multi_unknown"],
                                  f"{len(unknown)} unrecognised people in view", tuple(p.track_id for p in unknown)))

        # ----- child-alone protocol
        if r["use_context"] and children_alone:
            visitors = [p for p in stable if p.role not in GUARDIAN_ROLES and not p.is_child]
            if visitors:
                names = ", ".join(sorted({p.identity or "an unrecognised person" for p in visitors}))
                signals.append(Signal("child_alone_visitor", "context", w["child_alone_visitor"],
                                      f"Child is home without a guardian while {names} is present"))
            base = sum(s.points for s in signals if s.points > 0 and s.name != "child_alone_visitor")
            if base > 0:
                extra = base * (r["child_alone_multiplier"] - 1.0)
                signals.append(Signal("child_alone_amplifier", "context", extra,
                                      f"Child-Alone Protocol raises all risk x{r['child_alone_multiplier']}"))

        # ----- sensor fusion
        if r["use_sensors"] and obs.sensors.online:
            self._fuse_sensors(signals, obs, children_alone)

        score = max(0.0, min(100.0, sum(s.points for s in signals)))
        th = r["thresholds"]
        # Temporal anomaly debouncing (Limitation #3 Fix: Prevents 1-frame spikes like pillow fights from ringing sirens)
        debounce = r.get("temporal_debounce_frames", 1)
        if score >= th["high"]:
            self._consecutive_high_frames += 1
            level = HIGH if self._consecutive_high_frames >= debounce else MEDIUM
        else:
            self._consecutive_high_frames = 0
            level = MEDIUM if score >= th["medium"] else LOW

        trust = self._trust(loss)
        latency = (_time.perf_counter() - t0) * 1000.0
        return Assessment(
            timestamp=ts, score=score, level=level, signals=signals, trust=trust,
            persons=self._person_summaries(obs, loss), children_alone=children_alone,
            summary=self._summary(signals), action=ACTIONS[level], latency_ms=latency,
        )

    # --------------------------------------------------------------- helpers
    def _behavior(self, signals, pl, p: PersonObservation, key: str, ts) -> None:
        arrival = p.first_seen or ts
        mx = self.risk["weights"]["behavior_anomaly"]
        pts, reason = self.baseline.deviation_points(key, arrival, mx)
        if pts > 0:
            # Limitation #3: Resident Activity Grace - Benign domestic activities by verified family shouldn't trigger high alerts
            if p.known and p.role in GUARDIAN_ROLES and self.risk.get("resident_activity_grace", True):
                pts = pts * 0.4
            signals.append(Signal("behavior_anomaly", "behavior", pts, reason, (p.track_id,)))
            pl["behavior"] = max(pl["behavior"], min(1.0, pts / mx))

    def _fuse_sensors(self, signals: list[Signal], obs: SceneObservation, children_alone: bool) -> None:
        r, w = self.risk, self.risk["weights"]
        s = obs.sensors
        corroborated = s.door_open or s.pir_motion
        visible = bool(obs.persons)  # includes tracks whose identity is still settling
        vision_pts = sum(x.points for x in signals if x.points > 0)

        # Limitation #6: Acoustic Anomaly Fusion in Visual Blind Spots (Screams, Glass Breaks, Crashes)
        if s.acoustic_anomaly or obs.acoustic_event:
            pts = w.get("acoustic_anomaly", 35)
            ev_label = obs.acoustic_event or "Loud acoustic impact/distress"
            if not visible:
                pts += 10  # higher risk if sound comes from an unmonitored blind spot
            signals.append(Signal("acoustic_anomaly", "sensor", pts,
                                  f"{ev_label} in zone '{obs.camera_zone}' (auditory trigger)"))

        if visible:
            if vision_pts > 0 and corroborated:
                signals.append(Signal("sensor_confirmed", "sensor", w["sensor_confirmed"],
                                      "Camera finding confirmed by door/PIR sensor"))
            elif vision_pts > 0:
                cut = vision_pts * (1.0 - r["uncorroborated_factor"])
                signals.append(Signal("sensor_unconfirmed", "sensor", -cut,
                                      "Camera-only detection: no door/PIR confirmation, confidence reduced"))
        elif corroborated:
            both = s.door_open and s.pir_motion
            pts = w["unseen_motion_both"] if both else w["unseen_motion_single"]
            if self.ctx.is_quiet_hours(obs.timestamp):
                pts += 10
            if children_alone and r["use_context"]:
                pts *= r["child_alone_multiplier"]
            what = "Door contact + PIR" if both else ("Door contact" if s.door_open else "PIR motion")
            signals.append(Signal("unseen_motion_both" if both else "unseen_motion_single", "sensor", pts,
                                  f"{what} active but no person visible to the camera"))

    def _trust(self, loss: dict[int, dict[str, float]]) -> dict:
        tw = self.risk["trust_weights"]
        comps = {}
        for c in TRUST_COMPONENTS:
            worst = max((pl[c] for pl in loss.values()), default=0.0)
            comps[c] = round((1.0 - worst) * 100.0, 1)
        overall = sum(tw[c] * comps[c] for c in TRUST_COMPONENTS) / sum(tw.values())
        return {**comps, "overall": round(overall, 1), "has_subject": bool(loss)}

    def _person_summaries(self, obs: SceneObservation, loss) -> list[dict]:
        tw = self.risk["trust_weights"]
        out = []
        for p in obs.persons:
            d = p.to_dict()
            d["zone_label"] = self.ctx.zone_label(p.zone)
            pl = loss.get(p.track_id)
            if pl:
                d["trust"] = round(100 * sum(tw[c] * (1 - pl[c]) for c in TRUST_COMPONENTS) / sum(tw.values()), 1)
            else:
                d["trust"] = None
            out.append(d)
        return out

    @staticmethod
    def _summary(signals: list[Signal]) -> str:
        pos = sorted((s for s in signals if s.points > 0), key=lambda s: -s.points)
        if not pos:
            return "Routine activity"
        seen, parts = set(), []
        for s in pos:
            title = TITLES.get(s.name, s.name)
            if title not in seen:
                seen.add(title)
                parts.append(title)
        return " + ".join(parts[:3])

    # -------------------------------------------------------------- learning
    def learn(self, obs: SceneObservation, assessment: Assessment) -> None:
        """Fold low-risk arrivals into the baseline so routines adapt over time."""
        if assessment.level != LOW or not self.risk["use_behavior"]:
            return
        for p in obs.persons:
            if not p.stable:
                continue
            key = p.identity or VISITOR_KEY
            token = (p.track_id, key, (p.first_seen or obs.timestamp).isoformat())
            if token in self._learned:
                continue
            self._learned.add(token)
            self.baseline.observe(key, p.first_seen or obs.timestamp)
