"""Unit tests verifying mitigations for all 6 project limitations."""
from datetime import datetime
from pathlib import Path
import tempfile
import numpy as np
import pytest

from zerotrust.config import load_config
from zerotrust.vision.face_engine import enhance_low_light, FaceEngine
from zerotrust.alerts import OfflineAlertQueue, SMSNotifier, LocalBroadcast
from zerotrust.audio import AudioAnomalyDetector
from zerotrust.models import SceneObservation, PersonObservation, SensorState
from zerotrust.risk import RiskEngine


def test_limitation_1_multi_camera_config():
    """Limitation 1: Multi-camera configuration support."""
    cfg = load_config(overrides={
        "vision": {
            "camera_sources": [
                {"id": 0, "zone": "entry", "name": "Main Door"},
                {"id": "rtsp://192.168.1.100:554/stream", "zone": "backyard", "name": "Backyard IP Cam"}
            ]
        }
    })
    sources = cfg["vision"]["camera_sources"]
    assert len(sources) == 2
    assert sources[1]["id"].startswith("rtsp://")


def test_limitation_2_adaptive_clahe_low_light():
    """Limitation 2: Low-light enhancement via CLAHE in LAB space."""
    # Create dark dummy frame (mean pixel intensity ~25)
    dark_frame = np.full((100, 100, 3), 25, dtype=np.uint8)
    enhanced, mean_lum = enhance_low_light(dark_frame)
    assert mean_lum < 70.0
    assert enhanced.shape == dark_frame.shape
    # CLAHE should increase or maintain contrast
    assert np.mean(enhanced) >= np.mean(dark_frame)


def test_limitation_3_resident_grace_and_debouncing():
    """Limitation 3: Resident activity grace reduces false alarms for harmless domestic motions."""
    cfg = load_config()
    engine = RiskEngine(cfg)
    now = datetime(2026, 10, 14, 14, 0, 0)

    # Known homeowner inside living room
    homeowner = PersonObservation(
        track_id=1,
        identity="Homeowner",
        role="owner",
        match_score=0.92,
        zone="living_room",
        stable=True
    )
    obs = SceneObservation(timestamp=now, persons=[homeowner], camera_zone="living_room")
    assessment = engine.assess(obs)
    # Risk should remain LOW for normal household presence
    assert assessment.level == "LOW"
    assert assessment.score < 30.0


def test_limitation_4_offline_alert_queue():
    """Limitation 4: Offline persistent alert queue when Twilio/internet is disconnected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        qfile = Path(tmpdir) / "offline_alerts.json"
        queue = OfflineAlertQueue(qfile)
        assert queue.load() == []

        record = {"ts": "2026-10-14T10:00:00", "to": "+919876543210", "body": "Emergency Intruder Alert"}
        queue.enqueue(record)
        loaded = queue.load()
        assert len(loaded) == 1
        assert loaded[0]["body"] == "Emergency Intruder Alert"

        # Test local UDP broadcast fallback
        bc = LocalBroadcast(port=8766, enabled=True)
        # Should execute safely without throwing exceptions
        assert isinstance(bc.broadcast("Test local notification"), bool)


def test_limitation_5_multiscale_inference_i3_speedup():
    """Limitation 5: Frame downscaling factor for low-end Core i3 CPU."""
    cfg = load_config()
    scale = cfg["vision"]["detection_scale"]
    assert scale == 0.5  # 50% detection scale reduces computation drastically


def test_limitation_6_audio_anomaly_blind_spots():
    """Limitation 6: Audio anomaly detector bridges visual blind spots."""
    detector = AudioAnomalyDetector(threshold_db=75.0, listen_mic=False)
    # Initial state
    is_anom, desc, _ = detector.check()
    assert is_anom is False

    # Trigger acoustic distress (glass shatter or child scream)
    detector.trigger_anomaly(event_type="Shattered window glass", db_level=88.5, hold_s=2.0)
    is_anom, desc, db = detector.check()
    assert is_anom is True
    assert desc == "Shattered window glass"
    assert db == 88.5
