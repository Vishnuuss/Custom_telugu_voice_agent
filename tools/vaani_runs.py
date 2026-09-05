"""Read runs from the VAANI server and decompose per-turn latency.

Unlike tools/recent_calls.py (which points at the old production Dograh at
voice.bswealthfinance.com), this talks to the new Vaani install and reports the
four numbers that actually matter for the budget:

    TOTAL          user stopped speaking -> first bot audio byte
    endpoint+STT   the part before the LLM is even asked  (TOTAL - LLM - LLM->audio)
    LLM            first token out of Groq                (rtf-ttfb-metric, llm)
    LLM->audio     first byte out of Cartesia             (rtf-ttfb-metric, tts)

    python tools/vaani_runs.py --workflow 2 --n 3
    python tools/vaani_runs.py --run 12 --transcript
"""
from __future__ import annotations

import argparse, json, statistics, sys, urllib.request
from collections import Counter
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

env = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

BASE = (env.get("VAANI_SERVER_API_URL") or "https://vaani.bswealthfinance.com").rstrip("/")
KEY = env["VAANI_SERVER_API_KEY"]


def get(path):
    r = urllib.request.Request(f"{BASE}{path}", headers={"X-API-Key": KEY})
    with urllib.request.urlopen(r, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def decompose(det):
    """Return (rows, totals) where each row is one measured turn.

    Grouped by TURN BOUNDARY, not by list index.

    The first version zipped three independent lists together -- every LLM ttfb
    against every TTS ttfb, in arrival order. That is only correct while each
    turn emits exactly one of each, and it does not: run 300 turn 15 produced
    two STT events and two LLM events (a retried hedge), after which every
    later row was reading another turn's numbers. The column looked bimodal,
    alternating 0.06 and 0.32 turn after turn, and the alternation was the
    lists sliding past each other.

    It cost real time. The "TTS 0.231s bimodal" reported on 28 August came from
    this, and so did a morning spent looking for a variance in Cartesia that
    was never there: measured properly, TTS first-audio is 0.046-0.063s on
    every single turn of run 300 and has never been a lever.

    `rtf-latency-measured` marks the end of a turn, so the ttfb events since
    the previous one belong to it -- which is what a turn is, and what the
    index was standing in for.
    """
    events = (det.get("logs") or {}).get("realtime_feedback_events") or []
    rows = []
    raw = {"llm": [], "tts": [], "stt": []}
    pending = {}
    for e in events:
        t, p = e.get("type") or "", e.get("payload") or {}
        if t == "rtf-ttfb-metric":
            svc = (p.get("service") or p.get("processor") or "").lower()
            v = float(p.get("ttfb_seconds", 0) or 0)
            # Order matters: "SarvamSTTService" contains the substring "tts",
            # so STT must be claimed before TTS is tested for. Getting this
            # backwards folded every STT reading into the TTS aggregate and
            # produced a "TTS 0.231s" that was mostly Sarvam.
            key = ("stt" if ("stt" in svc or "sarvam" in svc or "deepgram" in svc)
                   else "llm" if "llm" in svc
                   else "tts" if ("tts" in svc or "cartesia" in svc) else None)
            if key:
                raw[key].append(v)
                pending[key] = v          # last one wins: a retry supersedes
        elif t == "rtf-latency-measured":
            total = float(p.get("latency_seconds", 0) or 0)
            llm, tts, stt = pending.get("llm"), pending.get("tts"), pending.get("stt")
            head = total - (llm or 0) - (tts or 0)
            rows.append((total, head, llm, tts, stt))
            pending = {}
    return rows, raw


def fmt(v):
    return "  --  " if v is None else f"{v:6.3f}"


def show_run(wf, rid, transcript=False):
    det = get(f"/api/v1/workflow/{wf}/runs/{rid}")
    rows, raw = decompose(det)
    ic = det.get("initial_context") or {}
    cost = det.get("cost_info") or {}
    print(f"\n=== run {rid}  {det.get('name')} ===")
    print(f"  disposition : {det.get('call_disposition')}   duration={det.get('duration')}s")
    print(f"  mode        : {det.get('mode')}")
    if cost:
        print(f"  cost        : {json.dumps(cost)[:400]}")
    if rows:
        print("")
        print("  turn   TOTAL   endpoint     LLM     TTS   (STT)")
        for i, (tot, head, L, T, S) in enumerate(rows, 1):
            print(f"  {i:>4}  {fmt(tot)}   {fmt(head)}  {fmt(L)}  {fmt(T)}  {fmt(S)}")
        tot = [r[0] for r in rows]
        def col(n):
            vals = [r[n] for r in rows if r[n] is not None]
            return statistics.mean(vals) if vals else 0.0
        print(f"   avg  {statistics.mean(tot):6.3f}   {col(1):6.3f}"
              f"  {col(2):6.3f}  {col(3):6.3f}  {col(4):6.3f}")
        print(f"   p50 TOTAL {statistics.median(tot):.3f}   max {max(tot):.3f}")
    else:
        print("  NO rtf-latency-measured events -- not enough turns to measure")
        if raw["llm"] or raw["tts"]:
            print(f"  raw llm ttfb={raw['llm']}  tts ttfb={raw['tts']}")

    # token / cache accounting
    usage = []
    for e in (det.get("logs") or {}).get("realtime_feedback_events") or []:
        if (e.get("type") or "").endswith("usage") or "token" in (e.get("type") or ""):
            usage.append(e.get("payload"))
    if usage:
        print(f"  usage: {json.dumps(usage[-3:])[:600]}")

    print(f"\n  gathered: {json.dumps(det.get('gathered_context') or {}, ensure_ascii=False)[:600]}")

    if transcript:
        print("\n  --- transcript ---")
        for e in (det.get("logs") or {}).get("realtime_feedback_events") or []:
            t, p = e.get("type") or "", e.get("payload") or {}
            if t == "rtf-bot-text":
                print(f"   BOT  : {p.get('text','')}")
            elif t in ("rtf-user-text", "rtf-user-transcript", "rtf-user-transcription"):
                print(f"   USER : {p.get('text','')}")
    return det


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, default=2)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--run", type=int)
    ap.add_argument("--transcript", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.run:
        show_run(a.workflow, a.run, a.transcript)
        return

    d = get(f"/api/v1/workflow/{a.workflow}/runs?page=1&limit=50")
    runs = d.get("runs", d if isinstance(d, list) else [])
    print(f"{len(runs)} runs on workflow {a.workflow}")
    for r in runs[:15]:
        print(f"  id={r.get('id'):<5} {r.get('name'):<26} mode={r.get('mode'):<10} "
              f"disp={r.get('call_disposition')} dur={r.get('duration')}")
    if a.list:
        return
    phone = [r for r in runs if r.get("mode") != "textchat"]
    for r in phone[:a.n]:
        show_run(a.workflow, r["id"], a.transcript)


if __name__ == "__main__":
    main()
