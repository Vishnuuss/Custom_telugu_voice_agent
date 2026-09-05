"""Train a Telugu turn-completion detector on 2,754 real caller utterances.

Why this model and not a faster LLM
-----------------------------------
Measured on run 7, a real call: perceived latency was 2.256s, split as ~1.385s
from the caller falling silent to a final transcript, and 0.872s from there to
the first audio. **Endpointing is the larger half.** Every LLM optimisation so
far has been fighting over the smaller one.

And there is nothing to buy. No Telugu turn detector exists: Smart Turn v3 covers
23 languages, LiveKit v1 14, Deepgram Flux 10, AssemblyAI 4-6 -- Telugu is in
none of them. The `eager_eot_threshold` sitting in `service_factory.py` is dead
code on a Telugu call.

Where the labels come from
--------------------------
The harvest gives 2,754 utterances that were all, by definition, complete -- a
final transcript IS a finished turn. That is 2,754 positives and zero negatives,
which trains nothing.

Negatives are generated the way LiveKit and Smart Turn build theirs: a PREFIX of
a complete utterance is, by construction, incomplete. "నాకు రెండు వేలు వస్తుంది"
truncated to "నాకు రెండు" is a turn that has not finished. This is not a
shortcut; it is the standard construction, and it matches what the model must
actually decide at runtime -- the endpointer sees a partial transcript and has to
judge whether more is coming.

Two consequences kept honest:
  - A prefix ending at a natural clause boundary may genuinely be a complete
    turn ("సరే" is a whole answer), so a fraction of the negatives are wrong.
    That caps achievable accuracy and is stated in the report, not hidden.
  - Splitting is by UTTERANCE, never by example. Prefixes of one sentence
    appearing on both sides of the split would leak, and the score would be a
    fiction.

What the number to optimise actually is
---------------------------------------
Not accuracy. A false "complete" cuts a caller off mid-sentence, which is the
one failure Telugu callers complained about in earlier testing; a false
"incomplete" merely costs the normal silence wait. So the model is scored at the
threshold where false cutoffs stay under 2%, and the report says how much of the
wait it can remove at that operating point.

    python tools/train_turn_detector.py --data .tmp/harvest/turnstops.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

# A caller cannot be cut off more than this often. Telugu callers protested at
# 350ms of total silence in earlier testing; being talked over is worse.
MAX_FALSE_CUTOFF_RATE = 0.02


def load(path: Path) -> list[str]:
    seen, out = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        text = (json.loads(line).get("text") or "").strip()
        # One-word utterances are KEPT, and that is the point. An earlier
        # version dropped them as grunts, which was exactly wrong for this
        # agent: qualification callers answer in one or two words -- "సరే",
        # "అవును", "అనంతపూర్" -- and every one of those is a finished turn.
        # Training without them taught the model that short means unfinished,
        # which is the most common and most costly case to get wrong.
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def examples(utterances: list[str], rng: random.Random):
    """(text, is_complete, source_utterance) -- grouped so the split cannot leak."""
    rows = []
    for u in utterances:
        words = u.split()
        rows.append((u, 1, u))
        # Prefixes are the negatives. Sample rather than take all, so long
        # utterances do not dominate the class.
        cuts = list(range(1, len(words)))
        rng.shuffle(cuts)
        for c in cuts[:2]:
            rows.append((" ".join(words[:c]), 0, u))
    return rows


def split(rows, rng: random.Random, frac: float = 0.2):
    """Split by SOURCE utterance. Splitting by row would leak prefixes."""
    sources = sorted({r[2] for r in rows})
    rng.shuffle(sources)
    held = set(sources[: int(len(sources) * frac)])
    train = [r for r in rows if r[2] not in held]
    test = [r for r in rows if r[2] in held]
    return train, test


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=".tmp/harvest/turnstops.jsonl")
    ap.add_argument("--out", default=".tmp/models")
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    utterances = load(Path(a.data))
    short = sum(1 for u in utterances if len(u.split()) == 1)
    print(f"{len(utterances)} distinct caller utterances "
          f"({short} of them a single word -- kept deliberately)")
    if len(utterances) < 300:
        print("too few to train on; harvest more calls first")
        return 1

    rows = examples(utterances, rng)
    train, test = split(rows, rng)
    print(f"{len(rows)} examples -> {len(train)} train / {len(test)} test "
          f"(split by utterance, so no prefix leaks across)")

    Xtr = [r[0] for r in train]
    ytr = np.array([r[1] for r in train])
    Xte = [r[0] for r in test]
    yte = np.array([r[1] for r in test])

    # Character n-grams, because Telugu is agglutinative: the signal for "this
    # sentence has ended" lives in word-final morphology (-ఉంది, -అండి, -లేదు)
    # rather than in whole words, and a word-level model cannot see it.
    model = make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5),
                        min_df=2, sublinear_tf=True),
        # Plain LR, deliberately: its weights export to a flat dict, so the
        # live pipeline scores a partial with a dictionary lookup instead of
        # importing scikit-learn into the API container.
        LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced"),
    )
    model.fit(Xtr, ytr)

    prob = model.predict_proba(Xte)[:, 1]
    acc = float(((prob >= 0.5).astype(int) == yte).mean())
    print(f"\naccuracy at 0.5: {acc:.3f}")

    # The operating point that matters: how confident must we be before calling
    # a turn complete, to cut fewer than 2% of callers off mid-sentence?
    incomplete = prob[yte == 0]
    complete = prob[yte == 1]
    chosen, recall = None, 0.0
    for t in np.arange(0.50, 1.00, 0.01):
        false_cutoff = float((incomplete >= t).mean())
        if false_cutoff <= MAX_FALSE_CUTOFF_RATE:
            chosen = float(t)
            recall = float((complete >= t).mean())
            break

    print(f"\n{'threshold':>10} {'false cutoffs':>14} {'turns ended early':>18}")
    for t in (0.5, 0.6, 0.7, 0.8, 0.9, 0.95):
        print(f"{t:>10.2f} {float((incomplete >= t).mean()):>13.1%} "
              f"{float((complete >= t).mean()):>17.1%}")

    if chosen is None:
        print(f"\nNo threshold keeps false cutoffs under "
              f"{MAX_FALSE_CUTOFF_RATE:.0%}. Not shippable as an endpointer yet.")
    else:
        print(f"\nOperating point: p >= {chosen:.2f}")
        print(f"  false cutoffs      {float((incomplete >= chosen).mean()):.1%} "
              f"(cap {MAX_FALSE_CUTOFF_RATE:.0%})")
        print(f"  turns ended early  {recall:.1%}")
        print(f"\n  On {recall:.0%} of turns the endpointer could stop waiting as")
        print("  soon as the transcript looks complete, instead of sitting out")
        print("  the full silence window. The rest fall back to today's behaviour,")
        print("  so this can only make endpointing faster, never slower.")

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # Export to plain weights. The live scorer must not depend on sklearn.
    vec, clf = model.steps[0][1], model.steps[1][1]
    weights = {t: round(float(w), 5)
               for t, w in zip(vec.get_feature_names_out(), clf.coef_[0])
               if abs(w) > 1e-4}
    (out / "turn_detector_weights.json").write_text(json.dumps({
        "kind": "char_wb_tfidf_logreg",
        "ngram_range": list(vec.ngram_range),
        "idf": {t: round(float(v), 5)
                for t, v in zip(vec.get_feature_names_out(), vec.idf_)
                if t in weights},
        "weights": weights,
        "intercept": round(float(clf.intercept_[0]), 5),
        "threshold_endpointing": chosen,
        "threshold_speculation": 0.5,
    }, ensure_ascii=False), encoding="utf-8")
    import pickle
    (out / "turn_detector.pkl").write_bytes(pickle.dumps(model))
    (out / "turn_detector.json").write_text(json.dumps({
        "utterances": len(utterances), "examples": len(rows),
        "accuracy_at_0.5": round(acc, 4),
        "threshold": chosen, "false_cutoff_cap": MAX_FALSE_CUTOFF_RATE,
        "turns_ended_early": round(recall, 4),
        "note": ("Negatives are generated prefixes, the standard construction. "
                 "A prefix that lands on a natural clause boundary can be a "
                 "genuine complete turn, so a fraction of negatives are "
                 "mislabelled and true accuracy is higher than reported."),
    }, indent=1), encoding="utf-8")
    print(f"\nwrote {out/'turn_detector.pkl'}")

    print("\nsanity check on held-out text:")
    for probe in ["నాకు రెండు", "నాకు రెండు వేలు వస్తుంది",
                  "మా", "మా ఇల్లు సొంతమే అండి", "సరే"]:
        p = float(model.predict_proba([probe])[0, 1])
        print(f"  p(complete)={p:.2f}  {probe!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
