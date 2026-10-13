"""Project: AI-Based Zero-Trust Smart Home Security And Child Safety System
Authors: Humera Tahzeeb (GE-232023385), Megha Saxena (GE-232023450), Yatharth Verma (GE-232023727)
Supervisor: Dr. Neha Tripathi, Graphic Era Deemed to be University, Dehradun
Academic Year: 2025-2026
Module: Multi-Tier Alert Dispatcher, Cooldown Aggregator & Offline Queue
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .config import Config
from .models import HIGH, LEVEL_RANK, MEDIUM, Assessment
from .sensors import ESP32Link


class LocalAlarm:
    """Two-tone siren on a background thread (winsound on Windows, bell elsewhere)."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def active(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self, duration_s: float = 20) -> None:
        if not self.enabled or self.active:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(duration_s,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self, duration_s: float) -> None:  # pragma: no cover - audio
        end = time.monotonic() + duration_s
        try:
            import winsound  # type: ignore
            while not self._stop.is_set() and time.monotonic() < end:
                winsound.Beep(1800, 350)
                winsound.Beep(1200, 350)
        except ImportError:
            while not self._stop.is_set() and time.monotonic() < end:
                sys.stdout.write("\a")
                sys.stdout.flush()
                time.sleep(0.7)


class OfflineAlertQueue:
    """Persistent local queue for unsent notifications when internet/Twilio is down (Limitation #4 Fix)."""

    def __init__(self, filepath: Path):
        self.path = filepath
        self._lock = threading.Lock()

    def enqueue(self, record: dict) -> None:
        with self._lock:
            queue = self.load()
            queue.append(record)
            self._save(queue)

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            import json
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save(self, items: list[dict]) -> None:
        try:
            import json
            self.path.write_text(json.dumps(items, indent=2), encoding="utf-8")
        except Exception as exc:
            pass

    def flush(self, send_fn) -> int:
        """Retry sending queued alerts once network is restored."""
        with self._lock:
            items = self.load()
            if not items:
                return 0
            remaining = []
            delivered = 0
            for item in items:
                try:
                    res = send_fn(item["body"], from_queue=True)
                    if res.get("status") == "sent":
                        delivered += 1
                    else:
                        remaining.append(item)
                except Exception:
                    remaining.append(item)
            self._save(remaining)
            return delivered


class LocalBroadcast:
    """Zero-Internet local network alert beacon via UDP broadcast (Limitation #4 Fix)."""

    def __init__(self, port: int = 8766, enabled: bool = True):
        self.port = port
        self.enabled = enabled

    def broadcast(self, payload: str) -> bool:
        if not self.enabled:
            return False
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.2)
            sock.sendto(payload.encode("utf-8"), ("<broadcast>", self.port))
            sock.close()
            return True
        except Exception:
            return False


class SMSNotifier:
    """Twilio SMS with offline persistent fallback and local resilience."""

    def __init__(self, cfg: Config, outbox: Path, queue_file: Optional[Path] = None):
        self.dry_run = bool(cfg["alerts"]["dry_run"])
        self.to = os.environ.get("ZT_SMS_TO") or cfg["alerts"]["sms_to"]
        self.outbox = outbox
        self.queue = OfflineAlertQueue(queue_file or outbox.parent / "offline_alerts.json")
        self.sent: list[dict] = []

    def send(self, body: str, from_queue: bool = False) -> dict:
        record = {"ts": datetime.now().isoformat(timespec="seconds"), "to": self.to or "(unset)", "body": body}
        sid, token, sender = (os.environ.get(k) for k in ("ZT_TWILIO_SID", "ZT_TWILIO_TOKEN", "ZT_TWILIO_FROM"))
        if self.dry_run or not (sid and token and sender and self.to):
            record["status"] = "dry-run"
            with self.outbox.open("a", encoding="utf-8") as fh:
                fh.write(f"{record['ts']} -> {record['to']}: {body}\n")
        else:  # pragma: no cover - network
            try:
                from twilio.rest import Client  # type: ignore
                Client(sid, token).messages.create(to=self.to, from_=sender, body=body)
                record["status"] = "sent"
            except Exception as exc:
                record["status"] = f"error: {exc}"
                if not from_queue:
                    # Enqueue for offline resilience when Wi-Fi/Twilio network is cut
                    self.queue.enqueue(record)
                    record["status"] = f"queued-offline ({exc})"
        self.sent.append(record)
        return record


class PushNotifier:
    """Optional ntfy.sh push notification (free, no account needed)."""

    def __init__(self, topic: str):
        self.topic = topic

    def send(self, title: str, body: str) -> str:
        if not self.topic:
            return "dashboard-only"
        try:  # pragma: no cover - network
            req = urllib.request.Request(f"https://ntfy.sh/{self.topic}", data=body.encode(),
                                         headers={"Title": title, "Priority": "high"})
            urllib.request.urlopen(req, timeout=5).read()
            return "sent"
        except Exception as exc:  # pragma: no cover
            return f"error: {exc}"


@dataclass
class AlertDecision:
    fire: bool = False              # an alert was issued this frame
    suppressed: bool = False        # grouped into an existing incident (cooldown)
    new_incident: bool = False
    escalated: bool = False
    capture_evidence: bool = False
    incident_id: Optional[int] = None
    actions: list[str] = field(default_factory=list)


@dataclass
class _Incident:
    id: int
    start: datetime
    last_active: datetime
    last_alert: datetime
    max_rank: int
    muted_rank: int = -1            # guardian ALLOW silences up to this rank
    confirmed: bool = False         # guardian DENY (confirmed threat)
    suppressed: int = 0


class AlertManager:
    def __init__(self, cfg: Config, link: ESP32Link, data_dir: Path, local_beep: Optional[bool] = None):
        self.cfg = cfg
        self.link = link
        t = cfg["timing"]
        self.cooldown = timedelta(seconds=t["cooldown_s"])
        self.quiet = timedelta(seconds=t["incident_quiet_s"])
        self.alarm_duration = t["alarm_duration_s"]
        beep = cfg["alerts"]["local_beep"] if local_beep is None else local_beep
        self.alarm = LocalAlarm(enabled=bool(beep))
        self.sms = SMSNotifier(cfg, data_dir / "sms_outbox.log", data_dir / "offline_alerts.json")
        self.push = PushNotifier(cfg["alerts"]["ntfy_topic"])
        self.broadcast = LocalBroadcast(enabled=bool(cfg["alerts"].get("local_lan_broadcast", True)))
        self.incident: Optional[_Incident] = None
        self._next_id = 1
        self.total_suppressed = 0
        self.total_alerts = 0

    # ---------------------------------------------------------------- policy
    def process(self, a: Assessment) -> AlertDecision:
        ts, rank = a.timestamp, a.rank
        inc = self.incident
        if inc and abs((ts - inc.last_active).total_seconds()) > self.quiet.total_seconds():
            self._close()  # the previous event has ended
            inc = None
        if rank == 0:
            return AlertDecision(incident_id=inc.id if inc else None)

        new = inc is None
        if new:
            inc = self.incident = _Incident(self._next_id, ts, ts, ts - self.cooldown - timedelta(seconds=1), -1)
            self._next_id += 1
        inc.last_active = ts
        escalated = (not new) and rank > inc.max_rank
        reminder = ts - inc.last_alert >= self.cooldown
        decision = AlertDecision(new_incident=new, escalated=escalated, incident_id=inc.id)

        muted = rank <= inc.muted_rank
        if muted or not (new or escalated or reminder):
            inc.suppressed += 1
            self.total_suppressed += 1
            decision.suppressed = True
            inc.max_rank = max(inc.max_rank, rank)
            return decision

        inc.max_rank = max(inc.max_rank, rank)
        inc.last_alert = ts
        decision.fire = True
        self.total_alerts += 1
        body = self.format_message(a, inc.id)
        push_status = self.push.send(f"ZeroTrust {a.level}", body)
        decision.actions.append(f"push:{push_status}")
        self.broadcast.broadcast(body)
        decision.actions.append("lan:broadcast")
        if rank >= LEVEL_RANK[HIGH]:
            self.alarm.start(self.alarm_duration)
            self.link.set_alarm(True)
            decision.actions += ["siren:local", "siren:esp32", f"sms:{self.sms.send(body)['status']}"]
            decision.capture_evidence = new or escalated
        elif rank == LEVEL_RANK[MEDIUM] and self.cfg["alerts"]["sms_on_medium"]:
            decision.actions.append(f"sms:{self.sms.send(body)['status']}")
        return decision

    # --------------------------------------------------------------- control
    def guardian_decision(self, decision: str) -> None:
        """ALLOW silences the current incident; DENY confirms the threat."""
        inc = self.incident
        if decision == "allow":
            self.silence()
            if inc:
                inc.muted_rank = inc.max_rank
        elif decision == "deny" and inc:
            inc.confirmed = True
            self.alarm.start(self.alarm_duration)
            self.link.set_alarm(True)
            self.sms.send(f"[ZeroTrust] Guardian CONFIRMED threat (incident #{inc.id}). Contact emergency services if needed.")

    def silence(self) -> None:
        self.alarm.stop()
        self.link.set_alarm(False)

    def _close(self) -> None:
        self.silence()
        self.incident = None

    @staticmethod
    def format_message(a: Assessment, incident_id: int) -> str:
        top = "; ".join(s.reason for s in sorted(a.signals, key=lambda s: -s.points) if s.points > 0)[:220]
        return f"[ZeroTrust #{incident_id}] {a.level} risk {a.score:.0f}/100 - {a.summary}. {top}"
