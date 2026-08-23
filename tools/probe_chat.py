"""Send ONE text-chat turn and print the raw response, with no polling loop.

The eval harness polls until a NEW assistant message appears, which turns "the model is
broken" into "the harness hangs". This shows what the API actually returns.

    python tools/probe_chat.py --workflow 5 --say "హలో"
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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


def req(method: str, path: str, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-API-Key": KEY}
    if data:
        headers["Content-Type"] = "application/json"
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", required=True)
    ap.add_argument("--say", default="హలో")
    a = ap.parse_args()
    wid = a.workflow

    t0 = time.time()
    st, s = req("POST", f"/api/v1/workflow/{wid}/text-chat/sessions", {})
    print(f"create session -> HTTP {st} in {time.time() - t0:.1f}s")
    if not isinstance(s, dict):
        print(s[:1000])
        return 1
    rid = s.get("workflow_run_id") or s.get("id")
    print("run_id:", rid)
    print("session state:", s.get("state"), "| is_completed:", s.get("is_completed"))
    msgs = (s.get("session_data") or {}).get("messages") or []
    print(f"messages after create: {len(msgs)}")
    for m in msgs[-3:]:
        print("   ", m.get("role"), ":", str(m.get("content"))[:200])

    t0 = time.time()
    st, r = req("POST", f"/api/v1/workflow/{wid}/text-chat/sessions/{rid}/messages",
                {"text": a.say})
    print(f"\nsend '{a.say}' -> HTTP {st} in {time.time() - t0:.1f}s")
    if isinstance(r, dict):
        msgs = (r.get("session_data") or {}).get("messages") or []
        print(f"messages now: {len(msgs)}")
        for m in msgs[-4:]:
            print("   ", m.get("role"), ":", str(m.get("content"))[:300])
        gc = r.get("gathered_context") or {}
        print("nodes_visited:", gc.get("nodes_visited"))
    else:
        print("RAW:", str(r)[:1500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
