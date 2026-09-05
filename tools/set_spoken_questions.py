"""Give each qualification field the words the caller actually hears.

Run 298 is what this is for. The agent asked "మీ నెలవారీ బిల్లు ఎంత?" -- "how
much is your monthly bill?" -- and the caller asked back, twice, which bill was
meant. He was right to: the sentence never says electricity. The agent was
reading out `extraction_variables[].prompt`, which the DTO documents as the
"Extraction Hint" ("Monthly electricity bill in rupees"), translating it live,
and dropping the one word that mattered.

`ask` now carries the spoken question and `prompt` goes back to being what it
says it is. The two texts are written for different readers -- one for a Telugu
caller on a phone, one for an extraction model -- and neither is improved by
being made to serve the other.

The wording rules these follow, which is why they read the way they do:

  - "కరెంట్ బిల్లు", not "విద్యుత్ బిల్లు". Nobody on a phone in Telangana says
    విద్యుత్; they say current, and the harvested transcripts agree.
  - Options are offered where the answer is a category, so the caller does not
    have to invent the format. The reference call the client supplied does this
    on every categorical question and ours did not.
  - No field presumes anything about the caller. "మీది సొంత ఇల్లా, అపార్ట్‌మెంటా,
    లేదా కమర్షియలా?" asks; "your house's bill" assumes.

    python tools/set_spoken_questions.py            # show the difference
    python tools/set_spoken_questions.py --apply    # write it
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

sys.path.insert(0, str(Path(__file__).resolve().parents[0]))
import vaani_runs as V  # noqa: E402

ASKS = {
    "monthly_bill":
        "మీ కరెంట్ బిల్లు నెలకి ఎంత వస్తుంది?",
    "location":
        "మీరు ఏ ఏరియా లేదా సిటీలో ఉంటున్నారు?",
    "property_type":
        "మీది సొంత ఇల్లా, అపార్ట్‌మెంటా, లేదా కమర్షియల్ ప్లేసా?",
    "roof_available":
        "మీకు సొంత రూఫ్ లేదా టెర్రస్ ఉందా?",
    "customer_name":
        "మీ పేరు చెప్పగలరా?",
    "assessment_agreed":
        "ఉచితంగా ఒక సైట్ సర్వే చేయించుకుంటారా?",
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
    definition = wf.get("workflow_definition")
    if isinstance(definition, str):
        definition = json.loads(definition)

    changed = 0
    for node in definition.get("nodes", []):
        for variable in (node.get("data", {}).get("extraction_variables") or []):
            want = ASKS.get(variable.get("name"))
            if not want:
                continue
            print(f"\n{variable['name']}")
            print(f"  spoken now : {variable.get('ask') or '(none -- reads the hint)'}")
            print(f"  hint       : {variable.get('prompt')}")
            print(f"  spoken new : {want}")
            if variable.get("ask") != want:
                variable["ask"] = want
                changed += 1

    if not changed:
        print("\nAlready set; nothing to write.")
        return 0
    if not a.apply:
        print(f"\n{changed} question(s) differ. Re-run with --apply to write them.")
        return 0

    put(f"/api/v1/workflow/{a.workflow}", {"workflow_definition": definition})

    # Read back rather than trust the write. A field the DTO silently drops --
    # which is exactly what `ask` would have been before today's schema change --
    # looks identical to success from here, and would cost another call to spot.
    after = V.get(f"/api/v1/workflow/fetch/{a.workflow}").get("workflow_definition")
    if isinstance(after, str):
        after = json.loads(after)
    live = {v.get("name"): v.get("ask")
            for n in after.get("nodes", [])
            for v in (n.get("data", {}).get("extraction_variables") or [])}
    bad = {k: (live.get(k), v) for k, v in ASKS.items()
           if k in live and live.get(k) != v}
    if bad:
        print(f"\nWROTE BUT DID NOT STICK: {json.dumps(bad, ensure_ascii=False)}")
        return 1
    print(f"\napplied and verified: {changed} question(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
