"""Patch the runtime stack + turn-taking config on a Dograh workflow.

Prompts live in the graph (`workflow_definition`); latency and turn-taking live in
`workflow_configurations`. This tool only touches the latter.

VERIFIED 2026-08-19 on scratch workflow 8: this API preserves the real provider keys
when they are sent back as masks, so a read-modify-write is safe. Proven by changing
max_call_duration with masked keys and confirming the LLM still answered over text-chat.
Do NOT assume the same of /organizations/model-configurations/v2 -- that one is untested
and a bad write there takes every agent offline.

    python tools/patch_stack.py --workflow 8 --show
    python tools/patch_stack.py --workflow 8 --llm meta-llama/llama-4-scout-17b-16e-instruct
    python tools/patch_stack.py --workflow 8 --stt saarika:v2.5 --min-words 3
    python tools/patch_stack.py --workflow 8 --restore backups/wf8_cfg_before.json

Always writes a timestamped backup of the previous configuration first.
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
            or env.get("NEXT_PUBLIC_DOGRAH_API_URL"))
    key = os.environ.get("DOGRAH_API_KEY") or env.get("DOGRAH_API_KEY")
    if not base or not key:
        sys.exit("DOGRAH_BASE_URL and DOGRAH_API_KEY must be set")
    return base.rstrip("/"), key


BASE, KEY = _env()


def req(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-Key": KEY}
    if data:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def show(cfg: dict) -> None:
    pipe = ((cfg.get("model_configuration_v2_override") or {})
            .get("byok", {}).get("pipeline", {}))
    print("  stack:")
    for layer in ("llm", "tts", "stt"):
        v = dict(pipe.get(layer) or {})
        v.pop("api_key", None)
        print(f"    {layer:4s} {v}")
    print("  turn-taking:")
    for k in ("turn_start_strategy", "turn_start_min_words", "smart_turn_stop_secs",
              "provisional_vad_pause_secs", "turn_stop_strategy",
              "max_user_idle_timeout", "max_call_duration", "context_compaction_enabled"):
        print(f"    {k} = {cfg.get(k)}")
    print(f"    voicemail_detection = {json.dumps(cfg.get('voicemail_detection'))}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--llm")
    ap.add_argument("--tts")
    ap.add_argument("--stt")
    ap.add_argument("--tts-speed", type=float)
    ap.add_argument("--min-words", type=int)
    ap.add_argument("--turn-strategy")
    ap.add_argument("--stop-secs", type=float)
    ap.add_argument("--vad-pause", type=float,
                    help="provisional_vad_pause_secs; patch_turn_taking.py cannot write "
                         "this on a BYOK workflow because it omits the model override")
    ap.add_argument("--idle-timeout", type=float)
    ap.add_argument("--max-duration", type=int)
    ap.add_argument("--voicemail", choices=["on", "off"])
    ap.add_argument("--compaction", choices=["on", "off"])
    ap.add_argument("--restore", help="path to a saved configuration json")
    a = ap.parse_args()

    wid = a.workflow
    cfg = req("GET", f"/api/v1/workflow/fetch/{wid}")["workflow_configurations"]

    if a.show:
        print(f"workflow {wid} current configuration:")
        show(cfg)
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    Path("backups").mkdir(exist_ok=True)
    before = Path(f"backups/wf{wid}_cfg_{stamp}.json")
    before.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"backed up previous configuration -> {before}")

    if a.restore:
        new = json.loads(Path(a.restore).read_text(encoding="utf-8"))
    else:
        new = json.loads(json.dumps(cfg))
        pipe = (new.setdefault("model_configuration_v2_override", {})
                .setdefault("byok", {}).setdefault("pipeline", {}))
        if a.llm:
            pipe["llm"]["model"] = a.llm
        if a.tts:
            pipe["tts"]["model"] = a.tts
        if a.stt:
            pipe["stt"]["model"] = a.stt
        if a.tts_speed is not None:
            pipe["tts"]["speed"] = a.tts_speed
        if a.min_words is not None:
            new["turn_start_min_words"] = a.min_words
        if a.turn_strategy:
            new["turn_start_strategy"] = a.turn_strategy
        if a.stop_secs is not None:
            new["smart_turn_stop_secs"] = a.stop_secs
        if a.vad_pause is not None:
            new["provisional_vad_pause_secs"] = a.vad_pause
        if a.idle_timeout is not None:
            new["max_user_idle_timeout"] = a.idle_timeout
        if a.max_duration is not None:
            new["max_call_duration"] = a.max_duration
        if a.compaction:
            new["context_compaction_enabled"] = a.compaction == "on"
        if a.voicemail == "off":
            new["voicemail_detection"] = None
        elif a.voicemail == "on":
            # Mirrors WF1, the only config of this in the account that has run live.
            # use_workflow_llm lets the workflow LLM judge the greeting, which is what
            # catches mixed Telugu/English voicemail prompts ("The person you are trying
            # to reach is not available" + Telugu tone message) -- seen on WF5 run 1624,
            # where the agent answered the voicemail and scored it user_qualified.
            new["voicemail_detection"] = {"enabled": True, "use_workflow_llm": True,
                                          "long_speech_timeout": 4}

    req("PUT", f"/api/v1/workflow/{wid}", {"workflow_configurations": new})
    after = req("GET", f"/api/v1/workflow/fetch/{wid}")["workflow_configurations"]
    print(f"\nworkflow {wid} AFTER:")
    show(after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
