"""Print the node prompts and edge conditions of a Dograh workflow, draft or published.

Live telephony serves the last PUBLISHED version, so always check which one you are
reading. --version picks a specific version_number; default is the live published one.

    python tools/show_graph.py --workflow 5
    python tools/show_graph.py --workflow 5 --version 55
    python tools/show_graph.py --workflow 5 --version 55 --full
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

env: dict[str, str] = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
BASE = "https://voice.bswealthfinance.com"
KEY = env["DOGRAH_API_KEY"]


def get(path: str):
    r = urllib.request.Request(f"{BASE}{path}", headers={"X-API-Key": KEY})
    with urllib.request.urlopen(r, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def versions(wid: int):
    rows = get(f"/api/v1/workflow/{wid}/versions")
    return rows.get("versions", rows) if isinstance(rows, dict) else rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, default=5)
    ap.add_argument("--version", type=int)
    ap.add_argument("--full", action="store_true", help="print prompts untruncated")
    ap.add_argument("--json", help="also write the raw definition to this path")
    a = ap.parse_args()

    rows = versions(a.workflow)
    if a.version:
        row = next((v for v in rows if v.get("version_number") == a.version), None)
    else:
        row = next((v for v in rows if v.get("status") == "published"), None)
    if not row:
        sys.exit("no such version")

    print(f"workflow {a.workflow}  v{row.get('version_number')}  {row.get('status')}  "
          f"published_at={row.get('published_at')}")

    defn = row.get("workflow_definition") or row.get("definition")
    if isinstance(defn, str):
        defn = json.loads(defn)
    if not defn:
        # The versions listing carries metadata only. The graph itself comes from
        # /workflow/fetch/{id}, which always returns the CURRENT DRAFT -- so this is
        # only equivalent to the published version when there is no open draft.
        detail = get(f"/api/v1/workflow/fetch/{a.workflow}")
        defn = detail.get("workflow_definition") or detail.get("definition")
        if isinstance(defn, str):
            defn = json.loads(defn)
        print("  (graph read from the live DRAFT via /workflow/fetch)")
    if not defn:
        sys.exit(f"could not read a definition off this version; keys={list(row.keys())}")

    if a.json:
        Path(a.json).write_text(json.dumps(defn, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        print(f"raw definition -> {a.json}")

    cut = 100000 if a.full else 1400
    for n in defn.get("nodes", []):
        d = n.get("data") or {}
        print("\n" + "=" * 78)
        print(f"NODE {n.get('id')}  type={n.get('type')}  name={d.get('name')}")
        print(f"  add_global_prompt={d.get('add_global_prompt')} "
              f"allow_interrupt={d.get('allow_interrupt')} "
              f"is_start={d.get('is_start')} is_end={d.get('is_end')}")
        if d.get("greeting_type") or d.get("greeting_text"):
            print(f"  greeting_type={d.get('greeting_type')} "
                  f"greeting_text={json.dumps(d.get('greeting_text'), ensure_ascii=False)}")
        if n.get("type") == "qa":
            print(f"  QA DATA: {json.dumps(d, ensure_ascii=False, indent=2)[:cut]}")
        for field in ("prompt", "delayed_start_prompt", "extraction_prompt",
                      "extraction_variables"):
            val = d.get(field)
            if val:
                if not isinstance(val, str):
                    val = json.dumps(val, ensure_ascii=False, indent=2)
                print(f"\n  --- {field} ({len(val)} chars) ---")
                print("  " + val[:cut].replace("\n", "\n  "))

    print("\n" + "=" * 78)
    print("EDGES")
    for e in defn.get("edges", []):
        d = e.get("data") or {}
        print(f"\n  {e.get('source')} -> {e.get('target')}  label={d.get('label')}")
        c = d.get("condition") or d.get("prompt") or ""
        print(f"    condition ({len(c)} chars): {c[:cut]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
