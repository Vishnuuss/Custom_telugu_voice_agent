"""Read and replace the knowledge base on a VAANI workflow.

    python tools/vaani_kb.py --workflow 2 --show
    python tools/vaani_kb.py --workflow 2 --file .tmp/kb.txt --dry-run
    python tools/vaani_kb.py --workflow 2 --file .tmp/kb.txt

The start node's `prompt` IS the knowledge base. `run_pipeline.build_vaani_prompt`
passes it to `VaaniBrief(products=...)`, and `compiler._business_layer` renders
it as Layer 3 under the heading "What we offer — FACTS YOU KNOW, NOT LINES YOU
SAY". Nothing else on the workflow feeds it.

Why this is not `tools/patch_node_prompt.py`
---------------------------------------------
That tool is hardcoded to `voice.bswealthfinance.com`, the OLD production Dograh
that still runs the client's live loan and investing agents. Pointing it at a
Vaani workflow id would edit whatever workflow happens to carry that id over
there. Vaani lives on a different host with a different key, so it gets its own
entry point rather than a flag that can be forgotten.

Every write saves the full previous definition to `.tmp/kb-backup-<ts>.json`
first, and prints a diff summary. Editing touches the DRAFT; live telephony
keeps serving the published version until `publish` runs.
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

ROOT = Path(__file__).resolve().parent.parent

env: dict[str, str] = {}
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

BASE = (env.get("VAANI_SERVER_API_URL")
        or "https://vaani.bswealthfinance.com").rstrip("/")
KEY = env["VAANI_SERVER_API_KEY"]


def api(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-Key": KEY}
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data,
                                 headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read().decode("utf-8", "replace")
    return json.loads(raw) if raw.strip() else {}


def fetch(workflow: int) -> dict:
    return api("GET", f"/api/v1/workflow/fetch/{workflow}")


def definition(record: dict) -> dict:
    defn = record.get("workflow_definition")
    return json.loads(defn) if isinstance(defn, str) else (defn or {})


def start_node(defn: dict) -> dict:
    """The node whose prompt is the knowledge base.

    A Vaani agent is single-node by construction (one `startCall`, zero edges --
    that is what makes the prompt compile once and never swap), so this is
    unambiguous. It still checks rather than taking nodes[0], because a
    misidentified node would silently write the knowledge base into a globals
    node and the agent would lose every fact it has.
    """
    nodes = defn.get("nodes") or []
    starts = [n for n in nodes if n.get("type") == "startCall"]
    if len(starts) == 1:
        return starts[0]
    with_prompt = [n for n in nodes if (n.get("data") or {}).get("prompt")]
    if len(with_prompt) == 1:
        return with_prompt[0]
    raise SystemExit(
        f"cannot identify the knowledge-base node: {len(starts)} startCall "
        f"node(s), {len(with_prompt)} node(s) with a prompt")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, required=True)
    ap.add_argument("--file", help="UTF-8 text file to install as the KB")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    record = fetch(a.workflow)
    defn = definition(record)
    node = start_node(defn)
    current = (node.get("data") or {}).get("prompt") or ""

    print(f"workflow {a.workflow}: {record.get('name')}")
    print(f"node       : {node.get('id')} ({node.get('type')})")
    print(f"current KB : {len(current):,} chars")

    if a.show or not a.file:
        print("\n" + "=" * 70)
        print(current)
        return 0

    new = Path(a.file).read_text(encoding="utf-8")
    print(f"new KB     : {len(new):,} chars  ({len(new) - len(current):+,})")
    if new.strip() == current.strip():
        print("identical -- nothing to do")
        return 0

    if a.dry_run:
        print("\n--- dry run, nothing written ---")
        print(new[:1500])
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = ROOT / ".tmp" / f"kb-backup-wf{a.workflow}-{stamp}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps(defn, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"backup     : {backup}")

    node.setdefault("data", {})["prompt"] = new
    api("PUT", f"/api/v1/workflow/{a.workflow}",
        {"workflow_definition": defn})

    # Read back. A 200 from this API has meant "changed nothing" before -- the
    # STT config write on 29 Aug returned 200 while writing to the wrong nesting
    # and the agent kept running the old model for hours.
    after = (start_node(definition(fetch(a.workflow))).get("data") or {}
             ).get("prompt") or ""
    ok = after.strip() == new.strip()
    print(f"verified   : {ok}  ({len(after):,} chars on the server)")
    if not ok:
        print("!! read-back does not match. The write did NOT take effect.")
        return 1
    print("\nDRAFT updated. Publish before it reaches live calls.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
