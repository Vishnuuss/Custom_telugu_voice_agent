"""Pull recent Dograh runs for a workflow and report health: dispositions, node paths,
latency, token spend and full transcripts.

Read-only. Never dials, never writes to Dograh.

    python tools/analyze_runs.py --workflow 5                  # summary of last 50 runs
    python tools/analyze_runs.py --workflow 5 --pages 3        # go further back
    python tools/analyze_runs.py --workflow 5 --transcripts 8  # dump 8 real conversations
    python tools/analyze_runs.py --run 1221                    # one run in full detail

Reads DOGRAH_BASE_URL / DOGRAH_API_KEY from .env (NEXT_PUBLIC_DOGRAH_API_URL accepted).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path


def force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


force_utf8()


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


BASE, KEY = "", ""


def get(path: str):
    r = urllib.request.Request(f"{BASE}{path}", headers={"X-API-Key": KEY}, method="GET")
    with urllib.request.urlopen(r, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def fetch_runs(workflow: int, pages: int) -> list[dict]:
    out: list[dict] = []
    for page in range(1, pages + 1):
        d = get(f"/api/v1/workflow/{workflow}/runs?page={page}&limit=50")
        rows = d.get("runs", []) if isinstance(d, dict) else d
        if not rows:
            break
        out.extend(rows)
        if isinstance(d, dict) and page >= d.get("total_pages", 1):
            break
    return out


def hydrate(workflow: int, runs: list[dict]) -> list[dict]:
    """The list endpoint omits logs.realtime_feedback_events, so transcripts and latency
    are invisible there. Fetch detail only for runs that actually entered the graph --
    busy/no-answer rows have nothing to say and each fetch is a round trip."""
    out = []
    for r in runs:
        gc = r.get("gathered_context") or {}
        if not gc.get("nodes_visited"):
            out.append(r)
            continue
        try:
            out.append(get(f"/api/v1/workflow/{workflow}/runs/{r['id']}"))
        except Exception as exc:  # noqa: BLE001 - a bad row must not kill the report
            print(f"  (could not fetch run {r['id']}: {exc})", file=sys.stderr)
            out.append(r)
    return out


def events_of(run: dict) -> list[dict]:
    return (run.get("logs") or {}).get("realtime_feedback_events") or []


def metrics(run: dict) -> dict:
    """Pull latency, transcript and error events out of one run."""
    ttfb: list[float] = []
    lat: list[float] = []
    transcript: list[tuple[str, str]] = []
    errors: list[dict] = []
    for e in events_of(run):
        t = e.get("type") or ""
        p = e.get("payload") or {}
        try:
            if t == "rtf-ttfb-metric":
                ttfb.append(float(p["ttfb_seconds"]))
            elif t == "rtf-latency-measured":
                lat.append(float(p["latency_seconds"]))
            elif t == "rtf-bot-text":
                transcript.append(("bot", p.get("text") or ""))
            elif t == "rtf-user-transcription":
                transcript.append(("user", p.get("text") or ""))
            elif t == "rtf-node-transition":
                transcript.append(("NODE", f"-> {p.get('node_name')}"))
            elif "error" in t.lower():
                errors.append(e)
        except (KeyError, TypeError, ValueError):
            continue
    return {"ttfb": ttfb, "latency": lat, "transcript": transcript, "errors": errors}


def pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    i = min(len(xs) - 1, int(q * len(xs)))
    return xs[i]


def summarize(runs: list[dict]) -> None:
    print(f"\n{'=' * 78}\nANALYZED {len(runs)} RUNS  "
          f"({runs[-1]['created_at'][:16]} .. {runs[0]['created_at'][:16]} UTC)\n{'=' * 78}")

    disp = Counter()
    paths = Counter()
    by_day = defaultdict(Counter)
    all_ttfb: list[float] = []
    all_lat: list[float] = []
    talked: list[dict] = []
    error_types = Counter()

    for r in runs:
        gc = r.get("gathered_context") or {}
        d = gc.get("call_disposition") or "none"
        disp[d] += 1
        by_day[r["created_at"][:10]][d] += 1
        nv = gc.get("nodes_visited")
        paths[" > ".join(nv) if nv else "(never entered graph)"] += 1

        m = metrics(r)
        all_ttfb.extend(m["ttfb"])
        all_lat.extend(m["latency"])
        for e in m["errors"]:
            error_types[e.get("type")] += 1
        if any(w == "user" for w, _ in m["transcript"]):
            talked.append(r)

    print("\nDISPOSITIONS")
    for k, v in disp.most_common():
        print(f"  {v:4d}  {v / len(runs) * 100:5.1f}%  {k}")

    print("\nNODE PATHS")
    for k, v in paths.most_common(10):
        print(f"  {v:4d}  {k}")

    print("\nBY DAY (UTC)")
    for day in sorted(by_day, reverse=True):
        row = ", ".join(f"{k}={v}" for k, v in by_day[day].most_common())
        print(f"  {day}  n={sum(by_day[day].values()):3d}  {row}")

    print(f"\nCONNECTED CALLS WITH REAL SPEECH: {len(talked)} of {len(runs)}")

    print("\nLATENCY (across all analyzed runs)")
    for name, xs in (("llm ttfb (s)", all_ttfb), ("turn latency (s)", all_lat)):
        if not xs:
            print(f"  {name}: none recorded")
            continue
        print(f"  {name}: n={len(xs)} min={min(xs):.2f} p50={pct(xs, .5):.2f} "
              f"p90={pct(xs, .9):.2f} p95={pct(xs, .95):.2f} max={max(xs):.2f}")

    if error_types:
        print("\nERROR EVENTS")
        for k, v in error_types.most_common():
            print(f"  {v:4d}  {k}")

    qual = [r for r in runs
            if (r.get("gathered_context") or {}).get("call_disposition") == "user_qualified"]
    print(f"\nQUALIFIED: {len(qual)}  "
          f"({len(qual) / max(1, len(talked)) * 100:.0f}% of calls where someone spoke)")

    print("\nEXTRACTED VARIABLES on calls where someone spoke")
    keys = Counter()
    for r in talked:
        gc = r.get("gathered_context") or {}
        for k, v in gc.items():
            if k in ("nodes_visited", "provider", "call_id", "call_tags",
                     "call_disposition", "mapped_call_disposition"):
                continue
            keys[f"{k}={json.dumps(v, ensure_ascii=False)[:40]}"] += 1
    for k, v in keys.most_common(20):
        print(f"  {v:3d}  {k}")


def dump_transcripts(runs: list[dict], n: int) -> None:
    talked = [r for r in runs
              if any(w == "user" for w, _ in metrics(r)["transcript"])]
    print(f"\n\n{'#' * 78}\n# {min(n, len(talked))} REAL CONVERSATIONS\n{'#' * 78}")
    for r in talked[:n]:
        show_run(r)


def show_run(r: dict) -> None:
    gc = r.get("gathered_context") or {}
    ic = r.get("initial_context") or {}
    m = metrics(r)
    print(f"\n{'-' * 78}\nRUN {r['id']}  {r['created_at'][:19]}  mode={r.get('mode')}")
    print(f"  to={ic.get('phone_number')} name={ic.get('customer_name')} "
          f"vertical={ic.get('vertical')}")
    rc = ic.get("runtime_configuration") or {}
    print(f"  stack: stt={rc.get('stt_provider')}/{rc.get('stt_model')} "
          f"tts={rc.get('tts_provider')}/{rc.get('tts_model')} "
          f"llm={rc.get('llm_provider')}/{rc.get('llm_model')}")
    print(f"  disposition={gc.get('call_disposition')} nodes={gc.get('nodes_visited')}")
    print(f"  duration={(r.get('cost_info') or {}).get('call_duration_seconds')}s")
    extracted = {k: v for k, v in gc.items()
                 if k not in ("nodes_visited", "provider", "call_id", "call_tags",
                              "call_disposition", "mapped_call_disposition")}
    if extracted:
        print(f"  extracted: {json.dumps(extracted, ensure_ascii=False)[:400]}")

    usage = (r.get("usage_info") or {}).get("llm") or {}
    bot_turns = max(1, sum(1 for w, _ in m["transcript"] if w == "bot"))
    for svc, u in usage.items():
        print(f"  tokens {svc.split('|||')[-1]}: prompt={u.get('prompt_tokens')} "
              f"completion={u.get('completion_tokens')} "
              f"({u.get('completion_tokens', 0) // bot_turns}/reply over {bot_turns})")

    for name, xs in (("ttfb", m["ttfb"]), ("turn latency", m["latency"])):
        if xs:
            print(f"  {name}: n={len(xs)} p50={pct(xs, .5):.2f} p95={pct(xs, .95):.2f} "
                  f"max={max(xs):.2f}")
    for e in m["errors"][:5]:
        print(f"  !! {json.dumps(e, ensure_ascii=False)[:300]}")

    print("  TRANSCRIPT")
    for who, text in m["transcript"]:
        print(f"    {who:5s}: {text}")


def main() -> int:
    global BASE, KEY
    BASE, KEY = _env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, default=5)
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--transcripts", type=int, default=0)
    ap.add_argument("--run", type=int, help="show one run id in full")
    ap.add_argument("--day", help="keep only runs created on this UTC date, e.g. 2026-08-19")
    a = ap.parse_args()

    if a.run:
        d = get(f"/api/v1/workflow/{a.workflow}/runs/{a.run}")
        show_run(d)
        return 0

    runs = fetch_runs(a.workflow, a.pages)
    if a.day:
        runs = [r for r in runs if (r.get("created_at") or "").startswith(a.day)]
    if not runs:
        print("no runs")
        return 1
    print(f"hydrating {sum(1 for r in runs if (r.get('gathered_context') or {}).get('nodes_visited'))} "
          f"connected runs of {len(runs)} ...", file=sys.stderr)
    runs = hydrate(a.workflow, runs)
    summarize(runs)
    if a.transcripts:
        dump_transcripts(runs, a.transcripts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
