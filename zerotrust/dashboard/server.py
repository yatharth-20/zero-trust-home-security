"""Guardian dashboard: dependency-free HTTP server (stdlib only) + single-page UI."""
from __future__ import annotations

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

# Resilient imports: supports both running directly (`python server.py`) and as a package
try:
    from ..config import ROOT, load_config
    from ..pipeline import SecuritySystem
except (ImportError, ValueError):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from zerotrust.config import ROOT, load_config
    from zerotrust.pipeline import SecuritySystem

STATIC = Path(__file__).parent / "static"
MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".jpg": "image/jpeg",
    ".mp4": "video/mp4",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".ico": "image/x-icon",
}


def make_handler(system: SecuritySystem, demo=None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # silence request logging
            pass

        def handle(self):
            """Gracefully catch client-aborted connections without logging noisy tracebacks."""
            try:
                super().handle()
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError):
                pass

        # ---------------------------------------------------------- helpers
        def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: Optional[dict] = None) -> None:
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, OSError):
                pass

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj, default=str).encode())

        def _file(self, path: Path) -> None:
            if not path.is_file():
                return self._send(404, b'{"error":"not found"}')
            self._send(200, path.read_bytes(), MIME.get(path.suffix, "application/octet-stream"))

        def _body(self) -> dict:
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if not n:
                    return {}
                return json.loads(self.rfile.read(n) or b"{}")
            except (json.JSONDecodeError, OSError, ValueError):
                return {}

        # -------------------------------------------------------------- GET
        def do_GET(self):
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._file(STATIC / "index.html")
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if path.startswith("/static/"):
                return self._file(STATIC / Path(path).name)
            if path.startswith("/evidence/"):
                return self._file(system.evidence.media / Path(path).name)
            if path == "/api/state":
                state = system.snapshot()
                state["demo"] = bool(demo)
                state["playing"] = demo.playing if demo else None
                return self._json(state)
            if path == "/api/scenarios":
                return self._json(demo.catalogue() if demo else {"benign": [], "threat": []})
            if path == "/api/results":
                f = ROOT / "results" / "evaluation.json"
                return self._file(f) if f.exists() else self._json({"error": "no results yet"}, 404)
            if path == "/api/config":
                return self._json({
                    "zones": system.cfg["zones"],
                    "profiles": system.cfg["profiles"],
                    "thresholds": system.cfg["risk"]["thresholds"],
                    "weights": system.cfg["risk"]["weights"],
                })
            if path == "/api/stream":
                return self._stream()
            self._send(404, b'{"error":"not found"}')

        def _stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                while True:
                    jpg = system.last_jpeg
                    if jpg:
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                            + str(len(jpg)).encode()
                            + b"\r\n\r\n"
                            + jpg
                            + b"\r\n"
                        )
                    time.sleep(0.1)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return

        # ------------------------------------------------------------- POST
        def do_POST(self):
            path, body = urlparse(self.path).path, self._body()
            if path == "/api/override":
                res = system.override(int(body.get("event_id", 0)), str(body.get("decision", "")))
                return self._json(res, 200 if res.get("ok") else 400)
            if path == "/api/sensors":
                system.link.set(door=body.get("door"), pir=body.get("pir"))
                return self._json({"ok": True})
            if path == "/api/zone":
                if body.get("zone") in system.cfg["zones"]:
                    system.active_zone = body["zone"]
                return self._json({"ok": True, "zone": system.active_zone})
            if path == "/api/adults_away":
                system.set_adults_away(body.get("away"))
                return self._json({"ok": True})
            if path == "/api/silence":
                system.alerts.silence()
                return self._json({"ok": True})
            if path == "/api/scenario":
                ok = bool(demo and demo.play(str(body.get("key", ""))))
                return self._json({"ok": ok}, 200 if ok else 409)
            if path == "/api/audio_anomaly":
                ev = body.get("event", "Glass shatter / child scream")
                system.audio.trigger_anomaly(event_type=ev)
                return self._json({"ok": True, "event": ev})
            if path == "/api/camera_switch":
                sources = system.cfg["vision"].get("camera_sources") or [
                    {"id": 0, "name": "Entrance Primary Cam", "zone": "entry"},
                    {"id": 1, "name": "Backyard & Window FOV", "zone": "bedroom"},
                    {"id": 2, "name": "Living Room Cam", "zone": "living_room"},
                ]
                cur_zone = system.active_zone
                cur_idx = 0
                for i, s in enumerate(sources):
                    if s.get("zone") == cur_zone:
                        cur_idx = i
                        break
                nxt = sources[(cur_idx + 1) % len(sources)]
                system.active_zone = nxt.get("zone", system.active_zone)
                return self._json({"ok": True, "camera": nxt})
            if path == "/api/evaluate":
                from ..evaluation import evaluate
                return self._json(evaluate(int(body.get("n", 400)), int(body.get("seed", 11))))
            self._send(404, b'{"error":"not found"}')

    return Handler


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that suppresses noisy WinError 10054 / BrokenPipeError on browser reload."""

    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        _, exc, _ = sys.exc_info()
        if exc and isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def serve(system: SecuritySystem, host: str, port: int, demo=None, block: bool = True) -> ThreadingHTTPServer:
    """Serve the dashboard HTTP server, gracefully selecting the next open port if occupied."""
    target_port = port
    server = None
    for p in range(target_port, target_port + 10):
        try:
            server = QuietThreadingHTTPServer((host, p), make_handler(system, demo))
            port = p
            break
        except OSError as err:
            if err.errno == 10048 or "10048" in str(err) or "address already in use" in str(err).lower():
                continue
            raise

    if server is None:
        server = QuietThreadingHTTPServer((host, port), make_handler(system, demo))

    server.daemon_threads = True
    print(f"[dashboard] http://{host}:{port}")
    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    else:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    cfg = load_config()
    sys_instance = SecuritySystem(cfg, mode="demo")
    try:
        from zerotrust.demo import DemoPlayer
        demo_instance = DemoPlayer(sys_instance, cfg)
        demo_instance.start_auto()
    except Exception:
        demo_instance = None
    h = cfg["dashboard"]["host"]
    pt = cfg["dashboard"]["port"]
    serve(sys_instance, h, pt, demo=demo_instance, block=True)
