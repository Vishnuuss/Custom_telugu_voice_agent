"""Push the latency settings the code intends into the workflow that overrides them.

Why this exists
---------------
`workflow_configurations` is stored per workflow and wins over every constant in
`api/schemas/workflow_configurations.py`. The code reads it as
`run_configs.get("<key>", DEFAULT_<KEY>)` -- so a key PRESENT in the stored
config makes the default unreachable, whether or not anyone remembers setting it.

Workflow 2 carries explicit values for exactly the settings that have been tuned
in code over the last two days:

    speculation_enabled            false   (code now True)
    llm_hedge                          2   (code now 3)
    stt_finalisation_budget_secs     0.6   (code now 0.45)

So three shipped latency changes never ran. They were deployed, measured, found
to have changed nothing, and the absence of an effect was then explained with
other theories -- the network, the model, the prompt. The config was the reason.

This tool prints the difference and only writes what is asked for, because a
blind overwrite of a live agent's configuration is how a working call flow gets
lost.

    python tools/sync_latency_config.py                 # show the difference
    python tools/sync_latency_config.py --apply         # write it
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO.parent / "dograh-vapi"))

import vaani_runs as V  # noqa: E402


def code_defaults() -> dict:
    """The values the code intends, read from the schema rather than retyped."""
    from api.schemas import workflow_configurations as w

    return {
        "speculation_enabled": w.DEFAULT_SPECULATION_ENABLED,
        "llm_hedge": w.DEFAULT_LLM_HEDGE,
        "stt_finalisation_budget_secs": w.DEFAULT_STT_FINALISATION_BUDGET_SECS,
        "smart_turn_stop_secs": w.DEFAULT_SMART_TURN_STOP_SECS,
        "turn_stop_strategy": w.DEFAULT_TURN_STOP_STRATEGY,
        "turn_wait_for_transcript": w.DEFAULT_TURN_WAIT_FOR_TRANSCRIPT,
    }


def put(path: str, body: dict):
    req = urllib.request.Request(
        f"{V.BASE}{path}", method="PUT",
        data=json.dumps(body).encode("utf-8"),
        headers={"X-API-Key": V.KEY, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, default=2)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    wf = V.get(f"/api/v1/workflow/fetch/{a.workflow}")
    cfg = dict(wf.get("workflow_configurations") or {})
    want = code_defaults()

    print(f"{'setting':<32}{'stored':>16}{'code wants':>14}")
    changes = {}
    for key, target in want.items():
        current = cfg.get(key, "(unset)")
        differs = current != target
        print(f"{key:<32}{str(current):>16}{str(target):>14}"
              f"{'   <== will change' if differs else ''}")
        if differs:
            changes[key] = target

    if not changes:
        print("\nAlready aligned; nothing to write.")
        return 0

    if not a.apply:
        print(f"\n{len(changes)} setting(s) differ. Re-run with --apply to write them.")
        return 0

    cfg.update(changes)
    put(f"/api/v1/workflow/{a.workflow}", {"workflow_configurations": cfg})

    # Read back rather than trusting the write: a silently rejected field would
    # look exactly like success and cost another round of calls to notice.
    after = (V.get(f"/api/v1/workflow/fetch/{a.workflow}")
             .get("workflow_configurations") or {})
    bad = {k: (after.get(k), v) for k, v in changes.items() if after.get(k) != v}
    if bad:
        print(f"\nWROTE BUT DID NOT STICK: {bad}")
        return 1
    print(f"\napplied and verified: {json.dumps(changes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
