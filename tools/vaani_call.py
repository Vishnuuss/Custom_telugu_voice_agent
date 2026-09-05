"""Place a single test call on the Vaani server.

`place_test_call.py` goes through the campaign CSV path, which needs a presigned
MinIO upload -- and the server hands back its INTERNAL `http://localhost:9000`
address, unreachable from here. `/api/v1/telephony/initiate-call` places one call
directly with no object storage involved, which is what a latency test wants.

    python tools/vaani_call.py --workflow 2 --phone +916302488456
"""
from __future__ import annotations

import argparse, json, sys, urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
env = {}
for line in Path(".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
BASE = env.get("VAANI_SERVER_API_URL", "https://vaani.bswealthfinance.com").rstrip("/")
KEY = env["VAANI_SERVER_API_KEY"]

ap = argparse.ArgumentParser()
ap.add_argument("--workflow", type=int, default=2)
ap.add_argument("--phone", required=True)
a = ap.parse_args()

payload = {"workflow_id": a.workflow, "phone_number": a.phone}
req = urllib.request.Request(
    f"{BASE}/api/v1/telephony/initiate-call",
    data=json.dumps(payload).encode(),
    headers={"X-API-Key": KEY, "Content-Type": "application/json",
             "Accept": "application/json"},
    method="POST")
try:
    with urllib.request.urlopen(req, timeout=60) as r:
        print(f"HTTP {r.status}")
        print(r.read().decode("utf-8", "replace"))
except urllib.error.HTTPError as e:
    print(f"HTTP {e.code}")
    print(e.read().decode("utf-8", "replace")[:600])
    sys.exit(1)
