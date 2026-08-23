"""Show the most recent REAL phone calls (mode=vobiz) for a workflow, with transcript,
latency, which definition version served the call, and what was extracted.

Text-chat test sessions are excluded -- they pollute every summary otherwise.

    python tools/recent_calls.py --workflow 5 --n 8
"""

from __future__ import annotations

import argparse
import json
import statistics
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, default=5)
    ap.add_argument("--n", type=int, default=8)
    a = ap.parse_args()

    d = get(f"/api/v1/workflow/{a.workflow}/runs?page=1&limit=50")
    phone = [r for r in d.get("runs", []) if r.get("mode") != "textchat"]
    print(f"{len(phone)} real phone calls in the last 50 runs; showing {min(a.n, len(phone))}\n")

    for r in phone[:a.n]:
        det = get(f"/api/v1/workflow/{a.workflow}/runs/{r['id']}")
        gc = det.get("gathered_context") or {}
        ic = det.get("initial_context") or {}
        rc = ic.get("runtime_configuration") or {}
        ttfb, lat, tr, errs = [], [], [], []
        for e in (det.get("logs") or {}).get("realtime_feedback_events") or []:
            t, p = e.get("type") or "", e.get("payload") or {}
            if t == "rtf-ttfb-metric":
                ttfb.append(float(p["ttfb_seconds"]))
            elif t == "rtf-latency-measured":
                lat.append(float(p["latency_seconds"]))
            elif t == "rtf-bot-text":
                tr.append(("bot", p.get("text") or ""))
            elif t == "rtf-user-transcription":
                tr.append(("user", p.get("text") or ""))
            elif t == "rtf-node-transition":
                tr.append(("NODE", f"-> {p.get('node_name')}"))
            elif "error" in t.lower():
                errs.append(p.get("exception_message") or p.get("error"))

        print("=" * 78)
        print(f"RUN {r['id']}  {r['created_at'][:19]}  def={r.get('definition_id')}  "
              f"to={ic.get('phone_number')}")
        print(f"  disposition={gc.get('call_disposition')}  nodes={gc.get('nodes_visited')}  "
              f"dur={(det.get('cost_info') or {}).get('call_duration_seconds')}s")
        print(f"  stt={rc.get('stt_model')} tts={rc.get('tts_model')} llm={rc.get('llm_model')}")
        ex = {k: v for k, v in gc.items()
              if k in ("house_ownership", "solar_planning", "do_not_call", "lead_score",
                       "summary")}
        if ex:
            print(f"  extracted: {json.dumps(ex, ensure_ascii=False)[:260]}")
        if lat:
            print(f"  turn latency: n={len(lat)} p50={statistics.median(lat):.2f}s "
                  f"max={max(lat):.2f}s")
        if ttfb:
            print(f"  llm ttfb: p50={statistics.median(ttfb):.2f}s")
        for e in errs[:3]:
            print(f"  !! ERROR: {e}")
        for who, text in tr:
            print(f"    {who:5s}: {text}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
