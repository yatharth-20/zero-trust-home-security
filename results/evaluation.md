# Evaluation: context beats identity alone?
400 synthetic scenarios (181 threats, 219 benign), seed 11.
## System A vs System B
| System | Precision | Recall | F1 | False-alarm rate | Mean time to alert | Compute / frame (ms) |
|---|---|---|---|---|---|---|
| A: face-recognition only | 0.517 | 0.343 | 0.412 | 0.265 | 0.0s | 0.001 |
| B: context-aware fusion | 0.955 | 0.934 | 0.944 | 0.037 | 2.5s | 0.141 |

## Ablation (what each modality contributes)

| System | Precision | Recall | F1 | False-alarm rate | Mean time to alert | Compute / frame (ms) |
|---|---|---|---|---|---|---|
| B: full fusion | 0.955 | 0.934 | 0.944 | 0.037 | 2.5s | 0.141 |
| B - sensors | 0.834 | 0.834 | 0.834 | 0.137 | 2.9s | 0.122 |
| B - behaviour baseline | 0.983 | 0.934 | 0.958 | 0.014 | 2.5s | 0.032 |
| B - context (zone/schedule/child) | 0.789 | 0.746 | 0.767 | 0.164 | 2.6s | 0.116 |
| B - liveness | 0.950 | 0.845 | 0.895 | 0.037 | 2.6s | 0.130 |
| B - tailgating logic | 0.952 | 0.884 | 0.917 | 0.037 | 2.4s | 0.152 |

## Per-scenario alert rate

| Scenario | Truth | A alerts | B alerts | B mean peak score |
|---|---|---|---|---|
| Household member arrives | benign | 5% | 5% | 2 |
| Family in the living room | benign | 0% | 4% | 25 |
| Approved worker, normal hours | benign | 0% | 0% | 2 |
| Delivery at the door | benign | 100% | 7% | 27 |
| Resident home late | benign | 7% | 7% | 7 |
| Child arrives with parent | benign | 0% | 0% | 2 |
| Child home alone, nobody else | benign | 6% | 6% | 6 |
| Phantom camera detection | benign | 100% | 0% | 21 |
| Pet triggers PIR | benign | 0% | 0% | 18 |
| Stranger in the bedroom | threat | 100% | 100% | 88 |
| Photo / screen spoof | threat | 0% | 89% | 48 |
| Tailgating at the door | threat | 5% | 90% | 61 |
| Worker outside approved hours | threat | 0% | 100% | 100 |
| Worker enters restricted room | threat | 5% | 100% | 48 |
| Worker arrives, child alone | threat | 14% | 90% | 38 |
| Stranger, child home alone | threat | 95% | 95% | 68 |
| Entry outside camera view | threat | 0% | 89% | 40 |
| Unknown visitor at night | threat | 100% | 88% | 51 |

## Cooldown grouping

Naive per-frame alerts: **1788** -> grouped: **257** (86% fewer notifications).

## Assumptions

- Synthetic scenarios with injected recognition noise (4% false-reject, 1% false-accept, 5% sensor dropout).
- System A judges only the primary face: recognised -> safe, unrecognised -> alert.
- An 'alert' for System B is any frame at MEDIUM risk or above (score >= 30).
- Ground truth is defined by the scenario design/protocol; replace with real labelled trials for publication.
