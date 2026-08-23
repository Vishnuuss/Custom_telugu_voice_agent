"""Change turn-taking / latency settings on a Dograh workflow, safely.

Why this exists: `workflow_configurations` also holds `model_configuration_v2_override`,
whose API keys come back from the API **masked** (`"****...MlsA"`). A naive
read-modify-write PUT sends those masks back and takes the agent offline. This tool never
sends that key, and verifies after every write that the model override survived.

Dry run by default. Nothing is written without --apply.

    python tools/patch_turn_taking.py 5                       # show current values
    python tools/patch_turn_taking.py 5 --smart-turn-stop 0.8 # preview the change
    python tools/patch_turn_taking.py 5 --smart-turn-stop 0.8 --apply

Turn-taking notes for Telugu, learned the hard way on run 1104:
  smart_turn_stop_secs below ~0.6 cuts callers off mid-sentence -- Telugu speakers pause
  inside a sentence far more than English speakers. 0.35 produced a caller repeatedly
  shouting "ఎందుకు కట్ చేస్తున్నావ్?" (why do you keep cutting me off).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Keys this tool is allowed to write. model_configuration_v2_override is deliberately
# absent -- it carries masked provider keys and must only be edited in the dashboard.
SAFE_KEYS = {
    "smart_turn_stop_secs",
    "provisional_vad_pause_secs",
    "turn_start_min_words",
    "turn_start_strategy",
    "turn_stop_strategy",
    "max_user_idle_timeout",
    "max_call_duration",
    "context_compaction_enabled",
    "dictionary",
    "ambient_noise_configuration",
    "transcript_configuration",
    "external_pbx_field_mappings",
}


def env() -> tuple[str, str]:
    e = {}
    p = Path(".env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                e[k.strip()] = v.strip().strip('"').strip("'")
    import os
    base = (os.environ.get("DOGRAH_BASE_URL") or e.get("DOGRAH_BASE_URL")
            or e.get("NEXT_PUBLIC_DOGRAH_API_URL") or "").rstrip("/")
    key = os.environ.get("DOGRAH_API_KEY") or e.get("DOGRAH_API_KEY") or ""
    if not base or not key:
        sys.exit("DOGRAH_BASE_URL and DOGRAH_API_KEY must be set")
    return base, key


BASE, KEY = "", ""


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-Key": KEY}
    if data:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        sys.exit(f"{method} {path} -> HTTP {exc.code}: {exc.read()[:400]!r}")


def fetch(wid: int) -> dict:
    return call("GET", f"/api/v1/workflow/fetch/{wid}")


def show(cfg: dict, label: str) -> None:
    print(f"  [{label}]")
    for k in sorted(SAFE_KEYS):
        if k in cfg and not isinstance(cfg[k], (dict, list)):
            print(f"    {k:30s} {cfg[k]}")
    mo = cfg.get("model_configuration_v2_override") or {}
    llm = (((mo.get("byok") or {}).get("pipeline") or {}).get("llm") or {})
    print(f"    {'model override':30s} {llm.get('provider')}/{llm.get('model')}")


def main() -> int:
    global BASE, KEY
    BASE, KEY = env()
    ap = argparse.ArgumentParser()
    ap.add_argument("workflow_id", type=int)
    ap.add_argument("--smart-turn-stop", type=float)
    ap.add_argument("--vad-pause", type=float)
    ap.add_argument("--min-words", type=int)
    ap.add_argument("--idle-timeout", type=float)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    wid = a.workflow_id
    doc = fetch(wid)
    cfg = doc.get("workflow_configurations") or {}
    print(f"workflow {wid}: {doc.get('name')}  (v{doc.get('version_number')}"
          f" {doc.get('version_status')})")
    show(cfg, "current")

    changes = {}
    for flag, key in (("smart_turn_stop", "smart_turn_stop_secs"),
                      ("vad_pause", "provisional_vad_pause_secs"),
                      ("min_words", "turn_start_min_words"),
                      ("idle_timeout", "max_user_idle_timeout")):
        val = getattr(a, flag)
        if val is not None and cfg.get(key) != val:
            changes[key] = val

    if not changes:
        print("\nno changes requested")
        return 0

    print("\nchanges:")
    for k, v in changes.items():
        print(f"    {k:30s} {cfg.get(k)}  ->  {v}")

    if not a.apply:
        print("\nDRY RUN - re-run with --apply to write")
        return 0

    # PROVEN 2026-08-15 on workflow 2: this backend REPLACES workflow_configurations
    # wholesale. Any model_configuration_v2_override not included in the payload is
    # destroyed -- and it cannot be included, because the API only ever returns its API
    # keys masked. There is no safe API path. Change turn-taking in the dashboard.
    if cfg.get("model_configuration_v2_override"):
        print("\n!! REFUSING TO WRITE.")
        print("!! This workflow has a per-workflow model override (BYOK). A PUT to")
        print("!! workflow_configurations REPLACES the whole object and will DESTROY it,")
        print("!! taking the agent off its configured model. The override cannot be sent")
        print("!! back because its API keys are returned masked.")
        print("!! Change these values in the Dograh dashboard instead:")
        for k, v in changes.items():
            print(f"!!     {k} -> {v}")
        return 3

    # Send only the safe subset, carrying existing values through so a replace-semantics
    # backend cannot silently drop them. model_configuration_v2_override is never sent.
    payload = {k: cfg[k] for k in cfg if k in SAFE_KEYS}
    payload.update(changes)
    call("PUT", f"/api/v1/workflow/{wid}", {"workflow_configurations": payload})

    after = (fetch(wid).get("workflow_configurations") or {})
    show(after, "after")

    mo = after.get("model_configuration_v2_override") or {}
    llm = (((mo.get("byok") or {}).get("pipeline") or {}).get("llm") or {})
    if not llm.get("model"):
        print("\n!! MODEL OVERRIDE WAS LOST BY THE WRITE - restore it in the dashboard NOW")
        return 2
    bad = [k for k, v in changes.items() if after.get(k) != v]
    if bad:
        print(f"\n!! these did not stick: {bad}")
        return 2
    print("\nOK - changes applied, model override intact")
    print("Remember to publish the workflow for this to affect live calls.")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
