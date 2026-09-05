"""What the two-sided endpointing window actually costs, on real recordings.

Why this has to be measured
---------------------------
Holding a turn open is not free. Every turn the model is only half-sure about
now waits longer than the flat 0.2s it used to, and "half-sure" could easily be
most of them -- in which case the fix for interruptions would quietly hand back
the whole latency budget, and the first anyone would know is a call that felt
slow. The claim "p50 is unaffected" is not one to make from the shape of a
formula.

So the shipped forest is scored on the same 1,393 labelled clips it was trained
and validated on, and the new wait is computed for each. Two numbers come out,
and they are the trade in full:

    on turn_end clips   how much later a caller who HAD finished is answered
    on mid_turn clips   how many callers who had NOT finished are now let finish

    python tools/measure_endpoint_cost.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / "dograh-vapi"))

from api.services.vaani.telugu_turn import (  # noqa: E402
    MIN_CONFIDENT_TURN_S,
    SHORT_TURN_THRESHOLD,
    TeluguTurnAnalyzer,
    TeluguTurnParams,
    extract_features,
)

INDEX = Path(".tmp/audio/dataset/index.jsonl")
OLD_WAIT = 0.2          # the flat analyzer timeout being replaced
# Read from the shipped params rather than restated, so this tool cannot drift
# away from the analyzer it is measuring. It did once: the numbers in the 29 Aug
# report were computed against constants that the code had already moved past.
_P = TeluguTurnParams()
MIN_S = _P.min_endpoint_secs
MAX_S = _P.max_endpoint_secs
FLOOR_S = _P.fragment_floor_secs
UNSURE_FLOOR = _P.unsure_floor_secs
UNSURE_BAND = _P.unsure_band


def load(path: str):
    import wave
    try:
        with wave.open(path, "rb") as w:
            sr = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    except Exception:
        return None, 0
    return x.astype(np.float32) / 32768.0, sr


def wait_for(p: float, secs: float, threshold: float,
             band: float = UNSURE_BAND) -> float:
    """`TeluguTurnAnalyzer._wait_secs`, with no text signal available here.

    Text is deliberately left out: these clips carry no transcript, so this
    reports the audio-only half of the decision. The text floor can only ever
    ADD holding, so the mid-turn benefit below is a floor, not a ceiling.
    """
    bar = max(threshold, SHORT_TURN_THRESHOLD) if secs < MIN_CONFIDENT_TURN_S else threshold
    if p >= bar:
        return 0.0                       # ends early; the analyzer never waits
    frac = min(1.0, max(0.0, p / bar))
    wait = MAX_S - frac * (MAX_S - MIN_S)
    if secs < MIN_CONFIDENT_TURN_S:
        wait = max(wait, FLOOR_S)
    elif frac < band:
        # The long-answer floor. Gated on the model still being unsure, which
        # is what keeps the p50 where it was.
        wait = max(wait, UNSURE_FLOOR)
    return min(wait, MAX_S)


def main() -> int:
    rows = [json.loads(x) for x in INDEX.read_text(encoding="utf-8").splitlines() if x.strip()]
    a = TeluguTurnAnalyzer(params=TeluguTurnParams())
    if a._forest is None:
        print("no forest exported; nothing to measure")
        return 1
    threshold = a.params.threshold

    ends, mids = [], []
    for r in rows:
        x, sr = load(r["path"])
        if x is None or sr == 0:
            continue
        f = extract_features(x, sr)
        if f is None:
            continue
        p = a._forest.probability(np.asarray(f, dtype=np.float64))
        secs = len(x) / sr
        (ends if r["label"] == 1 else mids).append((p, secs))

    def report(name, rows_, band=UNSURE_BAND):
        if not rows_:
            print(f"{name}: no clips"); return
        waits = np.array([wait_for(p, s, threshold, band) for p, s in rows_])
        early = float((waits == 0.0).mean())
        delta = waits - OLD_WAIT
        print(f"\n{name}  n={len(rows_)}")
        print(f"  ends early on the model's verdict : {early*100:5.1f}%")
        print(f"  wait p50 / p90 / max             : "
              f"{np.percentile(waits,50):.3f} / {np.percentile(waits,90):.3f} / {waits.max():.3f} s")
        print(f"  change vs the flat {OLD_WAIT}s       : "
              f"p50 {np.percentile(delta,50):+.3f}s   mean {delta.mean():+.3f}s")
        print(f"  held longer than before          : {float((waits>OLD_WAIT).mean())*100:5.1f}%")

    print(f"forest threshold {threshold:.3f}")
    report("turn_end   (caller HAD finished -- cost)", ends)
    report("mid_turn   (caller had NOT finished -- benefit)", mids)

    # And the same two, for a caller this agent has already talked over twice.
    #
    # `TeluguTurnAnalyzer._band()` returns 1.0 for him, so the unsure floor
    # stops being conditional and applies to every one of his turns. Reported
    # separately because it is a DIFFERENT trade, deliberately taken only for
    # the callers who have shown they need it -- a call where nobody is
    # interrupted never reaches this column at all.
    print()
    print("=" * 62)
    print("AFTER WE HAVE CUT THIS CALLER OFF TWICE  (band 0.95 -> 1.0)")
    print("=" * 62)
    report("turn_end   (cost, for him only)", ends, band=1.0)
    report("mid_turn   (benefit, for him only)", mids, band=1.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
