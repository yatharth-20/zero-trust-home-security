"""Configuration for the Zero-Trust Smart Home Security system.

All tunable policy lives here (zones, household profiles, risk weights,
alert policy).  A JSON file can override any key, e.g. ``config/settings.json``.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


class Config(dict):
    """Dict with attribute access and recursive wrapping (``cfg.risk.weights``)."""

    def __getattr__(self, item: str) -> Any:
        try:
            value = self[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc
        return Config(value) if isinstance(value, dict) and not isinstance(value, Config) else value

    def to_dict(self) -> dict:
        return json.loads(json.dumps(self))


DEFAULTS: dict = {
    "paths": {"data_dir": "data"},
    # ------------------------------------------------------------------ zones
    "zones": {
        "entry": {"label": "Entry / Porch", "access": "open", "entry_point": True, "unknown_factor": 0.55},
        "living_room": {"label": "Living Room", "access": "open", "unknown_factor": 1.0},
        "kitchen": {"label": "Kitchen", "access": "open", "unknown_factor": 1.0},
        "study": {"label": "Study", "access": "restricted", "unknown_factor": 1.0},
        "bedroom": {"label": "Bedroom", "access": "restricted", "unknown_factor": 1.0},
    },
    # --------------------------------------------------------------- household
    # role: owner | family | child | worker | guest
    # allowed_zones: list of zone ids or ["*"]; schedule: approved visit window
    "profiles": {
        "Homeowner": {"role": "owner", "allowed_zones": ["*"], "schedule": None},
        "Spouse": {"role": "family", "allowed_zones": ["*"], "schedule": None},
        "Child": {"role": "child", "allowed_zones": ["*"], "schedule": None},
        "Worker": {
            "role": "worker",
            "allowed_zones": ["entry", "living_room", "kitchen"],
            "schedule": {"days": [0, 1, 2, 3, 4, 5], "start": "09:00", "end": "17:00"},
        },
    },
    "quiet_hours": {"start": "22:00", "end": "06:00"},
    # -------------------------------------------------------------------- risk
    "risk": {
        "weights": {
            "unknown_person": 40,        # scaled by zone ``unknown_factor``
            "spoof_suspected": 45,       # liveness failure on a (claimed) identity
            "tailgating": 35,
            "outside_schedule": 28,
            "restricted_zone": 35,
            "low_confidence_identity": 10,
            "behavior_anomaly": 22,      # maximum, scaled by deviation
            "multi_unknown": 10,
            "unseen_motion_both": 35,    # door + PIR active but nobody visible
            "unseen_motion_single": 20,
            "quiet_hours_visitor": 12,   # non-household person during quiet hours
            "child_alone_visitor": 30,   # non-guardian adult present, child alone
            "sensor_confirmed": 5,
            "acoustic_anomaly": 35,      # glass break / distress sound in blind spot
        },
        "child_alone_multiplier": 1.4,
        "uncorroborated_factor": 0.5,
        "thresholds": {"medium": 30, "high": 60},
        "liveness_threshold": 0.5,
        "low_match_score": 0.45,
        "match_threshold": 0.363,        # SFace cosine threshold
        "trust_weights": {"identity": 0.30, "liveness": 0.20, "schedule": 0.15, "location": 0.20, "behavior": 0.15},
        "temporal_debounce_frames": 3,   # consecutive anomaly frames before escalating to high alert
        "resident_activity_grace": True, # suppress single-frame false alarms for verified residents
        # Feature switches (used by the evaluation ablations)
        "use_sensors": True,
        "use_behavior": True,
        "use_context": True,
        "use_liveness": True,
        "use_tailgating": True,
    },
    "baseline": {"alpha": 0.5, "min_observations": 8, "surprise_floor": 0.9, "surprise_span": 0.5},
    # ------------------------------------------------------------------ timing
    "timing": {
        "tailgate_window_s": 10,
        "cooldown_s": 120,
        "incident_quiet_s": 60,
        "presence_timeout_s": 900,
        "confirm_frames": 3,
        "alarm_duration_s": 20,
    },
    # ------------------------------------------------------------------ alerts
    "alerts": {
        "dry_run": True,              # SMS are written to data/sms_outbox.log instead of being sent
        "sms_on_medium": False,
        "local_beep": True,
        "sms_to": "",                 # or env ZT_SMS_TO
        "ntfy_topic": "",             # optional push channel (https://ntfy.sh/<topic>)
        "esp32_port": "",             # e.g. "COM5"; empty = simulated link
        "esp32_baud": 115200,
        "offline_queue": True,        # store unsent alerts locally when Wi-Fi/Twilio is down
        "offline_queue_file": "offline_alerts.json",
        "local_lan_broadcast": True,  # broadcast alert on local network without cloud dependency
    },
    # ---------------------------------------------------------------- evidence
    "evidence": {"pre_roll_s": 4, "post_roll_s": 6, "fps": 10},
    # ------------------------------------------------------------------ vision
    "vision": {
        "camera_index": 0,
        "camera_zone": "entry",
        "camera_sources": [           # supports multiple webcams, RTSP IP cams, or video streams
            {"id": 0, "zone": "entry", "name": "Main Entrance"},
        ],
        "frame_width": 960,
        "frame_height": 540,
        "detector_score": 0.8,
        "process_every_n": 2,
        "liveness_window": 15,
        "adaptive_clahe": True,       # auto-enhance poor/dark lighting using CLAHE
        "low_light_threshold": 65,    # threshold to trigger adaptive contrast enhancement
        "detection_scale": 0.5,       # downscale frame for detection to reduce Core i3 CPU load
    },
    # ------------------------------------------------------------------- audio
    "audio": {
        "enabled": True,              # acoustic anomaly monitoring (glass break, scream, crash)
        "threshold_db": 75.0,
        "listen_mic": False,          # set True to capture live microphone stream
    },
    "dashboard": {"host": "127.0.0.1", "port": 8765},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for key, val in over.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], val)
        else:
            out[key] = val
    return out


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> Config:
    cfg = copy.deepcopy(DEFAULTS)
    candidate = Path(path) if path else ROOT / "config" / "settings.json"
    if candidate.exists():
        cfg = _merge(cfg, json.loads(candidate.read_text(encoding="utf-8")))
    if overrides:
        cfg = _merge(cfg, overrides)
    return Config(cfg)


def data_dir(cfg: Config) -> Path:
    p = Path(cfg["paths"]["data_dir"])
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p
