"""Evaluation harness: System A (face-recognition only) vs System B (context-aware fusion).

Research question: does fusing identity, timing, location, liveness, behaviour
and sensor data meaningfully reduce false positives (and missed threats)
compared with facial recognition used in isolation?

Metrics: response time, false-alarm rate, precision, recall, F1 - plus
per-scenario breakdowns, feature ablations and the effect of cooldown grouping.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Optional

import numpy as np

from .alerts import AlertManager
from .baseline import BehaviorBaseline
from .config import ROOT, Config, load_config
from .context import ContextModel, HouseholdState
from .models import SceneObservation
from .risk import RiskEngine
from .sensors import ESP32Link
from .simulation import BENIGN, STEP_S, THREAT, Scenario, ScenarioFactory

ABLATIONS = {
    "B: full fusion": {},
    "B - sensors": {"risk": {"use_sensors": False}},
    "B - behaviour baseline": {"risk": {"use_behavior": False}},
    "B - context (zone/schedule/child)": {"risk": {"use_context": False}},
    "B - liveness": {"risk": {"use_liveness": False}},
    "B - tailgating logic": {"risk": {"use_tailgating": False}},
}


# ------------------------------------------------------------------ System A
def baseline_alert(obs: SceneObservation) -> bool:
    """Standard facial recognition: judge only the primary (earliest) face.
    Recognised -> safe.  Unrecognised -> alert.  No other context is considered."""
    if not obs.persons:
        return False
    primary = min(obs.persons, key=lambda p: (p.first_seen or obs.timestamp, p.track_id))
    return not primary.known


def _metrics(rows: list[dict], key: str) -> dict:
    tp = sum(1 for r in rows if r["label"] == "threat" and r[key])
    fn = sum(1 for r in rows if r["label"] == "threat" and not r[key])
    fp = sum(1 for r in rows if r["label"] == "benign" and r[key])
    tn = sum(1 for r in rows if r["label"] == "benign" and not r[key])
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    far = fp / (fp + tn) if fp + tn else 0.0
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": precision, "recall": recall, "f1": f1,
            "false_alarm_rate": far, "accuracy": (tp + tn) / max(1, len(rows))}


def _run_a(scenarios: list[Scenario]) -> list[dict]:
    out = []
    for sc in scenarios:
        t0 = time.perf_counter()
        first = None
        for i, obs in enumerate(sc.frames):
            if baseline_alert(obs):
                first = i
                break
        elapsed = (time.perf_counter() - t0) * 1000.0 / max(1, len(sc.frames))
        out.append({"alert": first is not None, "first_frame": first, "latency_ms": elapsed})
    return out


def _run_b(cfg: Config, baseline: BehaviorBaseline, scenarios: list[Scenario], cooldown_stats: bool = False) -> list[dict]:
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        link = ESP32Link()
        for sc in scenarios:
            engine = RiskEngine(cfg, baseline, ContextModel(cfg), HouseholdState(cfg["timing"]["presence_timeout_s"]))
            mgr = AlertManager(cfg, link, Path(tmp), local_beep=False) if cooldown_stats else None
            first, naive, fired, lat, peak = None, 0, 0, [], 0.0
            for i, obs in enumerate(sc.frames):
                a = engine.assess(obs)
                lat.append(a.latency_ms)
                peak = max(peak, a.score)
                if a.rank >= 1:
                    naive += 1
                    first = i if first is None else first
                if mgr:
                    fired += int(mgr.process(a).fire)
            out.append({"alert": first is not None, "first_frame": first, "latency_ms": float(np.mean(lat)),
                        "peak_score": peak, "naive_alerts": naive, "grouped_alerts": fired})
    return out


def _mean_response(rows: list[dict], res: list[dict], key: str = "alert") -> Optional[float]:
    frames = [r["first_frame"] for r, lab in zip(res, (x["label"] for x in rows))
              if lab == "threat" and r["alert"] and r["first_frame"] is not None]
    return float(np.mean(frames) * STEP_S) if frames else None


def evaluate(n: int = 600, seed: int = 11, cfg: Optional[Config] = None, save: bool = True) -> dict:
    cfg = cfg or load_config()
    rng = np.random.default_rng(seed)
    baseline = BehaviorBaseline(alpha=cfg["baseline"]["alpha"], min_observations=cfg["baseline"]["min_observations"],
                                surprise_floor=cfg["baseline"]["surprise_floor"],
                                surprise_span=cfg["baseline"]["surprise_span"])
    baseline.seed_routine(rng, days=30)  # training period (frozen during testing)
    factory = ScenarioFactory(cfg, seed=seed)
    scenarios = [factory.random() for _ in range(n)]
    rows = [{"key": s.key, "label": s.label, "title": s.title} for s in scenarios]

    a_res = _run_a(scenarios)
    for r, x in zip(rows, a_res):
        r["A"] = x["alert"]
    systems = {"A: face-recognition only": {**_metrics([{**r, "x": r["A"]} for r in rows], "x")}}
    systems["A: face-recognition only"]["response_s"] = _mean_response(rows, a_res)
    systems["A: face-recognition only"]["latency_ms"] = float(np.mean([x["latency_ms"] for x in a_res]))

    ablation = {}
    full_res = None
    for name, ov in ABLATIONS.items():
        vcfg = load_config(overrides=ov)
        res = _run_b(vcfg, baseline, scenarios, cooldown_stats=(name == "B: full fusion"))
        if name == "B: full fusion":
            full_res = res
        m = _metrics([{"label": r["label"], "x": x["alert"]} for r, x in zip(rows, res)], "x")
        m["response_s"] = _mean_response(rows, res)
        m["latency_ms"] = float(np.mean([x["latency_ms"] for x in res]))
        ablation[name] = m
    systems["B: context-aware fusion"] = ablation["B: full fusion"]
    for r, x in zip(rows, full_res):
        r["B"] = x["alert"]
        r["B_peak"] = x["peak_score"]

    # per-scenario breakdown
    per = []
    for key in BENIGN + THREAT:
        sub = [r for r in rows if r["key"] == key]
        if not sub:
            continue
        per.append({"key": key, "title": sub[0]["title"], "label": sub[0]["label"], "n": len(sub),
                    "A_alert_rate": sum(r["A"] for r in sub) / len(sub),
                    "B_alert_rate": sum(r["B"] for r in sub) / len(sub),
                    "B_mean_peak": float(np.mean([r["B_peak"] for r in sub]))})

    naive = sum(x["naive_alerts"] for x in full_res)
    grouped = sum(x["grouped_alerts"] for x in full_res)
    result = {
        "n_scenarios": n, "seed": seed,
        "n_threat": sum(r["label"] == "threat" for r in rows), "n_benign": sum(r["label"] == "benign" for r in rows),
        "systems": systems, "ablation": ablation, "per_scenario": per,
        "cooldown": {"naive_notifications": naive, "grouped_notifications": grouped,
                     "reduction": 1 - grouped / naive if naive else 0.0},
        "assumptions": [
            "Synthetic scenarios with injected recognition noise (4% false-reject, 1% false-accept, 5% sensor dropout).",
            "System A judges only the primary face: recognised -> safe, unrecognised -> alert.",
            "An 'alert' for System B is any frame at MEDIUM risk or above (score >= %d)." % cfg["risk"]["thresholds"]["medium"],
            "Ground truth is defined by the scenario design/protocol; replace with real labelled trials for publication.",
        ],
    }
    if save:
        out = ROOT / "results"
        out.mkdir(exist_ok=True)
        (out / "evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (out / "evaluation.md").write_text(to_markdown(result), encoding="utf-8")
        with (out / "per_scenario.csv").open("w", encoding="utf-8") as fh:
            fh.write("key,label,A_alert_rate,B_alert_rate,B_mean_peak\n")
            for p in per:
                fh.write(f"{p['key']},{p['label']},{p['A_alert_rate']:.3f},{p['B_alert_rate']:.3f},{p['B_mean_peak']:.1f}\n")
    return result


def to_markdown(res: dict) -> str:
    def row(name, m):
        rs = f"{m['response_s']:.1f}s" if m.get("response_s") is not None else "n/a"
        return (f"| {name} | {m['precision']:.3f} | {m['recall']:.3f} | {m['f1']:.3f} | {m['false_alarm_rate']:.3f} | "
                f"{rs} | {m['latency_ms']:.3f} |")
    head = ("| System | Precision | Recall | F1 | False-alarm rate | Mean time to alert | Compute / frame (ms) |\n"
            "|---|---|---|---|---|---|---|\n")
    lines = [f"# Evaluation: context beats identity alone?\n",
             f"{res['n_scenarios']} synthetic scenarios ({res['n_threat']} threats, {res['n_benign']} benign), seed {res['seed']}.\n",
             "## System A vs System B\n", head]
    lines += [row(k, v) + "\n" for k, v in res["systems"].items()]
    lines += ["\n## Ablation (what each modality contributes)\n\n", head]
    lines += [row(k, v) + "\n" for k, v in res["ablation"].items()]
    lines += ["\n## Per-scenario alert rate\n\n| Scenario | Truth | A alerts | B alerts | B mean peak score |\n|---|---|---|---|---|\n"]
    lines += [f"| {p['title']} | {p['label']} | {p['A_alert_rate']:.0%} | {p['B_alert_rate']:.0%} | {p['B_mean_peak']:.0f} |\n"
              for p in res["per_scenario"]]
    c = res["cooldown"]
    lines += [f"\n## Cooldown grouping\n\nNaive per-frame alerts: **{c['naive_notifications']}** -> grouped: "
              f"**{c['grouped_notifications']}** ({c['reduction']:.0%} fewer notifications).\n",
              "\n## Assumptions\n\n"] + [f"- {a}\n" for a in res["assumptions"]]
    return "".join(lines)


if __name__ == "__main__":  # pragma: no cover
    r = evaluate()
    print(to_markdown(r))
