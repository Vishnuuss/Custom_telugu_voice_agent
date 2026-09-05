#!/usr/bin/env python
"""Hold a scripted conversation with a live Vaani agent and PRINT every turn.

`vaani_eval.py` scores. This one shows. When the client says "it is skipping
questions", "it is looping", "it cannot answer what I asked from the website",
the first thing needed is the transcript of it happening, not a pass/fail.

    python tools/vaani_probe.py --workflow 2 --say "హలో" "మీరు ఏమి సర్వీసెస్ ఇస్తారు?"
    python tools/vaani_probe.py --workflow 2 --script website
    python tools/vaani_probe.py --workflow 3 --script derail

Scripts are the client's own complaints, written as conversations:
  website     -- questions answerable only from the site
  derail      -- caller asks an unrelated question mid-qualification
  interrupt   -- caller changes their answer, then changes it again
  silly       -- "did you eat?", the stupid question that must still get an answer
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
env = {}
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")

BASE = (env.get("VAANI_SERVER_API_URL") or "https://vaani.bswealthfinance.com").rstrip("/")
KEY = env["VAANI_SERVER_API_KEY"]


def req(method: str, path: str, body=None, timeout=90):
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


def assistant_texts(payload) -> list[str]:
    """Replies live in session_data.turns[].assistant_message.text.

    `messages` exists and is always empty -- an earlier battery reported
    "NO REPLY" on every case because it read that one.
    """
    out = []
    for t in ((payload or {}).get("session_data") or {}).get("turns") or []:
        am = t.get("assistant_message") or {}
        if am.get("text"):
            out.append(" ".join(str(am["text"]).split()))
    return out


SCRIPTS = {
    # Everything here must be answerable from mbsolarhub.com alone.
    "website": [
        "హలో",
        "మీరు ఏమి సర్వీసెస్ ఇస్తారు?",
        "మా సొసైటీలో లిఫ్ట్ కి కరెంట్ బిల్లు ఎక్కువ వస్తుంది, మీరు హెల్ప్ చేస్తారా?",
        "వెండర్స్ ని ఎలా verify చేస్తారు?",
        "మీ ఆఫీస్ ఎక్కడ ఉంది?",
        "మీరే సోలార్ పెడతారా?",
    ],
    # The client: "if user asks another doubts it is looping".
    "derail": [
        "హలో",
        "నా పేరు రమేష్",
        "అసలు సబ్సిడీ ఎంత వస్తుంది?",
        "సరే, మా ఇల్లు విజయవాడలో ఉంది",
        "పానెల్ ఎన్ని సంవత్సరాలు వస్తుంది?",
        "బిల్లు దాదాపు మూడు వేలు వస్తుంది",
    ],
    # "if i tell something first it is considering it, if i try to change it,
    # it is not listening."
    "interrupt": [
        "హలో",
        "మాది సొంత ఇల్లు",
        "కాదు కాదు, సారీ, అది అపార్ట్మెంట్",
        "మా బిల్లు రెండు వేలు",
        "కాదు, తప్పు చెప్పాను, ఐదు వేలు వస్తుంది",
    ],
    # "i need it to answer user question even if they are stupid like did you eat".
    "silly": [
        "హలో",
        "మీరు భోజనం చేశారా?",
        "మీకు పెళ్లి అయిందా?",
        "సరే చెప్పండి, సోలార్ గురించి",
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow", type=int, default=2)
    ap.add_argument("--say", nargs="*")
    ap.add_argument("--script", choices=sorted(SCRIPTS))
    a = ap.parse_args()

    turns = a.say or SCRIPTS.get(a.script or "") or ["హలో"]

    st, s = req("POST", f"/api/v1/workflow/{a.workflow}/text-chat/sessions", {})
    if not isinstance(s, dict):
        print(f"session create HTTP {st}: {str(s)[:300]}")
        return 1
    rid = s.get("workflow_run_id") or s.get("id")
    print(f"\n=== workflow {a.workflow}   run {rid} ===\n")

    seen = assistant_texts(s)
    for t in seen:
        print(f"  BOT  : {t}")

    lats = []
    for i, turn in enumerate(turns, start=1):
        print(f"\n  YOU  : {turn}")
        t0 = time.time()
        st, r = req("POST",
                    f"/api/v1/workflow/{a.workflow}/text-chat/sessions/{rid}/messages",
                    {"text": turn})
        dt = time.time() - t0
        lats.append(dt)
        if not isinstance(r, dict):
            print(f"  ERR  : HTTP {st}: {str(r)[:300]}")
            return 1
        fresh = assistant_texts(r)[len(seen):]
        seen = assistant_texts(r)
        for t in fresh:
            print(f"  BOT  : {t}     [{dt:.2f}s]")
        if not fresh:
            print(f"  BOT  : <nothing>     [{dt:.2f}s]")
        if r.get("is_completed"):
            print("\n  -- call ended by the agent --")
            break

    if lats:
        lats_sorted = sorted(lats)
        print(f"\n  reply latency p50 {lats_sorted[len(lats)//2]:.2f}s  "
              f"max {max(lats):.2f}s   ({len(lats)} turns)")
    print(f"  run {rid}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
