"""Capture EVERYTHING about a Dograh workflow to disk: prompts, edges, extraction
schema, model stack, turn-taking, voicemail, dictionary and the published version.

STRICTLY READ-ONLY. Only ever issues GET. It cannot change a workflow, so it is safe
to run against a live agent at any time.

Use it to freeze a known-good agent so it can be rebuilt or compared later:

    python tools/snapshot_workflow.py --workflow 5
    python tools/snapshot_workflow.py --workflow 5 6 --label golden
    python tools/snapshot_workflow.py --workflow 6 --out snapshots/

Writes two files per workflow into snapshots/:
  wf<N>_v<VER>_<STAMP>[_label].json  -- exact API payload, machine-restorable
  wf<N>_v<VER>_<STAMP>[_label].md    -- readable: every prompt and setting in full

API keys come back from the API masked (****...ZqOV), so neither file contains a
secret. The JSON is NOT directly re-postable for that reason -- treat it as the record
of what was set, and re-enter provider keys in the dashboard if you ever rebuild.
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


def _env() -> tuple[str, str]:
    import os

    env: dict[str, str] = {}
    p = Path(".env")
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    base = (os.environ.get("DOGRAH_BASE_URL") or env.get("DOGRAH_BASE_URL")
            or env.get("NEXT_PUBLIC_DOGRAH_API_URL") or "https://voice.bswealthfinance.com")
    key = os.environ.get("DOGRAH_API_KEY") or env.get("DOGRAH_API_KEY")
    if not key:
        sys.exit("DOGRAH_API_KEY must be set in .env")
    return base.rstrip("/"), key


BASE, KEY = _env()


def get(path: str):
    r = urllib.request.Request(f"{BASE}{path}", headers={"X-API-Key": KEY})
    with urllib.request.urlopen(r, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def published_version(wid: int) -> str:
    try:
        rows = get(f"/api/v1/workflow/{wid}/versions")
        rows = rows.get("versions", rows) if isinstance(rows, dict) else rows
        row = next((v for v in rows if v.get("status") == "published"), None)
        return str(row.get("version_number")) if row else "unknown"
    except Exception:
        return "unknown"


def md_report(wid: int, ver: str, wf: dict) -> str:
    cfg = wf.get("workflow_configurations") or {}
    defn = wf.get("workflow_definition") or {}
    nodes = defn.get("nodes") or []
    edges = defn.get("edges") or []
    pipe = ((cfg.get("model_configuration_v2_override") or {})
            .get("byok", {}).get("pipeline", {}))

    out: list[str] = []
    a = out.append
    a(f"# Workflow {wid} — {wf.get('name', '')}")
    a("")
    a(f"Published version at capture: **v{ver}**")
    a(f"Captured: {datetime.now().isoformat(timespec='seconds')}")
    a("")
    a("> Read-only snapshot. Provider API keys are masked by the API and are NOT here.")
    a("")

    a("## Model stack")
    a("")
    a("| Layer | Provider | Model | Detail |")
    a("|---|---|---|---|")
    for layer in ("llm", "stt", "tts"):
        v = dict(pipe.get(layer) or {})
        v.pop("api_key", None)
        prov = v.pop("provider", "")
        model = v.pop("model", "")
        rest = ", ".join(f"{k}={v[k]}" for k in sorted(v)) or "-"
        a(f"| {layer.upper()} | {prov} | `{model}` | {rest} |")
    a("")

    a("## Turn-taking and call settings")
    a("")
    a("| Setting | Value |")
    a("|---|---|")
    for k in ("turn_start_strategy", "turn_start_min_words", "smart_turn_stop_secs",
              "provisional_vad_pause_secs", "turn_stop_strategy",
              "max_user_idle_timeout", "max_call_duration",
              "context_compaction_enabled"):
        a(f"| `{k}` | {cfg.get(k)} |")
    a(f"| `voicemail_detection` | `{json.dumps(cfg.get('voicemail_detection'))}` |")
    a("")

    if cfg.get("dictionary"):
        a("## STT dictionary (keyterms)")
        a("")
        a("```")
        a(str(cfg["dictionary"]))
        a("```")
        a("")

    for extra in ("ambient_noise_configuration", "transcript_configuration",
                  "external_pbx_field_mappings"):
        if cfg.get(extra):
            a(f"## {extra}")
            a("")
            a("```json")
            a(json.dumps(cfg[extra], indent=2, ensure_ascii=False))
            a("```")
            a("")

    a("## Node prompts (verbatim, untruncated)")
    a("")
    for n in nodes:
        d = n.get("data") or {}
        a(f"### Node {n.get('id')} — {d.get('name')}  (`{n.get('type')}`)")
        a("")
        flags = {k: d.get(k) for k in ("add_global_prompt", "allow_interrupt",
                                       "is_start", "is_end") if d.get(k) is not None}
        if flags:
            a(f"Flags: `{json.dumps(flags)}`")
            a("")
        if d.get("prompt"):
            a(f"Prompt ({len(d['prompt'])} chars):")
            a("")
            a("```text")
            a(d["prompt"])
            a("```")
            a("")
        if d.get("extraction_prompt"):
            a("Extraction prompt:")
            a("")
            a("```text")
            a(d["extraction_prompt"])
            a("```")
            a("")
        if d.get("extraction_variables"):
            a("Extraction variables:")
            a("")
            a("```json")
            ev = d["extraction_variables"]
            a(ev if isinstance(ev, str) else json.dumps(ev, indent=2, ensure_ascii=False))
            a("```")
            a("")

    a("## Edges")
    a("")
    for e in edges:
        d = e.get("data") or {}
        a(f"- **{e.get('source')} -> {e.get('target')}**  `{d.get('label', '')}`")
        cond = d.get("condition")
        if cond:
            a(f"  - condition: {cond}")
    a("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, nargs="+", required=True)
    ap.add_argument("--out", default="snapshots")
    ap.add_argument("--label", help="suffix, e.g. 'golden'")
    a = ap.parse_args()

    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    for wid in a.workflow:
        wf = get(f"/api/v1/workflow/fetch/{wid}")
        ver = published_version(wid)
        suffix = f"_{a.label}" if a.label else ""
        stem = f"wf{wid}_v{ver}_{stamp}{suffix}"

        jp = outdir / f"{stem}.json"
        jp.write_text(json.dumps(wf, indent=2, ensure_ascii=False), encoding="utf-8")

        mp = outdir / f"{stem}.md"
        mp.write_text(md_report(wid, ver, wf), encoding="utf-8")

        nodes = len((wf.get("workflow_definition") or {}).get("nodes") or [])
        print(f"workflow {wid} (v{ver}): {nodes} nodes")
        print(f"  {jp}")
        print(f"  {mp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
