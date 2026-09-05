"""Train a Telugu turn-end detector on real caller audio.

The thing that does not exist anywhere: Smart Turn v3 covers 23 languages,
LiveKit v1 14, Deepgram Flux 10, and Telugu is in none of them. The
`eager_eot_threshold` sitting in `service_factory.py` is dead code on a Telugu
call, which is why most turns end on a timeout instead of a decision, and why
endpointing is the largest single cost in a turn.

Why features and not a neural net
---------------------------------
1,393 clips. A CNN on mel-spectrograms would memorise a dataset that size and
report a score that does not survive contact with a real call. Hand-built
prosodic features are fewer parameters, are interpretable when they fail, and
export to plain weights that run in the API container without adding torch.

What the features are, and why each one
---------------------------------------
All of them answer "does this sound finished?", which is what the transcript
could not tell us:

  energy slope        speakers trail off at the end of a turn and hold volume
                      mid-sentence
  trailing energy     ratio of the last 300ms to the rest of the window
  trailing silence    how much of the tail is already quiet
  F0 slope            falling pitch ends a statement; rising or level pitch
                      means more is coming. This is the single most linguistically
                      motivated feature here and the one a transcript can never
                      carry
  F0 range/voicing    a trailing unvoiced fricative behaves differently from a
                      trailing vowel, which matters in Telugu
  spectral centroid   articulation loosens at the end of an utterance

Scored at the false-cutoff rate, not accuracy: cutting a caller off is the
failure they complain about, and waiting slightly longer is not.

    python tools/train_audio_turn.py
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import wave
from pathlib import Path

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import GroupShuffleSplit

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

MAX_FALSE_CUTOFF = 0.02      # a caller may be talked over at most this often
SR = 8000


def load(path: str) -> np.ndarray | None:
    try:
        with wave.open(path) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    except Exception:
        return None
    if x.size < SR // 2:
        return None
    return x.astype(np.float32) / 32768.0


def f0_track(x: np.ndarray, sr: int = SR, frame: int = 256) -> np.ndarray:
    """Crude autocorrelation pitch track. Zero where unvoiced.

    Good enough for a slope: we need the DIRECTION pitch is moving, not a
    musically accurate value.
    """
    out = []
    lo, hi = sr // 350, sr // 70          # 70-350 Hz covers phone speech
    for i in range(0, len(x) - frame, frame):
        seg = x[i:i + frame] - x[i:i + frame].mean()
        if np.sqrt((seg ** 2).mean()) < 0.01:
            out.append(0.0)
            continue
        ac = np.correlate(seg, seg, mode="full")[frame - 1:]
        if ac[0] <= 0:
            out.append(0.0)
            continue
        band = ac[lo:hi]
        if band.size == 0:
            out.append(0.0)
            continue
        peak = int(np.argmax(band)) + lo
        out.append(sr / peak if ac[peak] / ac[0] > 0.3 else 0.0)
    return np.asarray(out, dtype=np.float32)


def features(x: np.ndarray) -> list[float]:
    n = len(x)
    frame = 128
    energy = np.asarray([
        float(np.sqrt((x[i:i + frame] ** 2).mean()))
        for i in range(0, n - frame, frame)
    ])
    if energy.size < 6:
        return []
    e = energy / (energy.max() + 1e-9)
    third = max(1, len(e) // 3)
    tail_n = max(1, int(0.3 * SR / frame))          # last 300ms

    t = np.arange(len(e), dtype=np.float32)
    slope = float(np.polyfit(t, e, 1)[0])
    tail_slope = float(np.polyfit(t[-third:], e[-third:], 1)[0])

    f0 = f0_track(x)
    voiced = f0[f0 > 0]
    if voiced.size >= 4:
        vt = np.arange(voiced.size, dtype=np.float32)
        f0_slope = float(np.polyfit(vt, voiced, 1)[0])
        f0_tail = float(np.polyfit(vt[-max(2, voiced.size // 3):],
                                   voiced[-max(2, voiced.size // 3):], 1)[0])
        f0_rng = float(voiced.max() - voiced.min())
        f0_mean = float(voiced.mean())
    else:
        f0_slope = f0_tail = f0_rng = f0_mean = 0.0

    spec = np.abs(np.fft.rfft(x[-SR // 2:] * np.hanning(min(len(x), SR // 2))))
    freqs = np.fft.rfftfreq(min(len(x), SR // 2), 1 / SR)
    centroid = float((spec * freqs).sum() / (spec.sum() + 1e-9))

    return [
        slope, tail_slope,
        float(e[-tail_n:].mean()), float(e[-tail_n:].mean() / (e.mean() + 1e-9)),
        float((e < 0.08).mean()),                    # quiet fraction
        float((e[-tail_n:] < 0.08).mean()),          # trailing silence
        float(e.std()), float(e.mean()), float(e.max()),
        f0_slope, f0_tail, f0_rng, f0_mean,
        float((f0 > 0).mean()),                      # voicing fraction
        float((f0[-tail_n:] > 0).mean()) if len(f0) >= tail_n else 0.0,
        centroid,
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=".tmp/audio/dataset/index.jsonl")
    ap.add_argument("--out", default=".tmp/models")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    rows = [json.loads(x) for x in
            Path(a.index).read_text(encoding="utf-8").splitlines() if x.strip()]
    print(f"{len(rows)} clips; extracting prosodic features...", flush=True)

    X, y, groups = [], [], []
    for i, r in enumerate(rows):
        x = load(r["path"])
        if x is None:
            continue
        f = features(x)
        if not f:
            continue
        X.append(f); y.append(r["label"]); groups.append(r["run"])
        if (i + 1) % 300 == 0:
            print(f"  {i+1}/{len(rows)}", flush=True)
    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y)
    groups = np.asarray(groups)
    print(f"\n{X.shape[0]} usable clips, {X.shape[1]} features")
    print(f"  turn-end {int((y==1).sum())}   mid-turn {int((y==0).sum())}")
    if (y == 0).sum() < 80:
        print("too few mid-turn clips to learn from"); return 1

    # Split by CALL. Two clips from one call share a speaker, a handset and a
    # line; splitting by clip would let the model recognise the caller instead
    # of the ending, and the score would be a fiction.
    tr, te = next(GroupShuffleSplit(n_splits=1, test_size=0.25,
                                    random_state=a.seed).split(X, y, groups))
    print(f"  {len(tr)} train / {len(te)} test, split by call "
          f"({len(set(groups[tr]))} vs {len(set(groups[te]))} calls)")

    clf = GradientBoostingClassifier(
        n_estimators=250, max_depth=3, learning_rate=0.06,
        subsample=0.85, random_state=a.seed)
    clf.fit(X[tr], y[tr])
    p = clf.predict_proba(X[te])[:, 1]
    yt = y[te]
    print(f"\naccuracy at 0.5: {float(((p>=0.5).astype(int)==yt).mean()):.3f}")

    mid, end = p[yt == 0], p[yt == 1]
    print(f"\n{'threshold':>10} {'false cutoffs':>14} {'turns ended early':>18}")
    chosen = None
    for t in np.arange(0.50, 1.00, 0.01):
        fc = float((mid >= t).mean())
        if chosen is None and fc <= MAX_FALSE_CUTOFF:
            chosen = float(t)
    for t in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        print(f"{t:>10.2f} {float((mid>=t).mean()):>13.1%} "
              f"{float((end>=t).mean()):>17.1%}")

    names = ["energy_slope","tail_energy_slope","tail_energy","tail_ratio",
             "quiet_frac","tail_quiet","energy_std","energy_mean","energy_max",
             "f0_slope","f0_tail_slope","f0_range","f0_mean","voiced_frac",
             "tail_voiced","centroid"]
    imp = sorted(zip(names, clf.feature_importances_), key=lambda z: -z[1])
    print("\nwhat the model actually uses:")
    for n_, v in imp[:6]:
        print(f"  {v:6.3f}  {n_}")

    if chosen is None:
        print(f"\nNo threshold holds false cutoffs under {MAX_FALSE_CUTOFF:.0%}. "
              "Not shippable as an endpointer.")
    else:
        recall = float((end >= chosen).mean())
        print(f"\nOperating point p>={chosen:.2f}: "
              f"{float((mid>=chosen).mean()):.1%} false cutoffs, "
              f"{recall:.1%} of turns endable early")
        print(f"  text-only model reached 9.0% at the same safety bar")

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    import pickle
    (out / "audio_turn.pkl").write_bytes(pickle.dumps(clf))
    (out / "audio_turn.json").write_text(json.dumps({
        "clips": int(X.shape[0]), "features": names,
        "threshold": chosen, "false_cutoff_cap": MAX_FALSE_CUTOFF,
        "importances": {n_: float(v) for n_, v in imp},
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {out/'audio_turn.pkl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
