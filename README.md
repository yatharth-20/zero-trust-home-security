# AI-Based Zero-Trust Smart Home Security & Child Safety System
### Using Multi-Modal Intrusion Detection

[![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.14-blue.svg)](https://www.python.org/)
[![OpenCV](https://img.shields.io/badge/OpenCV-Zoo%20ONNX-green.svg)](https://opencv.org/)
[![Architecture](https://img.shields.io/badge/Security-Zero--Trust%20(NIST%20SP%20800--207)-red.svg)](https://csrc.nist.gov/publications/detail/sp/800-207/final)
[![Institution](https://img.shields.io/badge/Graphic%20Era%20University-B.Tech%20CSE%20Major%20Project-orange.svg)](https://www.geu.ac.in/)
[![Tests](https://img.shields.io/badge/Tests-6%2F6%20Passed-brightgreen.svg)](tests/)

---

## 📌 Project Overview

Traditional residential security systems rely on static perimeter verification (CCTV recordings, door sensors, or simple face match). Once an entity crosses the boundary, they are granted **implicit trust**, leaving homes vulnerable to insider anomalies, identity spoofing, and child hazard emergencies.

This project introduces an edge-deployable, **Multi-Modal Zero-Trust Security Framework** adhering to the NIST core doctrine: **"Never trust, always verify."** Every observation inside the home undergoes continuous, contextual risk evaluation combining computer vision, facial biometrics, behavioral normalcy baselines, acoustic spike detection, and spatial geofencing.

### 👥 Authors & Academic Attribution
* **Authors:** Humera Tahzeeb (`GE-232023385`), Megha Saxena (`GE-232023450`), Yatharth Verma (`GE-232023727`)
* **Project Guide:** Dr. Neha Tripathi, Professor, Department of Computer Science & Engineering
* **Institution:** Graphic Era Deemed to be University, Dehradun, Uttarakhand, India
* **Academic Year:** 2025–2026 (B.Tech Computer Science & Engineering Major Project)

---

## 🚀 Key Architectural Innovations

1. **Zero-Trust Multi-Factor Risk Fusion Engine (`zerotrust/risk.py`)**
   * Computes dynamic composite risk scores $R \in [0.0, 1.0]$ based on weighted anomaly attribution:
     * Unrecognized Face: `+0.35`
     * Restricted Zone (Kitchen, Nursery, Balcony): `+0.30`
     * Off-Hours / Quiet Hours: `+0.20`
     * Rapid Kinematic Motion: `+0.15`
   * Dwell-time escalation and resident activity grace periods.

2. **Edge Neural Biometrics & Liveness Verification (`zerotrust/vision/`)**
   * **Face Detection:** YuNet (`face_detection_yunet_2023mar.onnx`) - 1ms ultra-lightweight detector.
   * **Face Recognition:** SFace (`face_recognition_sface_2021dec.onnx`) - 512-D hypersphere metric embeddings.
   * **Anti-Spoofing:** Texture-based Laplacian edge variance and HSV chroma dispersion checks.
   * **Adaptive Low-Light CLAHE:** LAB-space contrast enhancement for nocturnal and shadowed captures.

3. **Dedicated Child Safety Subsystem**
   * Continuous monitoring of unescorted toddlers near designated physical hazard boundaries.
   * Autonomous escalation to immediate alert dispatch when children linger unassisted in restricted zones.

4. **Multi-Tier Alerting & Resilient Dispatch (`zerotrust/alerts.py`)**
   * **On-Site Deterrence:** Local PC beep buzzer + ESP32 IoT siren trigger.
   * **Remote Warnings:** Twilio cellular SMS notifications + NTFY push broadcasts.
   * **Offline Resilience:** `OfflineAlertQueue` caches alerts during WAN outages and automatically flushes them on reconnection.
   * **Local Failover:** UDP broadcast failover over local subnet when internet gateways are severed.
   * **Cooldown Aggregator:** Eliminates redundant notification storms during continuous movement.

5. **Acoustic Anomaly Detection (`zerotrust/audio.py`)**
   * Solves camera Field of View (FOV) blind spots by monitoring acoustic RMS energy and high-frequency spike thresholds for glass breakages and distress screams.

6. **Interactive Guardian Web Dashboard (`zerotrust/dashboard/`)**
   * Real-time WebSocket telemetry stream.
   * Live biometric camera feed HUD with face bounding boxes, recognized identities, and landmarks.
   * Interactive Scenario Simulation Lab (Parent Ingress, Night Intruder, Unescorted Child Hazard, Acoustic Distress).

---

## 📂 Repository Structure

```text
zero-trust-home-security/
├── config/                  # System YAML/JSON configurations (zones, quiet hours)
├── data/                    # Enrolled resident biometric embeddings
├── docs/                    # Academic synopsis and project presentation
│   ├── Project_Synopsis.docx
│   └── Project_Presentation.pptx
├── models/                  # Pre-trained ONNX neural weights (YuNet, SFace)
├── results/                 # Evaluation benchmarks (Markdown, CSV, JSON)
├── tests/                   # Automated pytest mitigation suite (6/6 tests passing)
├── zerotrust/               # Core Python Package
│   ├── alerts.py            # Multi-tier alert manager & offline spooler
│   ├── audio.py             # Acoustic distress & glass break detector
│   ├── baseline.py          # Hourly normalcy baseline statistical model
│   ├── config.py            # Global environment configuration loader
│   ├── context.py           # Multi-camera zone & schedule aggregator
│   ├── demo.py              # Scenario runner with simulated edge camera
│   ├── evaluation.py        # 600-sample benchmark evaluator
│   ├── evidence.py          # Cryptographic visual evidence logger
│   ├── live.py              # Multi-camera threaded live monitoring
│   ├── models.py            # Domain dataclasses & schemas
│   ├── pipeline.py          # Top-level multi-modal fusion orchestrator
│   ├── risk.py              # Zero-Trust mathematical risk engine
│   ├── dashboard/           # Web dashboard server (WebSocket + HTTP)
│   └── vision/              # YuNet detector, SFace recognizer, tracker, liveness
├── main.py                  # Primary CLI controller interface
├── package_for_submission.py# Clean packaging utility (excludes .venv & caches)
├── run.bat                  # One-click Windows runner (inner)
├── run_project.bat          # One-click Windows runner (root)
└── README.md                # Project documentation
```

---

## ⚡ Quick Start & Installation

### 1. Prerequisites
* Python 3.10+ (Compatible with Python 3.10, 3.11, 3.12, 3.14)
* Windows 10/11, Linux, or macOS

### 2. Clone the Repository
```bash
git clone https://github.com/yatharth-20/zero-trust-home-security.git
cd zero-trust-home-security
```

### 3. Setup Virtual Environment
```bash
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt  # Or pip install opencv-python numpy twilio pytest
```

### 4. Run the System

#### Option A: One-Click Windows Launcher (Recommended)
Simply double-click `run.bat` or run:
```cmd
run.bat
```
Select `[1]` to launch the Guardian Dashboard and auto-open `http://localhost:8765`.

#### Option B: CLI Commands
```bash
# 1. Launch Interactive Demo with Web Dashboard & Simulated Biometric Stream:
python main.py demo --auto --port 8765

# 2. Launch Real Live USB Webcam Monitoring:
python main.py live --camera 0 --port 8765

# 3. Enroll an Authorized Resident's Face:
python main.py enroll --name "Yatharth" --samples 20

# 4. Run 600-Scenario Benchmark Evaluation:
python main.py eval --samples 600

# 5. Run Automated Mitigation Tests:
pytest tests/ -v
```

---

## 📊 Evaluation & Benchmarks

Empirical testing on 600 multi-modal scenarios demonstrates superior threat discrimination compared to traditional CCTV and standalone face recognition:

| Metric | Standalone Face Recognition | Zero-Trust Multi-Modal System |
| :--- | :--- | :--- |
| **Intrusion Detection Rate** | 82.4% | **98.7%** |
| **Child Hazard Response Latency** | N/A (Unmonitored) | **< 320 ms** |
| **False Alarm Rate** | 24.1% | **< 3.2%** |
| **Average Decision Latency** | 120 ms | **38 ms** (Edge-Inference) |

Detailed results are available in [`results/evaluation.md`](results/evaluation.md) and [`results/per_scenario.csv`](results/per_scenario.csv).

---

## 📜 Academic References & Citations

1. **NIST SP 800-207**, *"Zero Trust Architecture,"* National Institute of Standards and Technology, Gaithersburg, MD, Aug. 2020. [doi:10.6028/NIST.SP.800-207](https://doi.org/10.6028/NIST.SP.800-207).
2. **F. Schroff, D. Kalenichenko, and J. Philbin**, *"FaceNet: A unified embedding for face recognition and clustering,"* in *Proc. IEEE CVPR*, 2015, pp. 815–823.
3. **Y. Zhong et al.**, *"SFace: Sigmoid-constrained hypersphere loss for robust face recognition,"* *IEEE Transactions on Image Processing*, vol. 30, pp. 2587–2598, 2021.
4. **W. Wu, P. Peng, and H. Ling**, *"YuNet: An ultra-high-performance and lightweight face detector,"* *OpenCV Model Zoo*, 2023.
5. **S. Sicari et al.**, *"Security, privacy and trust in Internet of Things: The road ahead,"* *Computer Networks*, vol. 76, pp. 146–164, 2015.
6. **M. A. Al-Garadi et al.**, *"A survey of machine and deep learning methods for Internet of Things (IoT) security,"* *IEEE Communications Surveys & Tutorials*, vol. 22, no. 3, pp. 1646–1685, 2020.

---

## 📄 License
This academic project is developed for educational and research purposes under the **Apache-2.0 License**.
