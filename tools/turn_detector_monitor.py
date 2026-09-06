#!/usr/bin/env python
"""How the DEPLOYED turn detector is doing on real calls.

The gap this fills
------------------
`train_turn_detector.py` scores a candidate on a held-out split of harvested
utterances, and it scores the right thing -- false cutoffs, not accuracy. But
that is a laboratory number, measured against synthetic negatives (prefixes of
complete utterances) on data the model was tuned against.

Nothing measured the model in PRODUCTION. The deployed artifact
(`api/services/vaani/models/audio_turn_gbm.json`) stores only its trees, its
learning rate and its threshold -- no metrics, no dataset version, no date. So
"is the detector actually good on live Telugu calls" had no answer at all.

The signal, and why it is honest
--------------------------------
`telugu_turn.py` already defines it internally:

    RESUME_WINDOW_S = 1.0
    "If the caller starts talking again this soon after we ended his turn, we
     did not end it -- we interrupted it. Nobody answers a question, hears the
     reply begin, and starts a fresh sentence inside a second; a resume that
     fast is the back half of the sentence we cut in two."

That rule runs live, per caller, to adapt the threshold. This reads the same
event out of the call log afterwards and counts it across every call, which
turns a per-caller heuristic into a fleet metric.

    CUT OFF        caller speaks again < 1.0s after the agent started
    SLOW           agent took > 0.6s of endpoint to decide the turn had ended

The two failures point opposite ways and that is the whole point: a detector
tuned to stop cutting people off gets slower, and one tuned for speed cuts
people off. A single accuracy number hides the trade; these two do not.

Deliberately conservative
-------------------------
A resume inside the window is *evidence* of a cutoff, not proof -- a caller may
genuinely interject. So this reports a RATE to watch over time, and never
relabels training data on its own. Feeding a model its own guesses back as
truth is how a dataset rots.

    python tools/turn_detector_monitor.py
    python tools/turn_detector_monitor.py --workflows 2 3 --calls 20
"""
from __future__ import annotations

import argparse
import importlib.util
import statistics
import sys
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vr", REPO / "tools" / "vaani_runs.py")
vr = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]
spec.loader.exec_module(vr)

# From telugu_turn.RESUME_WINDOW_S. Kept in sync by hand; if that constant
# moves, this number must move with it or the metric stops meaning the same
# thing as the rule it is measuring.
RESUME_WINDOW_S = 1.0
# The endpoint budget in latency_budget.yaml is 250ms; 600ms is the point past
# which the caller is audibly waiting, and is the floor the budget file names
# for Telugu without a detector.
SLOW_ENDPOINT_S = 0.6


def _ts(value: str) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def analyse(det: dict) -> dict | None:
    """Per-call detector behaviour, or None when the call is too short to judge."""
    events = (det.get("logs") or {}).get("realtime_feedback_events") or []

    bot_starts: list[float] = []
    user_starts: list[float] = []
    for e in events:
        kind = e.get("type") or ""
        payload = e.get("payload") or {}
        stamp = _ts(e.get("timestamp") or "")
        if stamp is None:
            continue
        if kind == "rtf-bot-text":
            bot_starts.append(stamp)
        elif kind == "rtf-user-transcription" and payload.get("final"):
            user_starts.append(_ts(payload.get("timestamp") or "") or stamp)

    if len(bot_starts) < 2:
        return None

    # A cutoff is the caller resuming inside the window after the agent began.
    cutoffs = 0
    for started in bot_starts:
        if any(0 < (u - started) < RESUME_WINDOW_S for u in user_starts):
            cutoffs += 1

    rows, _ = vr.decompose(det)
    endpoints = [r[1] for r in rows if r[1] is not None]
    slow = [e for e in endpoints if e > SLOW_ENDPOINT_S]

    return {
        "turns": len(bot_starts),
        "cutoffs": cutoffs,
        "cutoff_rate": cutoffs / len(bot_starts),
        "endpoint_p50": statistics.median(endpoints) if endpoints else None,
        "slow": len(slow),
        "slow_rate": (len(slow) / len(endpoints)) if endpoints else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflows", type=int, nargs="*", default=[2, 3, 4, 5, 6])
    ap.add_argument("--calls", type=int, default=30)
    a = ap.parse_args()

    calls = []
    for wf in a.workflows:
        try:
            listing = vr.get(f"/api/v1/workflow/{wf}/runs?page=1&limit={a.calls}")
        except Exception as e:
            print(f"wf{wf}: listing failed: {e}")
            continue
        runs = listing if isinstance(listing, list) else listing.get(
            "runs", listing.get("items", []))
        for r in runs:
            if (r.get("mode") or "") == "textchat":
                continue          # no audio, no turn detection to measure
            try:
                det = vr.get(f"/api/v1/workflow/{wf}/runs/{r.get('id')}")
            except Exception:
                continue
            row = analyse(det)
            if row:
                row.update(wf=wf, run=r.get("id"),
                           when=(det.get("created_at") or "")[:16])
                calls.append(row)

    if not calls:
        print("no measurable telephony calls found")
        return 1

    calls.sort(key=lambda c: c["when"])
    print(f"\n{'when':17} {'wf':>3} {'run':>5} {'turns':>6} {'cutoffs':>8} "
          f"{'cut%':>6} {'endp p50':>9} {'slow%':>6}")
    print("-" * 72)
    for c in calls:
        ep = f"{c['endpoint_p50']:.3f}" if c["endpoint_p50"] is not None else "  -  "
        sr = f"{c['slow_rate']:.0%}" if c["slow_rate"] is not None else "  -  "
        print(f"{c['when']:17} {c['wf']:>3} {c['run']:>5} {c['turns']:>6} "
              f"{c['cutoffs']:>8} {c['cutoff_rate']:>5.0%} {ep:>9} {sr:>6}")

    turns = sum(c["turns"] for c in calls)
    cuts = sum(c["cutoffs"] for c in calls)
    eps = [c["endpoint_p50"] for c in calls if c["endpoint_p50"] is not None]
    print("-" * 72)
    print(f"{len(calls)} calls, {turns} turns")
    print(f"  cutoff rate      {cuts / turns:.1%}   "
          f"({cuts}/{turns})   target < 2%")
    if eps:
        print(f"  endpoint p50     {statistics.median(eps):.3f}s   budget 0.250s")
    print("\n  A resume inside 1.0s is EVIDENCE of a cutoff, not proof -- a caller")
    print("  may genuinely interject. Watch the rate over time; never relabel")
    print("  training data from it. A model fed its own guesses as truth rots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
