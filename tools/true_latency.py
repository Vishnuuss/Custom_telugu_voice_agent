"""Measure what the caller actually waits, from the audio.

Why the run log is not enough
------------------------------
`rtf-latency-measured` reports TOTAL, and on every turn of run 273 that total
equals endpoint+STT plus the LLM exactly, to three decimals. Nothing else is in
it. Cartesia emits no TTFB metric at all -- the only `rtf-ttfb-metric` rows on
any call come from the LLM -- so the time between the model's first token and
the first sound leaving the line is absent from the number everyone has been
quoting, this project included.

So this ignores the logs and measures the two recordings: the moment the caller
stops speaking, and the moment the agent's voice starts. That gap is the whole
thing the caller experiences, TTS and network included.

Method
------
Both tracks are separated already (user.wav, bot.wav, same clock, same length).
Speech regions are found by energy on each, then for every caller region the
next agent region is located and the gap between them measured.

Deliberately conservative: a gap is only counted when the agent starts AFTER the
caller stops and within 6 seconds, so barge-in and long silences do not enter
the statistic and quietly flatter it.

    python tools/true_latency.py --runs 262,269,272,273
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import urllib.request
import wave
from pathlib import Path

import numpy as np

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

FRAME_S = 0.02
MAX_GAP_S = 6.0          # beyond this the caller was not waiting for a reply
MIN_REGION_S = 0.10      # shorter than this is a click, not speech


def load(url: str, path: Path) -> tuple[np.ndarray, int]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, path)
    with wave.open(str(path)) as w:
        return (np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
                .astype(np.float32), w.getframerate())


def regions(x: np.ndarray, sr: int) -> list[tuple[float, float]]:
    """(start, end) of each speech burst, in seconds."""
    fr = int(sr * FRAME_S)
    e = np.array([float(np.sqrt((x[i:i + fr] ** 2).mean()))
                  for i in range(0, len(x) - fr, fr)])
    if not len(e):
        return []
    # Relative to the track's own loudness, so the two sides are treated alike
    # regardless of line level.
    thr = float(np.percentile(e, 75)) * 0.35
    out, start, gap = [], None, 0
    for i, loud in enumerate(e > thr):
        if loud:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            # 0.30s of quiet ends a burst: shorter than a turn gap, longer than
            # the pauses inside one sentence.
            if gap >= 15:
                out.append((start * FRAME_S, (i - gap) * FRAME_S))
                start = None
    if start is not None:
        out.append((start * FRAME_S, (len(e) - 1) * FRAME_S))
    return [(a, b) for a, b in out if b - a >= MIN_REGION_S]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="262,269,272,273")
    ap.add_argument("--workflow", type=int, default=2)
    a = ap.parse_args()

    import vaani_runs as V

    print(f"{'run':>5} {'turns':>6} {'p50':>8} {'p90':>8} {'min':>8} {'max':>8}")
    everything: list[float] = []
    for rid in [int(x) for x in a.runs.split(",")]:
        r = V.get(f"/api/v1/workflow/{a.workflow}/runs/{rid}")
        u, b = r.get("user_recording_public_url"), r.get("bot_recording_public_url")
        if not (u and b):
            print(f"{rid:>5}   no separated recordings")
            continue
        src = REPO / ".tmp" / "fillersrc"
        ux, sr = load(u, src / f"user{rid}.wav")
        bx, _ = load(b, src / f"bot{rid}.wav")

        caller, agent = regions(ux, sr), regions(bx, sr)
        gaps = []
        for _, c_end in caller:
            nxt = [s for s, _ in agent if s > c_end]
            if not nxt:
                continue
            gap = nxt[0] - c_end
            if 0 < gap <= MAX_GAP_S:
                gaps.append(gap)
        if not gaps:
            print(f"{rid:>5}   no measurable turn gaps")
            continue
        everything += gaps
        srt = sorted(gaps)
        p90 = srt[int(0.9 * (len(srt) - 1))]
        print(f"{rid:>5} {len(gaps):>6} {st.median(gaps):>7.3f}s {p90:>7.3f}s "
              f"{min(gaps):>7.3f}s {max(gaps):>7.3f}s")

    if everything:
        srt = sorted(everything)
        print(f"\n  across {len(everything)} turns of real audio:")
        print(f"    p50 {st.median(everything):.3f}s"
              f"    p90 {srt[int(0.9*(len(srt)-1))]:.3f}s"
              f"    worst {max(everything):.3f}s")
        print(f"    under 0.7s: {sum(1 for g in everything if g <= 0.7)}"
              f"/{len(everything)} turns")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
