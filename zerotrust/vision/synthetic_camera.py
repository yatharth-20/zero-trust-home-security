"""High-fidelity synthetic camera frame generator for Zero-Trust Home Security.

Renders realistic surveillance camera frames showing detected persons, face features,
facial landmark points, and biometric tracking HUD overlays.
Used in demo/simulation mode and as a visual fallback when physical webcam is idle.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

try:
    import cv2
    import numpy as np
except ImportError:
    cv2, np = None, None

from ..models import Assessment, PersonObservation, SceneObservation

# Colors (BGR)
COLOR_VERIFIED = (80, 225, 95)    # Green
COLOR_WORKER = (40, 190, 245)      # Amber
COLOR_UNKNOWN = (60, 60, 240)      # Red
COLOR_SPOOF = (210, 50, 230)       # Magenta/Purple
COLOR_WHITE = (245, 245, 245)
COLOR_DARK = (18, 14, 12)


def _draw_tech_box(img, x1, y1, x2, y2, color, thickness=2, corner_len=16):
    """Draw a bounding box with high-tech corner brackets."""
    cv2.rectangle(img, (x1, y1), (x2, y2), color, thickness)
    # Four corner brackets with extra thickness
    t = thickness + 2
    # Top-left
    cv2.line(img, (x1, y1), (x1 + corner_len, y1), color, t)
    cv2.line(img, (x1, y1), (x1, y1 + corner_len), color, t)
    # Top-right
    cv2.line(img, (x2, y1), (x2 - corner_len, y1), color, t)
    cv2.line(img, (x2, y1), (x2, y1 + corner_len), color, t)
    # Bottom-left
    cv2.line(img, (x1, y2), (x1 + corner_len, y2), color, t)
    cv2.line(img, (x1, y2), (x1, y2 - corner_len), color, t)
    # Bottom-right
    cv2.line(img, (x2, y2), (x2 - corner_len, y2), color, t)
    cv2.line(img, (x2, y2), (x2, y2 - corner_len), color, t)


def _draw_person(img, p: PersonObservation, cx: int, cy: int, scale: float = 1.0):
    """Draw a human figure with detailed facial features, eyes, hair, and AI landmarks."""
    ident = (p.identity or "").lower()
    is_child = p.is_child or "child" in ident
    is_worker = p.role == "worker"
    is_known = p.known and p.role in ("owner", "family", "child")
    is_spoof = p.liveness < 0.5

    # Color palette based on identity
    if is_child:
        skin = (195, 215, 245)
        hair = (40, 65, 110)
        shirt = (210, 160, 60)
        head_w, head_h = int(45 * scale), int(60 * scale)
    elif is_known:
        skin = (180, 205, 235)
        hair = (30, 40, 50)
        shirt = (180, 110, 70) if "spouse" in ident else (80, 130, 180)
        head_w, head_h = int(52 * scale), int(72 * scale)
    elif is_worker:
        skin = (170, 195, 225)
        hair = (25, 30, 35)
        shirt = (40, 150, 230)  # orange/yellow vest
        head_w, head_h = int(52 * scale), int(72 * scale)
    else:  # Unknown stranger
        skin = (165, 190, 220)
        hair = (20, 20, 25)
        shirt = (45, 45, 55)    # dark jacket/hoodie
        head_w, head_h = int(54 * scale), int(74 * scale)

    # 1. Shoulders / Torso
    torso_w = int(head_w * 2.2)
    torso_h = int(head_h * 1.8)
    cv2.ellipse(img, (cx, cy + int(head_h * 1.6)), (torso_w, torso_h), 0, 180, 360, shirt, -1)
    # Neck
    neck_w = int(head_w * 0.45)
    cv2.rectangle(img, (cx - neck_w, cy + int(head_h * 0.6)), (cx + neck_w, cy + int(head_h * 1.1)), (skin[0]-15, skin[1]-15, skin[2]-15), -1)

    # 2. Face Oval
    cv2.ellipse(img, (cx, cy), (head_w, head_h), 0, 0, 360, skin, -1)

    # 3. Hair
    if "child" in ident:
        # Round hair / bangs
        cv2.ellipse(img, (cx, cy - int(head_h * 0.45)), (head_w + 3, int(head_h * 0.65)), 0, 180, 360, hair, -1)
    elif "spouse" in ident:
        # Longer hair
        cv2.ellipse(img, (cx, cy - int(head_h * 0.3)), (head_w + 6, int(head_h * 0.8)), 0, 160, 380, hair, -1)
        cv2.ellipse(img, (cx - head_w - 2, cy + 20), (12, 40), 0, 0, 360, hair, -1)
        cv2.ellipse(img, (cx + head_w + 2, cy + 20), (12, 40), 0, 0, 360, hair, -1)
    elif not is_known:
        # Hoodie / Cap shadow for intruder
        cv2.ellipse(img, (cx, cy - int(head_h * 0.3)), (head_w + 6, int(head_h * 0.8)), 0, 180, 360, hair, -1)
        cv2.ellipse(img, (cx, cy - int(head_h * 0.5)), (head_w + 8, int(head_h * 0.4)), 0, 0, 360, (30, 30, 35), -1)
    else:
        # Standard neat hairstyle
        cv2.ellipse(img, (cx, cy - int(head_h * 0.45)), (head_w + 4, int(head_h * 0.65)), 0, 180, 360, hair, -1)

    # 4. Eyes & Eyebrows
    eye_y = cy - int(head_h * 0.1)
    eye_dx = int(head_w * 0.42)
    eye_rad = max(3, int(5 * scale))

    # Eyebrows
    cv2.line(img, (cx - eye_dx - 6, eye_y - 8), (cx - eye_dx + 8, eye_y - 9), (30, 25, 20), max(1, int(2 * scale)))
    cv2.line(img, (cx + eye_dx - 8, eye_y - 9), (cx + eye_dx + 6, eye_y - 8), (30, 25, 20), max(1, int(2 * scale)))

    # White sclera + dark pupil
    for ex in (cx - eye_dx, cx + eye_dx):
        cv2.circle(img, (ex, eye_y), eye_rad + 2, (250, 250, 250), -1)
        cv2.circle(img, (ex, eye_y), eye_rad, (40, 30, 25), -1)
        cv2.circle(img, (ex - 1, eye_y - 1), max(1, eye_rad - 2), (15, 10, 5), -1)
        cv2.circle(img, (ex + 1, eye_y - 1), 1, (255, 255, 255), -1)  # light catch

    # 5. Nose
    nose_y = cy + int(head_h * 0.15)
    cv2.line(img, (cx, eye_y + 4), (cx - 2, nose_y), (skin[0]-35, skin[1]-35, skin[2]-35), 1)
    cv2.line(img, (cx - 2, nose_y), (cx + 3, nose_y), (skin[0]-40, skin[1]-40, skin[2]-40), 2)

    # 6. Mouth / Expression
    mouth_y = cy + int(head_h * 0.45)
    mouth_w = int(head_w * 0.35)
    if is_known:
        # Friendly curve
        cv2.ellipse(img, (cx, mouth_y - 2), (mouth_w, max(2, int(6 * scale))), 0, 0, 180, (50, 60, 160), 2)
    else:
        # Straight / tense expression
        cv2.line(img, (cx - mouth_w, mouth_y), (cx + mouth_w, mouth_y), (50, 50, 140), 2)

    # 7. Spoof indicator (visual photo/screen frame overlay if spoof)
    if is_spoof:
        # Draw mobile phone / photo bezel held in front
        bx1, by1 = cx - head_w - 12, cy - head_h - 12
        bx2, by2 = cx + head_w + 12, cy + head_h + 12
        cv2.rectangle(img, (bx1, by1), (bx2, by2), COLOR_SPOOF, 2)
        cv2.putText(img, "[2D PHOTO / SCREEN REPLAY DETECTED]", (cx - 110, by1 - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, COLOR_SPOOF, 1)

    # 8. Biometric Landmarks (5 points from YuNet)
    lm_color = (255, 220, 0)  # Cyan/Yellow
    landmarks = [
        (cx - eye_dx, eye_y),            # Left eye
        (cx + eye_dx, eye_y),            # Right eye
        (cx, nose_y),                    # Nose
        (cx - int(mouth_w * 0.8), mouth_y), # Left mouth
        (cx + int(mouth_w * 0.8), mouth_y), # Right mouth
    ]
    for lx, ly in landmarks:
        cv2.circle(img, (lx, ly), 3, lm_color, -1)
        cv2.circle(img, (lx, ly), 5, (0, 0, 0), 1)

    # 9. Detection Bounding Box & HUD
    box_pad_x = head_w + int(18 * scale)
    box_pad_top = head_h + int(14 * scale)
    box_pad_bot = int(head_h * 1.8)

    x1, y1 = cx - box_pad_x, cy - box_pad_top
    x2, y2 = cx + box_pad_x, cy + box_pad_bot

    if is_spoof:
        box_col = COLOR_SPOOF
    elif is_known:
        box_col = COLOR_VERIFIED
    elif is_worker:
        box_col = COLOR_WORKER
    else:
        box_col = COLOR_UNKNOWN

    _draw_tech_box(img, x1, y1, x2, y2, box_col, thickness=2)

    # Header badge
    name_str = p.identity.upper() if p.identity else f"UNKNOWN #{p.track_id}"
    match_str = f"{p.match_score:.0%}" if p.known else "NO MATCH"
    status_str = f"{name_str} ({match_str})"
    if is_spoof:
        status_str += " [SPOOF!]"

    badge_h = 24
    cv2.rectangle(img, (x1, y1 - badge_h), (x2, y1), box_col, -1)
    cv2.putText(img, status_str, (x1 + 6, y1 - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.44, (10, 10, 10), 2)

    # Sub-badge with liveness & age
    sub_str = f"Live: {p.liveness:.2f} | {p.role.upper()}"
    cv2.rectangle(img, (x1, y2), (x2, y2 + 18), (20, 20, 20), -1)
    cv2.rectangle(img, (x1, y2), (x2, y2 + 18), box_col, 1)
    cv2.putText(img, sub_str, (x1 + 6, y2 + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.38, box_col, 1)


def render_scene_frame(obs: SceneObservation, assessment: Optional[Assessment] = None, width: int = 800, height: int = 450) -> np.ndarray:
    """Generate a full-fidelity surveillance camera frame with detected human faces and biometric HUD."""
    if cv2 is None or np is None:
        return b""

    # 1. Base Room Background (Gradient Interior Room with doorway)
    img = np.zeros((height, width, 3), dtype=np.uint8)
    # Wall gradient
    for y in range(height):
        ratio = y / height
        val = int(22 + 28 * ratio)
        img[y, :] = (val, val + 2, val + 5)

    # Floor plane
    floor_y = int(height * 0.76)
    for y in range(floor_y, height):
        r = (y - floor_y) / (height - floor_y)
        v = int(40 - 15 * r)
        img[y, :] = (v, v - 2, v - 5)
    cv2.line(img, (0, floor_y), (width, floor_y), (60, 62, 70), 1)

    # Interior doorway frame in background
    door_w, door_h = 170, 280
    dx1, dy1 = int(width * 0.5 - door_w // 2), floor_y - door_h
    dx2, dy2 = dx1 + door_w, floor_y
    cv2.rectangle(img, (dx1, dy1), (dx2, dy2), (15, 12, 10), -1)
    cv2.rectangle(img, (dx1, dy1), (dx2, dy2), (50, 50, 58), 4)
    # Door panel (slightly ajar or closed depending on sensor)
    door_open = obs.sensors.door_open if obs.sensors else False
    if door_open:
        cv2.line(img, (dx1 + 4, dy1 + 4), (dx1 + 40, dy2 - 4), (75, 75, 85), 5)
        cv2.putText(img, "DOOR: OPEN", (dx1 + 15, dy1 + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)
    else:
        cv2.rectangle(img, (dx1 + 4, dy1 + 4), (dx2 - 4, dy2 - 4), (32, 28, 25), -1)
        cv2.circle(img, (dx2 - 20, dy1 + door_h // 2), 4, (180, 180, 190), -1)  # knob

    # 2. Render Persons / Faces
    persons = obs.persons or []
    n = len(persons)
    if n == 1:
        _draw_person(img, persons[0], cx=int(width * 0.5), cy=int(height * 0.44), scale=1.0)
    elif n == 2:
        _draw_person(img, persons[0], cx=int(width * 0.35), cy=int(height * 0.44), scale=0.95)
        _draw_person(img, persons[1], cx=int(width * 0.65), cy=int(height * 0.44), scale=0.95)
    elif n >= 3:
        for idx, p in enumerate(persons[:3]):
            cx = int(width * (0.24 + 0.26 * idx))
            _draw_person(img, p, cx=cx, cy=int(height * 0.45), scale=0.85)
    else:
        # Empty room / blind spot surveillance state
        cv2.putText(img, "[ CAMERA FEED: NO PERSONS VISIBLE ]", (int(width * 0.26), int(height * 0.45)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (120, 130, 140), 2)
        if obs.sensors and (obs.sensors.door_open or obs.sensors.pir_motion):
            cv2.putText(img, "WARNING: SENSOR ACTIVITY OUTSIDE CAMERA VIEW", (int(width * 0.21), int(height * 0.52)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (50, 50, 240), 2)

    # 3. Security Camera OSD (On-Screen Display) Overlay
    # Top banner
    cv2.rectangle(img, (0, 0), (width, 36), (8, 6, 4), -1)
    # Red recording dot
    cv2.circle(img, (18, 18), 5, (0, 0, 240), -1)
    cv2.putText(img, "LIVE", (30, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (240, 240, 240), 1)

    # Zone & camera name
    zone_label = (obs.camera_zone or "entry").replace("_", " ").upper()
    cv2.putText(img, f"CAM-01 [{zone_label}]", (90, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (110, 231, 249), 1)

    # Time
    ts_str = obs.timestamp.strftime("%Y-%m-%d  %H:%M:%S")
    cv2.putText(img, ts_str, (width - 240, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (200, 200, 200), 1)

    # Bottom status bar
    cv2.rectangle(img, (0, height - 32), (width, height), (8, 6, 4), -1)
    # AI Engine badge
    cv2.putText(img, "VISION: YuNet Detector + SFace Biometrics (ONNX)", (16, height - 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (140, 150, 170), 1)

    # Assessment indicator on frame
    if assessment is not None:
        score_val = assessment.score
        lvl = assessment.level
        lvl_col = COLOR_VERIFIED if lvl == "LOW" else COLOR_WORKER if lvl == "MEDIUM" else COLOR_UNKNOWN
        cv2.putText(img, f"RISK: {lvl} ({score_val:.0f}/100)", (width - 210, height - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, lvl_col, 2)

    return img
