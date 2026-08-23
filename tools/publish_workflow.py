"""Publish the current draft of a Dograh workflow so live calls start using it.

Editing a workflow only updates its DRAFT. Live telephony keeps serving the last
PUBLISHED version until this runs -- which is how workflow 5 sat on v43 for days while
edits piled up in the draft and nobody could see why calls had not changed.

Prints the version table before and after so the change is visible and reversible.

    python tools/publish_workflow.py --workflow 5
    python tools/publish_workflow.py --workflow 5 --dry-run
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


def req(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-Key": KEY}
    if data:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def versions(wid: int):
    rows = req("GET", f"/api/v1/workflow/{wid}/versions")
    return rows.get("versions", rows) if isinstance(rows, dict) else rows


def show(wid: int, label: str) -> None:
    print(f"\n{label}")
    for v in versions(wid)[:4]:
        print(f"   v{v.get('version_number'):<4} {v.get('status'):<10} "
              f"published_at={v.get('published_at')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    show(a.workflow, "BEFORE:")
    draft = [v for v in versions(a.workflow) if v.get("status") == "draft"]
    if not draft:
        print("\nno draft to publish - live already matches the latest version")
        return 0
    if a.dry_run:
        print(f"\ndry run: would publish v{draft[0].get('version_number')}")
        return 0

    req("POST", f"/api/v1/workflow/{a.workflow}/publish", {})
    show(a.workflow, "AFTER:")
    print("\nlive calls now use the newly published version.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
