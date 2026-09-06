#!/usr/bin/env python
"""Which model is deployed, where it came from, and whether a new one is better.

The gap this fills
------------------
The deployed turn detector,
`dograh-vapi/api/services/vaani/models/audio_turn_gbm.json`, stores exactly
five things: its trees, its learning rate, its init value, its feature count and
its threshold. It does not record which dataset trained it, how large that
dataset was, when it was built, what it scored, or which commit produced it.

So "is the model in production the good one" had no answer, and "is this new
model better than the one running" had no answer either. Both are the whole job
of a registry.

What this is NOT
----------------
Not a model server, not a feature store, not Kubeflow. There is one owned model
and a few thousand training rows; that infrastructure would be overhead
pretending to be rigour. This is a JSON file, a hash, and a promotion rule.

The promotion rule, and why it is not accuracy
----------------------------------------------
A candidate is only better if it wins on the metric the agent is actually judged
by, which `train_turn_detector.py` already establishes:

    false cutoffs      the caller was still talking and we cut in.
                       THE cardinal failure -- it is what Telugu callers
                       complained about, and it must stay under 2%.
    turns ended early  how much waiting the model removes. The reward.

A model with better accuracy and a worse cutoff rate is a WORSE model, and
promoting it on accuracy is the classic way to ship a regression. So the rule is:

    the cutoff rate must not get worse, AND
    the early-end rate must improve

Both, or it is not promoted.

    python tools/model_registry.py list
    python tools/model_registry.py register --note "retrained on Sep data"
    python tools/model_registry.py compare <candidate.json>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
DOGRAH = REPO.parent / "dograh-vapi"
DEPLOYED = DOGRAH / "api" / "services" / "vaani" / "models" / "audio_turn_gbm.json"
REGISTRY = REPO / "models" / "registry.json"
ARCHIVE = REPO / "models" / "archive"

# The dataset the detector is trained from.
DATASET = REPO / ".tmp" / "harvest" / "turnstops.jsonl"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12] if path.exists() else ""


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=DOGRAH, capture_output=True, text=True, timeout=15)
        return out.stdout.strip()
    except Exception:
        return ""


def _load_registry() -> dict:
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    return {"deployed": None, "versions": []}


def _save_registry(reg: dict) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(reg, indent=1, ensure_ascii=False),
                        encoding="utf-8")


def _model_facts(path: Path) -> dict:
    """Everything the artifact itself can tell us."""
    d = json.loads(path.read_text(encoding="utf-8"))
    return {
        "sha": _sha(path),
        "bytes": path.stat().st_size,
        "trees": len(d.get("trees") or []),
        "n_features": d.get("n_features"),
        "threshold": d.get("threshold"),
        # Written by train_turn_detector when it produced the model. Absent on
        # anything trained before the registry existed -- which is the point.
        "metrics": {k: d[k] for k in
                    ("accuracy_at_0.5", "false_cutoff_cap", "n_utterances",
                     "n_examples", "early_end_rate", "false_cutoff_rate")
                    if k in d},
    }


def cmd_register(a) -> int:
    if not DEPLOYED.exists():
        print(f"no model at {DEPLOYED}")
        return 1
    reg = _load_registry()
    facts = _model_facts(DEPLOYED)

    if any(v["sha"] == facts["sha"] for v in reg["versions"]):
        print(f"already registered (sha {facts['sha']})")
        return 0

    version = f"v{len(reg['versions']) + 1}"
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    kept = ARCHIVE / f"audio_turn_gbm_{version}.json"
    kept.write_bytes(DEPLOYED.read_bytes())

    entry = {
        "version": version,
        "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "artifact": str(kept.relative_to(REPO)),
        "git_commit": _git_commit(),
        "dataset": {
            "path": str(DATASET.relative_to(REPO)) if DATASET.exists() else None,
            "sha": _sha(DATASET),
            "rows": sum(1 for _ in DATASET.open(encoding="utf-8"))
            if DATASET.exists() else None,
        },
        "note": a.note or "",
        **facts,
    }
    reg["versions"].append(entry)
    reg["deployed"] = version
    _save_registry(reg)
    print(f"registered {version}  sha {facts['sha']}  "
          f"trees {facts['trees']}  threshold {facts['threshold']}")
    if not facts["metrics"]:
        print("  NOTE: this artifact carries no metrics. It predates the "
              "registry, so its scores are unknown and cannot be compared to.")
    print(f"  archived -> {kept.relative_to(REPO)}")
    return 0


def cmd_list(a) -> int:
    reg = _load_registry()
    if not reg["versions"]:
        print("registry is empty -- run `register` to record the deployed model")
        return 0
    print(f"\n{'ver':>5} {'registered':17} {'sha':>13} {'trees':>6} "
          f"{'thresh':>7} {'rows':>7}  note")
    print("-" * 78)
    for v in reg["versions"]:
        live = "*" if v["version"] == reg.get("deployed") else " "
        rows = (v.get("dataset") or {}).get("rows")
        print(f"{live}{v['version']:>4} {v['registered_at'][:16]:17} "
              f"{v['sha']:>13} {v['trees']:>6} {str(v['threshold'])[:7]:>7} "
              f"{str(rows or '-'):>7}  {v.get('note','')[:24]}")
    print("\n* = currently deployed")
    live = next((v for v in reg["versions"]
                 if v["version"] == reg.get("deployed")), None)
    if live and not live.get("metrics"):
        print("\nThe deployed model carries NO METRICS. Any replacement must be "
              "\nscored against a fresh holdout, not against it.")
    return 0


def cmd_compare(a) -> int:
    cand = Path(a.candidate)
    if not cand.exists():
        print(f"no such file: {cand}")
        return 1
    reg = _load_registry()
    live = next((v for v in reg["versions"]
                 if v["version"] == reg.get("deployed")), None)
    new = _model_facts(cand)

    print(f"\n{'':22} {'DEPLOYED':>14} {'CANDIDATE':>14}")
    print("-" * 54)
    for key, label in (("trees", "trees"), ("n_features", "features"),
                       ("threshold", "threshold")):
        old = live.get(key) if live else "-"
        print(f"{label:22} {str(old)[:14]:>14} {str(new.get(key))[:14]:>14}")

    om, nm = (live or {}).get("metrics") or {}, new.get("metrics") or {}
    for key in ("false_cutoff_rate", "early_end_rate", "accuracy_at_0.5"):
        if key in om or key in nm:
            print(f"{key:22} {str(om.get(key, '-'))[:14]:>14} "
                  f"{str(nm.get(key, '-'))[:14]:>14}")

    print("\nPROMOTION RULE — both must hold:")
    print("  1. false cutoffs must NOT get worse   (the cardinal failure)")
    print("  2. turns ended early must improve     (the reward)")

    if not om or not nm:
        print("\nVERDICT: CANNOT DECIDE. One side has no recorded metrics, so"
              "\nthere is nothing to compare. Score both on the SAME holdout"
              "\nwith train_turn_detector.py before promoting anything.")
        return 2

    worse_cut = nm.get("false_cutoff_rate", 1) > om.get("false_cutoff_rate", 0)
    better_early = nm.get("early_end_rate", 0) > om.get("early_end_rate", 1)
    if worse_cut:
        print("\nVERDICT: REJECT — it cuts callers off more often.")
    elif not better_early:
        print("\nVERDICT: REJECT — no gain; it ends no more turns early.")
    else:
        print("\nVERDICT: PROMOTE — safer or equal on cutoffs, and faster.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    r = sub.add_parser("register")
    r.add_argument("--note", default="")
    r.set_defaults(fn=cmd_register)
    c = sub.add_parser("compare")
    c.add_argument("candidate")
    c.set_defaults(fn=cmd_compare)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
