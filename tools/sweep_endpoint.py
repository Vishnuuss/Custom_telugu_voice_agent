#!/usr/bin/env python
"""The trade curve between cutting the caller off and making him wait.

Measured on the 6 Sep baseline: 35.9% of speech bursts cut off against a 2%
target, at a wait of 0.30s. The client's complaint, in one number.

The two failures point in opposite directions and one number cannot show a
trade-off, so both are always printed. A setting that halves cut-offs and
doubles the wait has moved the problem, not fixed it.

    python tools/sweep_endpoint.py --limit 120
"""
from __future__ import annotations

import argparse, importlib.util, statistics, sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.parent / "dograh-vapi"))
spec = importlib.util.spec_from_file_location("replay_turns", REPO / "tools" / "replay_turns.py")
RT = importlib.util.module_from_spec(spec); spec.loader.exec_module(RT)

import api.services.vaani.telugu_turn as tt

# name -> the parameters that differ from the shipped defaults.
GRID = {
    "SHIPPED (6 Sep)":        {},
    "unsure_floor 0.50":      {"unsure_floor_secs": 0.50},
    "unsure_floor 0.80":      {"unsure_floor_secs": 0.80},
    "fragment_floor 0.80":    {"fragment_floor_secs": 0.80},
    "min_endpoint 0.30":      {"min_endpoint_secs": 0.30},
    "min_endpoint 0.50":      {"min_endpoint_secs": 0.50},
    "threshold 0.99":         {"threshold": 0.99},
    "band 1.0 (floor always)": {"unsure_band": 1.0},
    "band 1.0 + floor 0.50":  {"unsure_band": 1.0, "unsure_floor_secs": 0.50},
    "band 1.0 + floor 0.80":  {"unsure_band": 1.0, "unsure_floor_secs": 0.80},
    # The blind-turn gate: only turns whose transcript has NOT arrived are
    # slowed. Measured 6 Sep: that is 68.8% of decisions, and it is where the
    # cut-offs are, because stale text from a finished sentence reads as
    # complete and leaves the immediate path open.
    "blind gate 250ms":       {"blind_min_silence_ms": 250},
    "blind gate 400ms":       {"blind_min_silence_ms": 400},
    "blind gate 600ms":       {"blind_min_silence_ms": 600},
    "blind gate 800ms":       {"blind_min_silence_ms": 800},
}


def _run_for(wav: Path):
    """The cached run log beside a caller recording. Same rule as replay_turns."""
    import json
    try:
        wf, rid = wav.stem.split("_run")           # wf<W>_run<R>
    except ValueError:
        return None
    log = REPO / ".tmp" / "harvest" / "runs" / f"{wf[2:]}_{rid}.json"
    if not log.exists():
        return None
    return json.loads(log.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    a = ap.parse_args()

    calls = sorted((REPO / ".tmp" / "audio" / "caller").glob("*.wav"))[: a.limit]
    print(f"\n{len(calls)} recordings\n")
    print(f"{'setting':26} {'bursts':>7} {'CUT OFF':>16} {'wait p50':>9} "
          f"{'wait p90':>9} {'slow':>6}")
    print("-" * 80)

    for name, overrides in GRID.items():
        params = tt.TeluguTurnParams(**overrides)
        bursts = cut = slow = 0
        waits: list[float] = []
        for wav in calls:
            run = _run_for(wav)
            if run is None:
                continue
            try:
                r = RT.replay(wav, run, params=params)
            except Exception:
                continue
            if r.get("error"):
                continue
            bursts += r.get("bursts", 0)
            cut += r.get("cutoffs", 0)
            slow += r.get("slow", 0)
            waits.extend(r.get("waits", []))
        pct = 100.0 * cut / bursts if bursts else 0.0
        p50 = statistics.median(waits) if waits else 0.0
        p90 = (sorted(waits)[int(len(waits) * 0.9)] if len(waits) > 9 else p50)
        print(f"{name:26} {bursts:>7} {cut:>6} ({pct:>5.1f}%) {p50:>9.2f} "
              f"{p90:>9.2f} {slow:>6}")

    print("\nA row is only better if CUT OFF falls AND the waits do not climb.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
