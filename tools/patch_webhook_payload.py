"""Add fields to a Dograh workflow's webhook payload_template.

The webhook node decides which extracted variables ever leave Dograh. Workflow 6
(investing) was extracting currently_investing / investment_type / interested and
then sending NONE of them: its template carried only run_id, phone, outcome and
lead_score. The dashboard therefore had nothing to show for an investing lead no
matter what the caller said, which is why it kept falling back to the loan
columns. Workflow 5 (solar) sends house_ownership / solar_planning the same way;
this is the same fix for a different business line.

Only ADDS or OVERWRITES the keys you name - every other key is left alone, and
the whole node is backed up to backups/ first.

    python tools/patch_webhook_payload.py --workflow 6 --dry-run
    python tools/patch_webhook_payload.py --workflow 6 \
        --set currently_investing=gathered_context.currently_investing

Editing only touches the DRAFT. Run tools/publish_workflow.py afterwards or live
calls keep using the old template.
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
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="key=source",
        help="key=source, where source is a template path such as "
             "gathered_context.summary. A bare literal (no dot) is sent as-is.",
    )
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    detail = req("GET", f"/api/v1/workflow/fetch/{a.workflow}")
    wd = detail["workflow_definition"]
    nodes = [n for n in wd.get("nodes", []) if n.get("type") == "webhook"]
    if len(nodes) != 1:
        print(f"expected exactly one webhook node, found {len(nodes)}")
        return 1
    node = nodes[0]
    template = dict(node["data"].get("payload_template") or {})

    # Backing up the whole node, not just the template: endpoint_url and the
    # API-key header live here too, and a bad PUT would take them with it.
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = Path("backups") / f"wf{a.workflow}_webhook_{stamp}.json"
    backup.parent.mkdir(exist_ok=True)
    backup.write_text(json.dumps(node, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"backed up the webhook node to {backup}")

    changes: list[str] = []
    for pair in a.set:
        if "=" not in pair:
            print(f"--set needs key=source, got {pair!r}")
            return 1
        key, source = pair.split("=", 1)
        key, source = key.strip(), source.strip()
        # A source with a dot is a template path; anything else is a literal
        # (that is how `vertical` is set to the plain word "investing").
        value = f"{{{{{source}}}}}" if "." in source else source
        before = template.get(key)
        if before == value:
            print(f"  = {key} already {value}")
            continue
        template[key] = value
        changes.append(f"  {'~' if before else '+'} {key}: {before!r} -> {value}")

    if not changes:
        print("nothing to change")
        return 0
    print("\n".join(changes))

    if a.dry_run:
        print("\ndry run: nothing written")
        return 0

    node["data"]["payload_template"] = template
    req("PUT", f"/api/v1/workflow/{a.workflow}", {"workflow_definition": wd})
    print(f"\ndraft updated. Run: python tools/publish_workflow.py --workflow {a.workflow}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
