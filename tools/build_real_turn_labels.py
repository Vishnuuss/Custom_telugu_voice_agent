#!/usr/bin/env python
"""Label turn ends from the AUDIO, so the detector stops learning its own mistakes.

The defect this exists to fix
-----------------------------
`vaani_harvest.py:186` writes `"was_turn_end": True` on every row it emits, and
`train_turn_detector.py` says so in its own docstring: 2,754 positives and ZERO
negatives, with negatives then generated as prefixes of the positives.

Two consequences, and they explain the client's complaint completely:

1. Every label came from a moment the DEPLOYED SYSTEM decided was a turn end.
   Where it was wrong, the mistake became a lesson. The model was trained to
   reproduce the cut-offs it is now blamed for.

2. The positives include "ఆ." and "హలో." -- a thinking sound and a hello, both
   taught as complete turns. Run 819's caller said "ఆ" before each sentence and
   was answered every single time. The model was doing what it was taught.

Where the truth actually is
---------------------------
Not in the logs. Final transcripts arrive after the fact, with the bot's reply
between them, so consecutive transcripts are 4.45s apart at the median and only
2% fall inside a second -- against the 33% of speech bursts the same recordings
show being cut off. The logs cannot see a caller restarting inside one utterance.

The audio can. If the caller starts again within RESUME_WINDOW_S of us ending his
turn, we did not end it -- we interrupted it. That is the same rule the live
analyzer already applies to adapt to a caller, promoted here to a training label:

    burst followed by another within 1.0s   ->  INCOMPLETE   (a real negative)
    burst followed by a longer gap          ->  COMPLETE

The negatives are then REAL mid-thought pauses from real Telugu callers, not
prefixes cut at a clause boundary and hoped to be wrong-sounding.

    python tools/build_real_turn_labels.py --limit 651
"""
from __future__ import annotations

import argparse, importlib.util, json, sys, wave
from pathlib import Path

import numpy as np

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.parent / "dograh-vapi"))
_spec = importlib.util.spec_from_file_location("rt", REPO / "tools" / "replay_turns.py")
RT = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(RT)

import api.services.vaani.telugu_turn as tt

CALLER = REPO / ".tmp" / "audio" / "caller"
RUNS = REPO / ".tmp" / "harvest" / "runs"
OUT = REPO / ".tmp" / "harvest" / "turnstops_real.jsonl"

# The analyzer reads this much of the tail when it scores a turn, so a training
# window must be cut the same way or the features mean something different.
WINDOW_S = tt.WINDOW_S


def text_for(said, start, end):
    """The transcript covering this burst, if one arrived near it."""
    best, gap = "", 9e9
    for t, txt in said:
        d = abs(t - end)
        if d < gap:
            best, gap = txt, d
    return best if gap < 5.0 else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=651)
    a = ap.parse_args()

    rows, files = [], 0
    for wav in sorted(CALLER.glob("*.wav"))[: a.limit]:
        try:
            wf, rid = wav.stem.split("_run")
        except ValueError:
            continue
        log = RUNS / f"{wf[2:]}_{rid}.json"
        if not log.exists():
            continue
        try:
            with wave.open(str(wav)) as w:
                sr = w.getframerate()
                pcm = w.readframes(w.getnframes())
            x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
            regions, _ = RT.speech_latch(x, sr, RT._load_tool("true_latency").regions)
            said = RT.transcripts(json.loads(log.read_text(encoding="utf-8")))
        except Exception:
            continue
        files += 1
        for i, (s, e) in enumerate(regions):
            nxt = regions[i + 1][0] if i + 1 < len(regions) else None
            resumed = nxt is not None and (nxt - e) < tt.RESUME_WINDOW_S
            lo = max(0, int((e - WINDOW_S) * sr))
            hi = int(e * sr)
            if hi - lo < int(0.2 * sr):
                continue
            rows.append({
                "run": rid, "workflow": wf[2:],
                "start": round(s, 3), "end": round(e, 3),
                "speech_secs": round(e - s, 3),
                "gap_after": round(nxt - e, 3) if nxt is not None else None,
                "text": text_for(said, s, e),
                # THE label. False means the caller carried on talking.
                "was_turn_end": not resumed,
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    pos = sum(1 for r in rows if r["was_turn_end"])
    neg = len(rows) - pos
    print(f"{files} recordings -> {len(rows)} labelled bursts")
    print(f"  COMPLETE   {pos:5}  ({100*pos/max(1,len(rows)):.1f}%)")
    print(f"  INCOMPLETE {neg:5}  ({100*neg/max(1,len(rows)):.1f}%)   <- REAL negatives")
    print(f"  -> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
