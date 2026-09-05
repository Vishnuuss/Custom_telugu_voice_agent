"""Reorder the qualification fields a Vaani agent works through.

The order is the order of `extraction_variables` on the start node.
`compile_prompt` reads it into `brief.field_names`, and `CallState.still_need`
walks it in that order -- so this list IS the shape of the call.

    python tools/set_field_order.py --workflow 2
    python tools/set_field_order.py --workflow 2 --apply

Why property_type moved to the front
------------------------------------
The client's instruction, on 31 Aug: "property type before, like house or
commercial, before keep it."

Run 336 is the argument for it. `property_type` sat third, was asked as a bare
"మీ ప్రాపర్టీ టైప్ ఏది?", and the caller answered:

    అంటే ఏదండీ ఏం చెప్పాలి ప్రాపర్టీ డిపెండ్ ఏంటి నాకు తెలీదు

-- what does property mean, what am I supposed to say, I don't know. The agent
then spent a three-sentence turn explaining the word, which is the longest turn
in the call and breaks the two-sentence rule outright.

Asked FIRST it is the easiest question on the list, because the answer is a
thing the caller can see. It also frames every question after it: a factory
owner and a flat owner are not having the same conversation, and knowing which
one you are talking to before you ask about money is the difference between a
qualification and an interrogation.

Every write is read back. `workflow_definition` has returned HTTP 200 for a
write that changed nothing before.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vaani_runs as V  # noqa: E402

# The order the caller is walked through. Names not listed keep their relative
# position at the end, so adding a field to the workflow never silently drops it.
ORDER = [
    "property_type",       # easiest to answer, and it frames everything after it
    "monthly_bill",        # the qualifying number, now asked in context
    "location",
    "roof_available",
    "customer_name",       # late on purpose: rapport is earned, not opened with
    "assessment_agreed",   # the close is always last
]


def put(path: str, body: dict):
    req = urllib.request.Request(
        f"{V.BASE}{path}", method="PUT",
        data=json.dumps(body).encode("utf-8"),
        headers={"X-API-Key": V.KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def definition_of(workflow: int) -> dict:
    wf = V.get(f"/api/v1/workflow/fetch/{workflow}")
    d = wf.get("workflow_definition")
    return json.loads(d) if isinstance(d, str) else (d or {})


def reorder(variables: list[dict]) -> list[dict]:
    rank = {name: i for i, name in enumerate(ORDER)}
    # Unlisted fields sort after every listed one, keeping their own order.
    return sorted(variables,
                  key=lambda v: (rank.get(v.get("name"), len(ORDER)),))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, default=2)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    defn = definition_of(a.workflow)
    touched = False
    for node in defn.get("nodes", []):
        variables = (node.get("data") or {}).get("extraction_variables") or []
        if not variables:
            continue
        before = [v.get("name") for v in variables]
        after = [v.get("name") for v in reorder(variables)]
        print(f"node {node.get('id')}")
        print(f"  now  : {before}")
        print(f"  want : {after}")
        if before != after:
            node["data"]["extraction_variables"] = reorder(variables)
            touched = True

    if not touched:
        print("\nalready in this order; nothing to write.")
        return 0
    if not a.apply:
        print("\n--- dry run. Re-run with --apply to write. ---")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = Path(".tmp") / f"fieldorder-backup-wf{a.workflow}-{stamp}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps(definition_of(a.workflow), ensure_ascii=False,
                                 indent=2), encoding="utf-8")
    print(f"\nbackup: {backup}")

    put(f"/api/v1/workflow/{a.workflow}", {"workflow_definition": defn})

    after = definition_of(a.workflow)
    got = [v.get("name")
           for n in after.get("nodes", [])
           for v in ((n.get("data") or {}).get("extraction_variables") or [])]
    want = [v.get("name")
            for n in defn.get("nodes", [])
            for v in ((n.get("data") or {}).get("extraction_variables") or [])]
    ok = got == want
    print(f"verified: {ok}")
    print(f"  server now: {got}")
    if not ok:
        print("!! read-back does not match. The write did NOT take effect.")
        return 1
    print("\nDRAFT updated. Publish before it reaches live calls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
