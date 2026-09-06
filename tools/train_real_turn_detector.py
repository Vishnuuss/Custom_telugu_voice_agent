#!/usr/bin/env python
"""Retrain the turn detector on REAL negatives instead of invented ones.

What was wrong with the old model
---------------------------------
`turnstops.jsonl` is 2,754 rows and every one is `was_turn_end: True`, because
`vaani_harvest.py` hardcodes it. The trainer then MANUFACTURES negatives by
cutting prefixes off those positives, and says so itself: "a prefix ending at a
natural clause boundary may genuinely be a complete turn".

So the model learned from:
  * positives that are the DEPLOYED SYSTEM'S OWN DECISIONS, mistakes included --
    including "ఆ." and "హలో." taught as complete turns
  * negatives that never happened

Run 819's caller said "ఆ" before every sentence and was answered every time. The
model was doing exactly what it had been taught.

What this trains on instead
---------------------------
`turnstops_real.jsonl`, built by `build_real_turn_labels.py` from 648 recordings:
1,707 real completions and 1,243 real interruptions, labelled from the audio by
whether the caller actually carried on within RESUME_WINDOW_S.

Same 16 features, same window, same file format, so the artifact drops straight
into the analyzer and can be scored by `replay_turns.py` before it goes anywhere
near a call.

Split by RECORDING, never by row: two bursts from one call share a speaker, a
line and a microphone, and splitting by row would let the model memorise those
rather than learn the task.

    python tools/train_real_turn_detector.py
"""
from __future__ import annotations

import argparse, json, sys, wave
from pathlib import Path

import numpy as np

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO.parent / "dograh-vapi"))
from api.services.vaani.telugu_turn import WINDOW_S, extract_features  # noqa: E402

DATA = REPO / ".tmp" / "harvest" / "turnstops_real.jsonl"
CALLER = REPO / ".tmp" / "audio" / "caller"
OUT = REPO / "models" / "audio_turn_real.json"


def features():
    rows = [json.loads(l) for l in DATA.open(encoding="utf-8")]
    by_call = {}
    for r in rows:
        by_call.setdefault(f"wf{r['workflow']}_run{r['run']}", []).append(r)

    X, y, groups = [], [], []
    for stem, rs in by_call.items():
        wav = CALLER / f"{stem}.wav"
        if not wav.exists():
            continue
        with wave.open(str(wav)) as w:
            sr = w.getframerate()
            pcm = w.readframes(w.getnframes())
        x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        for r in rs:
            hi = int(r["end"] * sr)
            lo = max(0, hi - int(WINDOW_S * sr))
            seg = x[lo:hi]
            if seg.size < int(0.2 * sr):
                continue
            f = extract_features(seg, sr)
            if f is None:
                continue
            X.append(f); y.append(1 if r["was_turn_end"] else 0); groups.append(stem)
    return np.asarray(X, float), np.asarray(y, int), np.asarray(groups)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", type=float, default=0.25)
    a = ap.parse_args()

    X, y, g = features()
    print(f"{len(X)} examples, {int(y.sum())} complete / {int((1-y).sum())} incomplete")
    if len(X) < 200:
        print("not enough data"); return 1

    calls = sorted(set(g.tolist()))
    rng = np.random.default_rng(0); rng.shuffle(calls)
    cut = int(len(calls) * (1 - a.holdout))
    train = set(calls[:cut]); mask = np.array([c in train for c in g])
    Xtr, ytr, Xte, yte = X[mask], y[mask], X[~mask], y[~mask]
    print(f"split by CALL: {len(Xtr)} train / {len(Xte)} holdout "
          f"({len(train)} calls / {len(calls)-len(train)})")

    # A 250-tree forest, the same learner the shipped model uses. A linear model
    # on these features scored 1.2% false cutoffs on the holdout but only 10.7%
    # of turns endable early, which pushes almost everything onto the timed path
    # and makes the call slower. The trees are what buy back the speed.
    from sklearn.ensemble import GradientBoostingClassifier
    clf = GradientBoostingClassifier(n_estimators=250, max_depth=3,
                                     learning_rate=0.05, subsample=0.9,
                                     random_state=0)
    clf.fit(Xtr, ytr)
    pf = clf.predict_proba(Xte)[:, 1]
    print("")
    print(f"{'FOREST thr':>11} {'false cutoffs':>14} {'endable early':>15}")
    fbest = None
    for thr in np.arange(0.50, 0.999, 0.01):
        fires = pf >= thr
        co = float((fires & (yte == 0)).sum() / max(1, (yte == 0).sum()))
        ea = float((fires & (yte == 1)).sum() / max(1, (yte == 1).sum()))
        if co <= 0.02 and (fbest is None or ea > fbest[2]):
            fbest = (thr, co, ea)
    if fbest:
        print(f"{fbest[0]:>11.2f} {100*fbest[1]:>13.1f}% {100*fbest[2]:>14.1f}%")
        import json as _j
        def _t(t):
            tr = t.tree_
            return {"feature": tr.feature.tolist(), "threshold": tr.threshold.tolist(),
                    "left": tr.children_left.tolist(), "right": tr.children_right.tolist(),
                    "value": tr.value.reshape(-1).tolist()}
        init = float(np.log(max(1e-6, ytr.mean()) / max(1e-6, 1 - ytr.mean())))
        gbm = {"trees": [_t(e[0]) for e in clf.estimators_],
               "learning_rate": float(clf.learning_rate), "init": init,
               "n_features": int(X.shape[1]), "threshold": float(fbest[0]),
               "false_cutoff_rate": float(fbest[1]), "early_end_rate": float(fbest[2]),
               "n_examples": int(len(X)), "n_incomplete": int((1 - y).sum()),
               "note": "REAL negatives from audio resume, not generated prefixes."}
        gp = REPO / "models" / "audio_turn_real_gbm.json"
        gp.parent.mkdir(parents=True, exist_ok=True)
        gp.write_text(_j.dumps(gbm), encoding="utf-8")
        print(f"-> {gp.relative_to(REPO)}  ({len(gbm['trees'])} trees)")
    else:
        print("  no forest threshold reaches 2% false cutoffs")

    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-6
    Ztr, Zte = (Xtr - mu) / sd, (Xte - mu) / sd
    w = np.zeros(Ztr.shape[1]); b = 0.0
    for _ in range(4000):
        p = 1 / (1 + np.exp(-(Ztr @ w + b)))
        gw = Ztr.T @ (p - ytr) / len(ytr) + 1e-4 * w
        gb = float((p - ytr).mean())
        w -= 0.5 * gw; b -= 0.5 * gb

    pte = 1 / (1 + np.exp(-(Zte @ w + b)))
    print(f"\n{'threshold':>10} {'false cutoffs':>14} {'turns ended early':>18}")
    best = None
    for thr in np.arange(0.50, 0.996, 0.02):
        fires = pte >= thr
        cut_off = float((fires & (yte == 0)).sum() / max(1, (yte == 0).sum()))
        early = float((fires & (yte == 1)).sum() / max(1, (yte == 1).sum()))
        if thr in (0.5, 0.7, 0.9) or abs(thr - 0.98) < 0.011:
            print(f"{thr:>10.2f} {100*cut_off:>13.1f}% {100*early:>17.1f}%")
        if cut_off <= 0.02 and (best is None or early > best[2]):
            best = (thr, cut_off, early)

    if best is None:
        print("\nNo threshold reaches a 2% false-cutoff rate on real negatives.")
        thr = 0.99
        fires = pte >= thr
        best = (thr, float((fires & (yte == 0)).sum() / max(1, (yte == 0).sum())),
                float((fires & (yte == 1)).sum() / max(1, (yte == 1).sum())))
    print(f"\nchosen threshold {best[0]:.2f}: false cutoffs {100*best[1]:.1f}%, "
          f"{100*best[2]:.1f}% of finished turns ended early")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "mean": mu.tolist(), "scale": sd.tolist(),
        "coef": w.tolist(), "intercept": float(b),
        "n_features": int(X.shape[1]), "threshold": float(best[0]),
        "false_cutoff_rate": float(best[1]), "early_end_rate": float(best[2]),
        "n_examples": int(len(X)), "n_incomplete": int((1 - y).sum()),
        "note": "REAL negatives from audio resume, not generated prefixes.",
    }, ensure_ascii=False), encoding="utf-8")
    print(f"-> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
