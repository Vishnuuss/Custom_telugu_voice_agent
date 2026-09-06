# MLOps for Vaani — the learning loop, sized for what we actually own

**5 September 2026 · Project Vaani**

Built without touching the serving path. Vaani is working; nothing here changes
how a call runs. Every tool is offline and read-only against the server.

---

## 1. What we actually own

MLOps is only worth building around models you train yourself. Vaani has one:

| Model | Ours? | Notes |
|---|---|---|
| **Telugu turn detector** | **YES** | 250-tree gradient-boosted forest, 2,754 utterances, 651 callers |
| Groq `gpt-oss-120b` | no | vendor API |
| Sarvam STT | no | vendor API |
| Cartesia TTS | no | vendor API |

So the loop is built around **one model**, plus the datasets already being
harvested for a second (a distilled LLM) that has not been trained yet.

**This is not Kubeflow, a feature store, or model orchestration.** One owned
model and a few thousand rows do not justify that; it would be overhead
pretending to be rigour. What was built is a JSON file, a hash, and two
measurements.

---

## 2. What already existed, and was already right

Worth stating before adding anything, because the hard part was done:

- `vaani_harvest.py` — mines every completed call for training signal
- `vaani_dataset.py` — builds `sft.jsonl` (3,810 rows) and `dpo.jsonl`
- `train_turn_detector.py` — trains, and **splits by utterance, never by
  example**, so prefixes of one sentence cannot leak across the split and make
  the score a fiction
- It also already optimises **the right metric**: not accuracy, but the
  threshold where **false cutoffs stay under 2%** — because cutting a Telugu
  caller off mid-sentence is the failure they actually complain about

The gaps were everything *after* training: versioning, provenance, production
measurement, and a promotion rule.

---

## 3. Gap 1 — nobody knew if the deployed model was any good

The live artifact, `api/services/vaani/models/audio_turn_gbm.json`, stores five
things: trees, learning rate, init, feature count, threshold. **No dataset, no
date, no metrics, no commit.**

So two questions had no answer: *is the model in production the good one*, and
*is this new model better than the one running*.

### `tools/model_registry.py`
Records every version with its provenance and archives the artifact.

```
  ver registered                  sha  trees  thresh    rows  note
*  v1 2026-09-05T17:11   ab5214363e51    250 0.97000    2754  incumbent, 28 Aug
```

It also says the uncomfortable thing out loud:

> The deployed model carries NO METRICS. Any replacement must be scored against
> a fresh holdout, not against it.

### The promotion rule — and why it is not accuracy
A candidate is promoted only if **both** hold:

1. **False cutoffs must not get worse** — the cardinal failure
2. **Turns ended early must improve** — the reward

A model with better accuracy and a worse cutoff rate is a **worse model**.
Promoting on accuracy is the classic way to ship a regression, and the rule
refuses to do it.

---

## 4. Gap 2 — nobody had measured the detector in production

`train_turn_detector.py` scores a candidate on held-out data, with **synthetic
negatives** (prefixes of complete utterances) on data it was tuned against.
That is a laboratory number. Nothing measured the model on live Telugu calls.

### `tools/turn_detector_monitor.py`
The signal was already defined inside `telugu_turn.py`:

> `RESUME_WINDOW_S = 1.0` — "If the caller starts talking again this soon after
> we ended his turn, we did not end it — we interrupted it."

That rule runs live, per caller, to adapt the threshold. The monitor reads the
same event out of the call log afterwards and counts it across every call,
turning a per-caller heuristic into a **fleet metric**.

It tracks the two failures that point in opposite directions — which is the
entire point, because one number cannot show a trade-off:

| | Meaning |
|---|---|
| **cutoff** | caller resumed < 1.0 s after the agent began — we cut them off |
| **slow** | endpoint took > 0.6 s — the caller was audibly waiting |

### First production measurement, 14 calls, 124 turns

```
cutoff rate      1.6%   (2/124)    target < 2%   PASS
endpoint p50     0.487s            budget 0.250s
```

> **CORRECTED 6 Sep 2026 — this number is wrong and must not be quoted.**
>
> Replaying 200 recorded calls through the shipped analyzer frame by frame
> (`tools/replay_turns.py`) measures **35.9% of speech bursts cut off**, not
> 1.6%. The monitor undercounts by more than twenty times, because it reads
> resumes out of the run log and the log only records FINAL transcripts — it
> cannot see the caller restarting inside one utterance, which is where almost
> all of the cut-offs are.
>
> The claim below — that the detector meets its quality bar on real calls — is
> therefore withdrawn. It does not. See
> [29-the-four-bugs-and-the-turn-detector-truth](29-the-four-bugs-and-the-turn-detector-truth-2026-09-06.md)
> §4 for the measurement, the pipecat bake-off, and the root cause.
>
> The lesson is the one this document already warns about in §5, applied to
> itself: a metric that agrees with what you hoped is the one to check hardest.

It also independently caught the 5 Sep incident — run 780, the broken realtime
STT call, shows endpoint 1.398 s and 100% slow turns, with no knowledge of what
happened.

---

## 5. The honest constraint: there is no new data

The loop is built. It cannot turn yet, and pretending otherwise would be the
error the ChatGPT overview warns about.

| Corpus | 27 Aug | 4 Sep | New |
|---|---|---|---|
| Turn-detector utterances | 2,754 | 2,759 | **5** |
| Preference pairs | 474,568 bytes | identical | **0** |

**Five new utterances in eight days.** Retraining a forest tuned to hold false
cutoffs under 2% on a 0.18% data increase cannot improve it and can only move
the operating point.

**The constraint is call volume, not tooling.** wf2 has taken about 50 calls in
its life. Every part of the loop — retraining, canary, drift detection — needs
traffic that does not exist yet.

### And the trap to avoid
Do **not** relabel training data from the monitor's output. A resume inside the
window is *evidence* of a cutoff, not proof — a caller may genuinely interject.
Feeding a model its own predictions back as truth is how a dataset rots, and the
tool says so in its own output every time it runs.

---

## 6. What is deliberately NOT built yet, and the trigger for each

| Piece | Build when |
|---|---|
| **Canary deployment** (10% → 25% → 100%) | The model is baked into the container image, so a canary needs per-call model selection. Worth building when there is a second model worth splitting traffic over — there is not |
| **Drift detection by segment** (noisy calls, elderly speakers) | Needs enough calls per segment to be a signal rather than noise. At ~50 calls per agent, every segment is noise |
| **Automated retraining** | Needs data arriving faster than a person can look at it |
| **Distilled LLM** | `sft.jsonl` has 3,810 rows READY. Train on the **loan agent's 1,095 calls**, not MB Solar's 50 |
| **Experiment tracking / registry service** | One model. A JSON file is the right size |

---

## 7. Where this sits in the system

```
   KNOWLEDGE          RUNTIME              MODELS
   Ontology           State block          Turn detector  (ours)
   Layer 3            Memory/checkpoint    LLM/STT/TTS    (vendor)
        └──────────────────┼───────────────────┘
                        Pipecat
                           │
                      CALL RESULT
                           │
        ┌──────────────────┴──────────────────┐
        │   harvest → registry → monitor      │
        │   (train → version → measure)       │
        └─────────────────────────────────────┘
```

Each part keeps its own job, and they are not mixed: the **ontology** structures
business knowledge, the **state block** holds runtime context, **prompt caching**
cuts repeated prefill, and **MLOps** versions, evaluates and monitors the one
model we train.

---

## 8. Summary

Two tools, both offline, neither touching a live call:

- **`model_registry.py`** — provenance, versioning, and a promotion rule that
  refuses a model which cuts callers off more often, however good its accuracy
- **`turn_detector_monitor.py`** — the first production measurement of the
  deployed detector: **1.6% cutoff rate against a 2% target**

The loop is real and closed. **It is waiting on call volume, not on engineering** —
and the most useful thing that could happen next is more real calls, not more
tooling.
