"""Project: AI-Based Zero-Trust Smart Home Security And Child Safety System
Authors: Humera Tahzeeb (GE-232023385), Megha Saxena (GE-232023450), Yatharth Verma (GE-232023727)
Supervisor: Dr. Neha Tripathi, Graphic Era Deemed to be University, Dehradun
Academic Year: 2025-2026
Main CLI Entrypoint for AI-Based Zero-Trust Smart Home Security System.

Commands:
  python main.py live [--camera 0] [--port 8765]
  python main.py enroll --name "Homeowner" [--images <path>] [--samples 20]
  python main.py demo [--port 8765] [--speed 1.0]
  python main.py eval [--samples 600] [--seed 11]
  python main.py dashboard [--port 8765]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from zerotrust.config import load_config
from zerotrust.pipeline import SecuritySystem


def cmd_enroll(args):
    from zerotrust.live import enroll
    cfg = load_config(args.config)
    images_path = Path(args.images) if args.images else None
    count = enroll(cfg, args.name, images=images_path, samples=args.samples, camera=args.camera)
    print(f"\n[enroll] Successfully enrolled {count} face embeddings for '{args.name}'.")


def cmd_live(args):
    from zerotrust.dashboard.server import serve
    from zerotrust.live import LiveRunner

    cfg = load_config(args.config)
    system = SecuritySystem(cfg)
    host, port = cfg["dashboard"]["host"], args.port or cfg["dashboard"]["port"]
    print(f"[system] Starting local dashboard at http://{host}:{port} ...")
    serve(system, host, port, block=False)

    runner = LiveRunner(system, cfg, show_window=not args.no_gui, camera=args.camera)
    runner.run()


def cmd_demo(args):
    from zerotrust.dashboard.server import serve
    from zerotrust.demo import DemoPlayer

    cfg = load_config(args.config)
    system = SecuritySystem(cfg, mode="demo")
    player = DemoPlayer(system, cfg, speed=args.speed, seed=args.seed)
    host, port = cfg["dashboard"]["host"], args.port or cfg["dashboard"]["port"]
    print(f"[demo] Dashboard ready at http://{host}:{port}")
    if args.auto:
        player.start_auto()
    serve(system, host, port, demo=player, block=True)


def cmd_eval(args):
    from zerotrust.evaluation import evaluate, to_markdown

    cfg = load_config(args.config)
    res = evaluate(n=args.samples, seed=args.seed, cfg=cfg, save=True)
    print(to_markdown(res))


def cmd_dashboard(args):
    from zerotrust.dashboard.server import serve

    cfg = load_config(args.config)
    system = SecuritySystem(cfg)
    host, port = cfg["dashboard"]["host"], args.port or cfg["dashboard"]["port"]
    serve(system, host, port, block=True)


def main():
    parser = argparse.ArgumentParser(description="Zero-Trust Smart Home Security & Child Safety System")
    parser.add_argument("--config", "-c", type=str, default=None, help="Path to custom settings.json")
    subparsers = parser.add_subparsers(dest="command", help="System command to execute")

    # Enroll
    p_enroll = subparsers.add_parser("enroll", help="Enroll face embeddings for authorized residents")
    p_enroll.add_argument("--name", "-n", required=True, type=str, help="Name of household member (e.g. Homeowner)")
    p_enroll.add_argument("--images", "-i", type=str, default=None, help="Directory of face photos")
    p_enroll.add_argument("--samples", "-s", type=int, default=20, help="Number of face samples to capture")
    p_enroll.add_argument("--camera", type=int, default=None, help="Camera device index")

    # Live
    p_live = subparsers.add_parser("live", help="Run live multi-modal detection system")
    p_live.add_argument("--camera", type=int, default=None, help="Camera device index or RTSP stream URL")
    p_live.add_argument("--port", "-p", type=int, default=None, help="Dashboard port")
    p_live.add_argument("--no-gui", action="store_true", help="Run headless without OpenCV GUI window")

    # Demo
    p_demo = subparsers.add_parser("demo", help="Run simulated test scenarios with dashboard")
    p_demo.add_argument("--port", "-p", type=int, default=None, help="Dashboard port")
    p_demo.add_argument("--speed", type=float, default=1.0, help="Scenario playback speed multiplier")
    p_demo.add_argument("--seed", type=int, default=11, help="Random scenario seed")
    p_demo.add_argument("--auto", action="store_true", help="Continuously cycle through scenarios")

    # Eval
    p_eval = subparsers.add_parser("eval", help="Run benchmark evaluation (System A vs System B)")
    p_eval.add_argument("--samples", "-n", type=int, default=600, help="Total synthetic scenarios")
    p_eval.add_argument("--seed", type=int, default=11, help="Random evaluation seed")

    # Dashboard only
    p_dash = subparsers.add_parser("dashboard", help="Start standalone Guardian dashboard")
    p_dash.add_argument("--port", "-p", type=int, default=None, help="Dashboard port")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "enroll": cmd_enroll,
        "live": cmd_live,
        "demo": cmd_demo,
        "eval": cmd_eval,
        "dashboard": cmd_dashboard,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
