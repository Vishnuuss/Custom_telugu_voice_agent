"""Render the Telugu filler bank to raw PCM, once, offline.

Why offline and not at call time
--------------------------------
The runtime must not depend on a TTS call to say a filler -- waiting for speech
synthesis is the exact thing the filler exists to hide. Rendering here means the
call path only ever does a disk read, so a filler cannot itself become latency,
and a TTS outage cannot break a call through this route.

The clips are keyed by voice. A filler in a different voice from the agent is
worse than no filler at all: the caller hears a second person. If the live voice
is changed, re-run this with --voice and the new name; unrendered voices simply
produce no fillers rather than the wrong ones.

    python tools/render_fillers.py --voice anushka
    python tools/render_fillers.py --list        # no API calls, just the plan
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request
import wave
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
DOGRAH = REPO.parent / "dograh-vapi"
sys.path.insert(0, str(DOGRAH))

from api.services.vaani.fillers import FILLERS, cache_path  # noqa: E402

API = "https://api.sarvam.ai/text-to-speech"
SR = 8000          # phone band; matches the transport, so no resampling at play time


def env(name: str) -> str:
    for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get(name, "")


def synthesise(text: str, key: str, voice: str) -> bytes:
    body = json.dumps({
        "inputs": [text],
        "target_language_code": "te-IN",
        "speaker": voice,
        "speech_sample_rate": SR,
        "model": "bulbul:v2",
    }).encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"api-subscription-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.loads(r.read().decode())
    import base64
    wav = base64.b64decode(payload["audios"][0])
    with wave.open(io.BytesIO(wav)) as w:
        if w.getframerate() != SR or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise RuntimeError(
                f"expected mono 16-bit {SR}Hz, got {w.getnchannels()}ch "
                f"{w.getsampwidth()*8}-bit {w.getframerate()}Hz")
        return w.readframes(w.getnframes())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="anushka")
    ap.add_argument("--list", action="store_true",
                    help="show what would be rendered; makes no API calls")
    a = ap.parse_args()

    if a.list:
        for t in FILLERS:
            p = cache_path(t, a.voice, SR)
            print(f"  {'cached' if p.exists() else '  TODO'}  {t!r}  -> {p.name}")
        return 0

    key = env("SARVAM_API_KEY")
    if not key:
        print("SARVAM_API_KEY is empty in .env -- cannot render.")
        return 1

    done = failed = skipped = 0
    for text in FILLERS:
        p = cache_path(text, a.voice, SR)
        if p.exists():
            skipped += 1
            continue
        try:
            pcm = synthesise(text, key, a.voice)
        except Exception as e:
            print(f"  FAILED {text!r}: {repr(e)[:160]}")
            failed += 1
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(pcm)
        print(f"  ok  {text!r}  {len(pcm)/2/SR:.2f}s  -> {p.name}")
        done += 1

    print(f"\n{done} rendered, {skipped} already cached, {failed} failed")
    if failed:
        print("Fillers with no clip are simply never played; the call is unaffected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
