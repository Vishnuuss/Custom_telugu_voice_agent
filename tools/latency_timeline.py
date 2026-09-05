#!/usr/bin/env python
"""Latency, per real phone call, over time — to answer "did it get worse, and when".

The client, 4 Sep: "5 days back latency was good ... you destroyed something
which fucked up latency". That is a question about a TREND, and every previous
latency tool in this repo answers a question about ONE call. So this walks every
run on every workflow, keeps the ones that are real telephony with measurable
turns, and prints them in date order with the component split.

Text-chat runs are excluded on purpose: they have no endpoint and no telephony,
so mixing them in would move the median for reasons that have nothing to do with
what a caller hears.

    python tools/latency_timeline.py
    python tools/latency_timeline.py --workflows 2 3 --min-turns 3
"""
from __future__ import annotations

import argparse
import importlib.util
import statistics
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vr", REPO / "tools" / "vaani_runs.py")
vr = importlib.util.module_from_spec(spec)
sys.argv = [sys.argv[0]]          # vaani_runs parses argv at import if run as main
spec.loader.exec_module(vr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflows", type=int, nargs="*", default=[2, 3, 4, 5, 6])
    ap.add_argument("--min-turns", type=int, default=2)
    a = ap.parse_args()

    rows = []
    for wf in a.workflows:
        try:
            listing = vr.get(f"/api/v1/workflow/{wf}/runs?page=1&limit=50")
        except Exception as e:
            print(f"wf{wf}: listing failed: {e}")
            continue
        runs = listing if isinstance(listing, list) else listing.get("runs", listing.get("items", []))
        for r in runs:
            if (r.get("mode") or "") == "textchat":
                continue
            rid = r.get("id")
            try:
                det = vr.get(f"/api/v1/workflow/{wf}/runs/{rid}")
            except Exception:
                continue
            turns, _ = vr.decompose(det)
            if not turns or len(turns) < a.min_turns:
                continue
            # decompose() yields tuples: (total, head/endpoint, llm, tts, stt)
            tot = [t[0] for t in turns if t[0]]
            end = [t[1] for t in turns if t[1]]
            llm = [t[2] for t in turns if t[2]]
            tts = [t[3] for t in turns if t[3]]
            stt = [t[4] for t in turns if t[4]]
            if not tot:
                continue
            rows.append({
                "wf": wf, "id": rid,
                "when": (det.get("created_at") or r.get("created_at") or "")[:16],
                "turns": len(tot),
                "p50": statistics.median(tot),
                "endpoint": statistics.median(end) if end else None,
                "llm": statistics.median(llm) if llm else None,
                "tts": statistics.median(tts) if tts else None,
                "stt": statistics.median(stt) if stt else None,
            })

    rows.sort(key=lambda x: x["when"])
    if not rows:
        print("no measurable real calls found")
        return 1

    print(f"\n{'when':17} {'wf':>3} {'run':>5} {'turns':>5} "
          f"{'p50':>7} {'endpt':>7} {'llm':>7} {'tts':>7} {'stt':>7}")
    print("-" * 74)
    for x in rows:
        def f(v):
            return f"{v:.3f}" if isinstance(v, (int, float)) else "  -  "
        print(f"{x['when']:17} {x['wf']:>3} {x['id']:>5} {x['turns']:>5} "
              f"{f(x['p50']):>7} {f(x['endpoint']):>7} {f(x['llm']):>7} "
              f"{f(x['tts']):>7} {f(x['stt']):>7}")

    allp = [x["p50"] for x in rows]
    print("-" * 74)
    print(f"{len(rows)} real calls   overall p50 {statistics.median(allp):.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
