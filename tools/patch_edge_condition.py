"""Replace one edge's condition text on a Dograh workflow DRAFT.

Editing only touches the draft. Live telephony keeps serving the last published
version until `python tools/publish_workflow.py --workflow <id>` runs.

    python tools/patch_edge_condition.py --workflow 1 --from 2 --to 4 --file .tmp/edge.txt
    python tools/patch_edge_condition.py --workflow 1 --from 2 --to 4 --file .tmp/edge.txt --dry-run

Writes a timestamped backup of the whole definition before every write.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
import urllib.request

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

env: dict[str, str] = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
BASE = "https://voice.bswealthfinance.com"
KEY = env["DOGRAH_API_KEY"]


def req(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-Key": KEY}
    if data:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, required=True)
    ap.add_argument("--from", dest="src", required=True, help="source node id")
    ap.add_argument("--to", dest="dst", required=True, help="target node id")
    ap.add_argument("--file", required=True, help="UTF-8 file holding the new condition text")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    new_condition = Path(a.file).read_text(encoding="utf-8").strip()

    doc = req("GET", f"/api/v1/workflow/fetch/{a.workflow}")
    wd = doc["workflow_definition"]
    if isinstance(wd, str):
        wd = json.loads(wd)

    edge = next(
        (e for e in wd["edges"]
         if str(e.get("source")) == str(a.src) and str(e.get("target")) == str(a.dst)),
        None,
    )
    if edge is None:
        have = [(e.get("source"), e.get("target")) for e in wd["edges"]]
        sys.exit(f"edge {a.src}->{a.dst} not found; have {have}")

    before = (edge.get("data") or {}).get("condition", "") or ""
    print(f"workflow {a.workflow}  edge {a.src}->{a.dst}  {len(before)} -> {len(new_condition)} chars")
    print(f"\n--- before ---\n{before}")
    print(f"\n--- after ---\n{new_condition}")

    if a.dry_run:
        print("\ndry run, nothing written.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = Path("backups") / f"wf{a.workflow}_def_{stamp}.json"
    bak.parent.mkdir(exist_ok=True)
    bak.write_text(json.dumps(wd, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nbackup -> {bak}")

    edge.setdefault("data", {})["condition"] = new_condition
    req("PUT", f"/api/v1/workflow/{a.workflow}", {"workflow_definition": wd})

    check = req("GET", f"/api/v1/workflow/fetch/{a.workflow}")["workflow_definition"]
    if isinstance(check, str):
        check = json.loads(check)
    got = next(e for e in check["edges"]
               if str(e.get("source")) == str(a.src) and str(e.get("target")) == str(a.dst))
    ok = ((got.get("data") or {}).get("condition", "") or "") == new_condition
    print("readback:", "MATCHES" if ok else "!! DOES NOT MATCH - check the dashboard")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
