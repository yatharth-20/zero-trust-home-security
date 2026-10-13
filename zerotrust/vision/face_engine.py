"""Face detection + recognition (OpenCV YuNet detector + SFace embeddings).

Models (~37 MB) are downloaded once into ``models/``.  If they are unavailable
the engine degrades to Haar-cascade *detection only* - every face is then
treated as unrecognised, which is the safe (zero-trust) default.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Optional

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None

MODELS = {
    "face_detection_yunet_2023mar.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "face_recognition_sface_2021dec.onnx":
        "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def ensure_models(models_dir: Path, quiet: bool = False) -> bool:
    models_dir.mkdir(parents=True, exist_ok=True)
    ok = True
    for name, url in MODELS.items():
        path = models_dir / name
        if path.exists() and path.stat().st_size > 100_000:
            continue
        try:
            if not quiet:
                print(f"[models] downloading {name} ...")
            urllib.request.urlretrieve(url, path)
        except Exception as exc:  # pragma: no cover - network
            print(f"[models] could not download {name}: {exc}")
            ok = False
    return ok


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.ravel(), b.ravel()
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


class FaceGallery:
    """Enrolled face embeddings, one ``.npy`` file per person."""

    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.embeddings: dict[str, np.ndarray] = {}
        self.load()

    def load(self) -> None:
        self.embeddings = {p.stem: np.load(p) for p in sorted(self.dir.glob("*.npy"))}

    def add(self, name: str, embeddings: np.ndarray) -> None:
        arr = np.asarray(embeddings, dtype=np.float32).reshape(-1, 128)
        if name in self.embeddings:
            arr = np.vstack([self.embeddings[name], arr])
        np.save(self.dir / f"{name}.npy", arr)
        self.embeddings[name] = arr

    def match(self, emb: np.ndarray, threshold: float) -> tuple[Optional[str], float]:
        """Best identity by mean of the top-3 cosine similarities (robust to a single lucky sample)."""
        best_name, best = None, -1.0
        for name, arr in self.embeddings.items():
            sims = sorted((cosine(emb, e) for e in arr), reverse=True)[:3]
            score = float(np.mean(sims))
            if score > best:
                best_name, best = name, score
        if best_name is not None and best >= threshold:
            return best_name, best
        return None, max(best, 0.0)


def enhance_low_light(frame: np.ndarray, clip_limit: float = 2.5) -> tuple[np.ndarray, float]:
    """Dynamically balance poor/harsh lighting using LAB CLAHE (Limitation #2 Fix).
    Returns enhanced frame and average luminance (0-255)."""
    if frame is None or frame.size == 0:
        return frame, 100.0
    # Fast luminance estimation via grayscale mean
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_lum = float(np.mean(gray))
    if mean_lum < 70.0:  # low light or night condition
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
        lab[:, :, 0] = clahe.apply(lab[:, :, 0])
        return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR), mean_lum
    return frame, mean_lum


class FaceEngine:
    def __init__(self, models_dir: Path, score_threshold: float = 0.8, download: bool = True,
                 adaptive_clahe: bool = True, detection_scale: float = 0.5):
        if cv2 is None:
            raise RuntimeError("opencv-python is required for live mode: pip install opencv-python")
        self.models_dir = Path(models_dir)
        self.recognition = False
        self.detector = self.recognizer = self.haar = None
        self.adaptive_clahe = adaptive_clahe
        self.detection_scale = max(0.25, min(1.0, detection_scale))
        if download:
            ensure_models(self.models_dir)
        det = self.models_dir / "face_detection_yunet_2023mar.onnx"
        rec = self.models_dir / "face_recognition_sface_2021dec.onnx"
        try:
            self.detector = cv2.FaceDetectorYN.create(str(det), "", (320, 320), score_threshold, 0.3, 5000)
            self.recognizer = cv2.FaceRecognizerSF.create(str(rec), "")
            self.recognition = True
        except Exception as exc:
            print(f"[face] YuNet/SFace unavailable ({exc}); falling back to Haar detection only - all faces unrecognised")
            self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def detect(self, frame) -> np.ndarray:
        """Return an (n, 15) array: x,y,w,h, 5 landmarks (x,y), score.
        Uses adaptive lighting enhancement and hardware-optimized multiscale inference."""
        h, w = frame.shape[:2]
        proc_frame = frame
        if self.adaptive_clahe:
            proc_frame, _ = enhance_low_light(frame)

        scale = self.detection_scale
        if scale < 0.99:
            sw, sh = max(32, int(w * scale)), max(32, int(h * scale))
            det_input = cv2.resize(proc_frame, (sw, sh), interpolation=cv2.INTER_LINEAR)
        else:
            sw, sh = w, h
            det_input = proc_frame

        if self.detector is not None:
            self.detector.setInputSize((sw, sh))
            _, faces = self.detector.detect(det_input)
            if faces is None or len(faces) == 0:
                return np.zeros((0, 15), np.float32)
            if scale < 0.99:
                # Scale bounding boxes and landmarks back to native resolution
                inv = 1.0 / scale
                faces[:, 0:14] *= inv
            return faces.astype(np.float32)

        gray = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2GRAY)
        boxes = self.haar.detectMultiScale(gray, 1.2, 5, minSize=(60, 60))
        rows = [[x, y, bw, bh] + [0.0] * 10 + [0.9] for (x, y, bw, bh) in boxes]
        return np.array(rows, dtype=np.float32).reshape(-1, 15)

    def embed(self, frame, face_row: np.ndarray) -> Optional[np.ndarray]:
        if not self.recognition:
            return None
        aligned = self.recognizer.alignCrop(frame, face_row)
        return self.recognizer.feature(aligned).astype(np.float32)
