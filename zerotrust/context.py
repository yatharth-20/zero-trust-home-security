"""Project: AI-Based Zero-Trust Smart Home Security And Child Safety System
Authors: Humera Tahzeeb (GE-232023385), Megha Saxena (GE-232023450), Yatharth Verma (GE-232023727)
Supervisor: Dr. Neha Tripathi, Graphic Era Deemed to be University, Dehradun
Academic Year: 2025-2026
Module: Contextual Reasoning Engine (Zones, Schedules, Tailgating)
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional

from .config import Config
from .models import GUARDIAN_ROLES, PersonObservation, SceneObservation


def parse_hhmm(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def in_window(now: time, start: time, end: time) -> bool:
    """Inclusive window check that also handles windows crossing midnight."""
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end


class ContextModel:
    """Answers 'is this allowed here / now?' for a given person."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.zones = cfg["zones"]
        self.profiles = cfg["profiles"]
        qh = cfg["quiet_hours"]
        self._quiet = (parse_hhmm(qh["start"]), parse_hhmm(qh["end"]))

    # ---- time ---------------------------------------------------------
    def is_quiet_hours(self, ts: datetime) -> bool:
        return in_window(ts.time(), *self._quiet)

    def within_schedule(self, identity: Optional[str], ts: datetime) -> Optional[bool]:
        """None => profile has no schedule constraint."""
        profile = self.profiles.get(identity or "")
        if not profile or not profile.get("schedule"):
            return None
        sch = profile["schedule"]
        if ts.weekday() not in sch.get("days", range(7)):
            return False
        return in_window(ts.time(), parse_hhmm(sch["start"]), parse_hhmm(sch["end"]))

    # ---- location -----------------------------------------------------
    def zone_label(self, zone: str) -> str:
        return self.zones.get(zone, {}).get("label", zone)

    def is_restricted(self, zone: str) -> bool:
        return self.zones.get(zone, {}).get("access") == "restricted"

    def unknown_factor(self, zone: str) -> float:
        return float(self.zones.get(zone, {}).get("unknown_factor", 1.0))

    def is_entry_zone(self, zone: str) -> bool:
        return bool(self.zones.get(zone, {}).get("entry_point", False))

    def zone_allowed(self, identity: Optional[str], zone: str) -> bool:
        profile = self.profiles.get(identity or "")
        if not profile:
            return not self.is_restricted(zone)
        allowed = profile.get("allowed_zones", ["*"])
        return "*" in allowed or zone in allowed


class HouseholdState:
    """Tracks who is home so the Child-Alone Protocol can be evaluated."""

    def __init__(self, presence_timeout_s: float = 900):
        self.timeout = timedelta(seconds=presence_timeout_s)
        self.last_adult: Optional[datetime] = None
        self.last_child: Optional[datetime] = None
        self.manual_adults_away: Optional[bool] = None  # guardian toggle from the dashboard

    def update(self, obs: SceneObservation) -> bool:
        """Update presence and return True when a child is home without a guardian."""
        for p in obs.persons:
            if p.role in GUARDIAN_ROLES and p.known:
                self.last_adult = obs.timestamp
            if p.is_child:
                self.last_child = obs.timestamp
        return self.children_alone(obs)

    def children_alone(self, obs: SceneObservation) -> bool:
        now = obs.timestamp
        if obs.child_home_hint is not None:
            child_home = obs.child_home_hint
        else:
            child_home = self.last_child is not None and now - self.last_child <= self.timeout
        if obs.adult_home_hint is not None:
            adult_home = obs.adult_home_hint
        elif self.manual_adults_away is not None:
            adult_home = not self.manual_adults_away
        else:
            adult_home = self.last_adult is not None and now - self.last_adult <= self.timeout
        # A guardian visible right now always counts.
        if any(p.role in GUARDIAN_ROLES and p.known for p in obs.persons):
            adult_home = True
        return bool(child_home and not adult_home)


def detect_tailgating(obs: SceneObservation, ctx: ContextModel, window_s: float) -> list[tuple[PersonObservation, PersonObservation]]:
    """Return (verified, follower) pairs: an unrecognised person entering with a cleared one."""
    pairs = []
    verified = [p for p in obs.persons if p.known and p.liveness >= 0.5 and p.stable and p.role != "child"]
    followers = [p for p in obs.persons if not p.known and p.stable]
    if not verified or not followers:
        return pairs
    entry_context = obs.sensors.door_open or any(ctx.is_entry_zone(p.zone) for p in verified + followers)
    if not entry_context:
        return pairs
    for v in verified:
        for f in followers:
            if v.first_seen and f.first_seen:
                if abs((f.first_seen - v.first_seen).total_seconds()) <= window_s:
                    pairs.append((v, f))
            else:
                pairs.append((v, f))
    return pairs
