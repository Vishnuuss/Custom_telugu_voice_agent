"""Export the gradient-boosted turn detector to plain numbers.

Why this exists
---------------
The shipped Telugu detector is a logistic regression that ends 33.9% of turns
early at the 2% false-cutoff bar. The gradient-boosted model trained on the same
1,393 clips reaches 47.8% -- and was rejected, correctly, because scoring it
needed scikit-learn inside the voice container:

    "Fourteen points of recall is not worth putting a new dependency on the
     call path."   -- telugu_turn.py

That trade was framed as recall versus a dependency. It is not. A boosted forest
IS a pile of thresholds and constants; sklearn is only the thing that FOUND them.
Exported as arrays, scoring is a walk down 250 short trees -- a few hundred
float comparisons, microseconds, on numpy, which pipecat already depends on.

Why it matters, measured
------------------------
Run 262's endpoint times are bimodal: 0.403s on the five turns where the
detector fired, 0.78-1.22s on the eight where it did not and the timeout ran.
Every turn moved from the second group to the first is worth roughly half a
second to the caller. That is the whole remaining latency gap.

Verification is the point of this script
-----------------------------------------
An export that quietly disagrees with the model it came from would be worse than
not shipping it, so the exported arithmetic is scored against sklearn's own
predictions on every clip and the maximum disagreement is printed. Anything
above 1e-9 means the export is wrong and must not ship.

    python tools/export_gbm_turn.py
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
import wave
from pathlib import Path

import numpy as np
from sklearn.model_selection import GroupShuffleSplit

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
DOGRAH = REPO.parent / "dograh-vapi"
sys.path.insert(0, str(DOGRAH))

from api.services.vaani.telugu_turn import extract_features  # noqa: E402

SR = 8000
MAX_FALSE_CUTOFF = 0.02      # unchanged: the caller-facing safety bar


def load(path: str) -> np.ndarray | None:
    try:
        with wave.open(path) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    except Exception:
        return None
    return x.astype(np.float32) / 32768.0 if x.size >= SR // 2 else None


def export_tree(tree) -> dict:
    """One decision tree as four flat arrays."""
    t = tree.tree_
    return {
        "feature": t.feature.tolist(),
        "threshold": t.threshold.tolist(),
        "left": t.children_left.tolist(),
        "right": t.children_right.tolist(),
        "value": t.value.reshape(-1).tolist(),
    }


def score_tree(tree: dict, x: np.ndarray) -> float:
    """Walk one tree. `feature < 0` marks a leaf."""
    node = 0
    while tree["feature"][node] >= 0:
        node = (tree["left"][node]
                if x[tree["feature"][node]] <= tree["threshold"][node]
                else tree["right"][node])
    return tree["value"][node]


def score(model: dict, x: np.ndarray) -> float:
    raw = model["init"] + model["learning_rate"] * sum(
        score_tree(t, x) for t in model["trees"])
    return 1.0 / (1.0 + np.exp(-raw))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pkl", default=".tmp/models/audio_turn.pkl")
    ap.add_argument("--index", default=".tmp/audio/dataset/index.jsonl")
    ap.add_argument("--out",
                    default=str(DOGRAH / "api/services/vaani/models/audio_turn_gbm.json"))
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    # pickle.loads on a LOCAL file this repo's own trainer wrote
    # (tools/train_audio_turn.py), run offline by hand. Nothing here is fetched
    # or user-supplied, and the runtime never unpickles anything: the whole
    # point of this script is that the call path loads JSON arrays instead.
    clf = pickle.loads(Path(a.pkl).read_bytes())
    model = {
        "trees": [export_tree(t[0]) for t in clf.estimators_],
        "learning_rate": float(clf.learning_rate),
        "init": float(clf.init_.class_prior_[1] if hasattr(clf.init_, "class_prior_")
                      else np.log(clf.init_.constant_[0][0] / (1 - clf.init_.constant_[0][0]))
                      if hasattr(clf.init_, "constant_") else 0.0),
        "n_features": int(clf.n_features_in_),
    }
    # sklearn stores the raw initial log-odds on the estimator itself.
    model["init"] = float(np.ravel(clf._raw_predict_init(np.zeros((1, clf.n_features_in_))))[0])
    print(f"{len(model['trees'])} trees, lr={model['learning_rate']}, init={model['init']:.4f}")

    rows = [json.loads(x) for x in
            Path(a.index).read_text(encoding="utf-8").splitlines() if x.strip()]
    X, y, groups = [], [], []
    for r in rows:
        x = load(r["path"])
        if x is None:
            continue
        f = extract_features(x, SR)
        if f is None:
            continue
        X.append(f); y.append(r["label"]); groups.append(r["run"])
    X = np.asarray(X, dtype=np.float32)
    y = np.asarray(y); groups = np.asarray(groups)
    print(f"{X.shape[0]} clips scored")

    # 1. Does the export reproduce sklearn EXACTLY?
    theirs = clf.predict_proba(X)[:, 1]
    ours = np.array([score(model, row.astype(np.float64)) for row in X])
    drift = float(np.abs(theirs - ours).max())
    print(f"\nmax disagreement with sklearn: {drift:.3e}")
    if drift > 1e-9:
        print("EXPORT IS WRONG -- not written.")
        return 1
    print("exact match; the exported arithmetic IS the model")

    # 2. Choose the threshold on held-out CALLS, exactly as the trainer did.
    tr, te = next(GroupShuffleSplit(n_splits=1, test_size=0.25,
                                    random_state=a.seed).split(X, y, groups))
    p, yt = ours[te], y[te]
    mid, end = p[yt == 0], p[yt == 1]
    chosen = None
    for t in np.arange(0.50, 1.00, 0.01):
        if float((mid >= t).mean()) <= MAX_FALSE_CUTOFF:
            chosen = float(t)
            break
    if chosen is None:
        print(f"no threshold holds false cutoffs under {MAX_FALSE_CUTOFF:.0%}")
        return 1
    model["threshold"] = chosen
    print(f"\noperating point p>={chosen:.2f} on {len(te)} held-out clips")
    print(f"  false cutoffs      {float((mid>=chosen).mean()):.1%}  (cap {MAX_FALSE_CUTOFF:.0%})")
    print(f"  turns ended early  {float((end>=chosen).mean()):.1%}")
    print(f"  shipped LR reached 33.9% at the same bar")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model), encoding="utf-8")
    print(f"\nwrote {out}  ({out.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
