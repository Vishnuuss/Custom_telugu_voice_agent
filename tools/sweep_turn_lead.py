"""How early can the turn detector decide?

The question this answers
--------------------------
Run 262's fast path is a hard floor at 0.403s, identical on every turn that hit
it. That is not a decision, it is an accumulation: VAD reports its stop after
0.2s of silence, and only then does the analyzer's own 120ms silence counter
begin -- so it waits for silence it has already had.

The obvious fix is to let it decide at the VAD stop instead. It already tries,
and returns INCOMPLETE, and the reason is in the training data rather than the
code: positive windows were cut ending at the moment the FINAL TRANSCRIPT
ARRIVED, which is several hundred milliseconds after the caller actually stopped.
The model was therefore taught that "finished" looks like a phrase followed by a
long tail of silence. Asked to judge before that tail exists, it correctly says
it has not seen one.

So the real question is not "can we lower a constant" but "how much of that tail
does the model actually need?" This sweeps it.

Method
------
For each lead L, positives are re-cut to end L seconds EARLIER than the
transcript arrival -- i.e. the model is asked to commit L seconds sooner.
Negatives stay where they were, mid-utterance. Everything else is held fixed:
same calls, same features, same model, same 2% false-cutoff bar, same split by
CALL rather than by clip.

Read the result as a trade curve, not a winner. A larger lead is worth real
milliseconds on every turn, and costs recall -- fewer turns end early. The two
have to be multiplied out against the measured 0.403s / 0.874s split before
choosing.

    python tools/sweep_turn_lead.py
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import GroupShuffleSplit

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
DOGRAH = REPO.parent / "dograh-vapi"
sys.path.insert(0, str(DOGRAH))

from api.services.vaani.telugu_turn import extract_features  # noqa: E402

SR = 8000
WINDOW_S = 1.5
MIN_NEG_OFFSET = 0.6
MAX_FALSE_CUTOFF = 0.02


def read_wav(path: Path):
    with wave.open(str(path)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            return None, 0
        return w.readframes(w.getnframes()), w.getframerate()


def slice_ending_at(frames: bytes, rate: int, end_s: float):
    end = int(end_s * rate) * 2
    start = end - int(WINDOW_S * rate) * 2
    if start < 0 or end > len(frames):
        return None
    return np.frombuffer(frames[start:end], dtype=np.int16).astype(np.float32) / 32768.0


def turn_ends(run: dict):
    events = (run.get("logs") or {}).get("realtime_feedback_events") or []
    if not events:
        return []

    def ts(x):
        return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()

    try:
        t0 = ts(events[0].get("timestamp"))
    except Exception:
        return []
    out = []
    for e in events:
        if e.get("type") != "rtf-user-transcription":
            continue
        p = e.get("payload") or {}
        if not p.get("final"):
            continue
        try:
            start = ts(p.get("timestamp")) - t0
            end = ts(p.get("end_timestamp") or e.get("timestamp")) - t0
        except Exception:
            continue
        if end > start >= 0:
            out.append((start, end))
    return out


def build(lead: float, audio_dir: Path, runs_dir: Path, limit: int | None):
    X, y, groups = [], [], []
    wavs = sorted(audio_dir.glob("*.wav"))
    if limit:
        wavs = wavs[:limit]
    for wav in wavs:
        try:
            wf, run_id = wav.stem.split("_run")
        except ValueError:
            continue
        meta = runs_dir / f"{wf.replace('wf', '')}_{run_id}.json"
        if not meta.exists():
            continue
        try:
            run = json.loads(meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        turns = turn_ends(run)
        if not turns:
            continue
        frames, rate = read_wav(wav)
        if not frames or rate != SR:
            continue
        for start, end in turns:
            # POSITIVE, pulled `lead` seconds earlier than the transcript.
            clip = slice_ending_at(frames, rate, end - lead)
            if clip is not None:
                f = extract_features(clip, rate)
                if f:
                    X.append(f); y.append(1); groups.append(run_id)
            # NEGATIVE, unchanged: genuinely mid-utterance.
            if end - start > WINDOW_S + MIN_NEG_OFFSET:
                clip = slice_ending_at(frames, rate, end - MIN_NEG_OFFSET)
                if clip is not None:
                    f = extract_features(clip, rate)
                    if f:
                        X.append(f); y.append(0); groups.append(run_id)
    return (np.asarray(X, dtype=np.float32), np.asarray(y), np.asarray(groups))


def evaluate(X, y, groups, seed: int):
    if (y == 0).sum() < 60 or (y == 1).sum() < 60:
        return None
    tr, te = next(GroupShuffleSplit(n_splits=1, test_size=0.25,
                                    random_state=seed).split(X, y, groups))
    clf = GradientBoostingClassifier(n_estimators=250, max_depth=3,
                                     learning_rate=0.06, subsample=0.85,
                                     random_state=seed)
    clf.fit(X[tr], y[tr])
    p = clf.predict_proba(X[te])[:, 1]
    yt = y[te]
    mid, end = p[yt == 0], p[yt == 1]
    for t in np.arange(0.50, 1.00, 0.01):
        if float((mid >= t).mean()) <= MAX_FALSE_CUTOFF:
            return {"threshold": float(t),
                    "false_cutoffs": float((mid >= t).mean()),
                    "recall": float((end >= t).mean()),
                    "n": int(len(te))}
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default=".tmp/audio/caller")
    ap.add_argument("--runs", default=".tmp/harvest/runs")
    ap.add_argument("--leads", default="0.0,0.15,0.3,0.45")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    # Measured on run 262: what a turn costs when the detector fires, and when
    # it does not and the timer runs instead.
    FAST, SLOW = 0.403, 0.874

    print(f"{'lead':>6} {'thr':>6} {'false':>7} {'recall':>8} {'fast path':>10} "
          f"{'mean endpoint':>14}")
    best = None
    for lead in [float(x) for x in a.leads.split(",")]:
        X, y, groups = build(lead, Path(a.audio), Path(a.runs), a.limit)
        r = evaluate(X, y, groups, a.seed)
        if r is None:
            print(f"{lead:>6.2f}   no threshold holds the 2% bar")
            continue
        # Deciding `lead` earlier makes the fast path that much shorter.
        fast = max(0.05, FAST - lead)
        mean = r["recall"] * fast + (1 - r["recall"]) * SLOW
        print(f"{lead:>6.2f} {r['threshold']:>6.2f} {r['false_cutoffs']:>6.1%} "
              f"{r['recall']:>7.1%} {fast:>9.3f}s {mean:>13.3f}s")
        if best is None or mean < best[1]:
            best = (lead, mean, r)

    if best:
        lead, mean, r = best
        print(f"\nbest: decide {lead:.2f}s earlier -> mean endpoint {mean:.3f}s "
              f"(today 0.722s), recall {r['recall']:.1%}, "
              f"false cutoffs {r['false_cutoffs']:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
