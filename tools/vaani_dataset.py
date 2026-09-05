"""Turn real calls into training data. The thing every ML step downstream needs.

Why this and not a model
------------------------
Fine-tuning, distillation and preference tuning all need the same input: labelled
examples of what a good turn looks like and what a bad one looks like. There is no
way to skip to the model. What decides when that model becomes possible is call
volume, not effort -- as of 2026-08-27 there are 13 runs on workflow 2 and four of
them never connected. So this is built now and improves on its own as calls
accumulate.

What it produces
----------------
1. `sft.jsonl`  -- supervised examples, one per CLEAN turn: the conversation up to
   that point, and the reply the agent gave. This is the distillation corpus: a
   small model trained on these should reproduce a large model's behaviour on this
   narrow task at a fraction of the latency and cost.

2. `dpo.jsonl`  -- preference pairs, one per turn where a REJECTED reply exists:
   the same context, with the malformed reply as `rejected` and the sanitised one
   as `chosen`. This is where RL legitimately enters. The pairs are free, because
   `ReplySanitizer` already records exactly what it removed and why -- every blob,
   leaked control token and invented caller line is a labelled negative that cost
   nothing to produce.

3. `turnstops.jsonl` -- (endpointing) each caller utterance with whether it was
   actually the end of their turn. Feeds a Telugu turn detector, which does not
   exist anywhere: Smart Turn v3 covers 23 languages, LiveKit v1 14, Deepgram Flux
   10, AssemblyAI 4-6, and Telugu is in none of them. That model is worth more
   than any prompt change, because endpointing is ~1.4s of a ~2.3s turn.

The label
---------
A turn is "clean" if it breaks none of the hard rules the eval battery enforces --
same function, imported, so the dataset and the gate can never drift apart. A
model trained on turns the gate would reject would learn the defects.

    python tools/vaani_dataset.py --workflow 2 --out .tmp/dataset
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vaani_eval import BASE, KEY, hard_rules  # noqa: E402

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


def get(path: str):
    r = urllib.request.Request(f"{BASE}{path}", headers={"X-API-Key": KEY})
    with urllib.request.urlopen(r, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def turns_of(run: dict) -> list[dict]:
    """Rebuild (user said, agent replied) pairs from the event stream."""
    events = (run.get("logs") or {}).get("realtime_feedback_events") or []
    out, pending_user = [], None
    for e in events:
        t, p = e.get("type") or "", e.get("payload") or {}
        if t == "rtf-user-transcription" and p.get("final"):
            pending_user = (p.get("text") or "").strip()
        elif t == "rtf-bot-text":
            out.append({"user": pending_user, "bot": (p.get("text") or "").strip(),
                        "at": e.get("timestamp")})
            pending_user = None
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, default=2)
    ap.add_argument("--out", default=".tmp/dataset")
    ap.add_argument("--limit", type=int, default=50)
    a = ap.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    listing = get(f"/api/v1/workflow/{a.workflow}/runs?page=1&limit={a.limit}")
    runs = listing.get("runs", listing if isinstance(listing, list) else [])
    print(f"{len(runs)} run(s) on workflow {a.workflow}")

    sft, dpo, stops = [], [], []
    connected = 0
    for meta in runs:
        try:
            run = get(f"/api/v1/workflow/{a.workflow}/runs/{meta['id']}")
        except Exception as e:
            print(f"  run {meta.get('id')}: {e!r}")
            continue
        pairs = turns_of(run)
        if not pairs:
            continue
        connected += 1
        history = []
        for turn in pairs:
            if turn["user"]:
                history.append({"role": "user", "content": turn["user"]})
                stops.append({"text": turn["user"], "run": meta["id"],
                              "was_turn_end": True})
            reply = turn["bot"]
            if not reply:
                continue
            violations = hard_rules(reply)
            if violations:
                # A malformed reply is not waste -- it is a labelled negative,
                # and the only thing missing is what SHOULD have been said. That
                # is filled in by review or by the current (fixed) agent.
                dpo.append({"run": meta["id"], "messages": list(history),
                            "rejected": reply, "chosen": None,
                            "why": violations})
            else:
                sft.append({"run": meta["id"], "messages": list(history),
                            "completion": reply})
            history.append({"role": "assistant", "content": reply})

    for name, rows in (("sft", sft), ("dpo", dpo), ("turnstops", stops)):
        path = out / f"{name}.jsonl"
        path.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8")
        print(f"  {len(rows):>4} -> {path}")

    print(f"\n{connected} run(s) had any conversation at all.")
    # Say plainly what the sample size supports, rather than implying a model.
    if len(sft) < 200:
        print(f"NOT ENOUGH TO TRAIN ON YET: {len(sft)} clean turn(s).")
        print("Rough shape of what each job needs, from published practice:")
        print("  distillation / SFT     ~500-1000 clean turns")
        print("  preference tuning      ~200-500 labelled pairs")
        print("  a Telugu turn detector ~hundreds of labelled utterances")
        print("The pipeline is ready; it is call volume that is missing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
