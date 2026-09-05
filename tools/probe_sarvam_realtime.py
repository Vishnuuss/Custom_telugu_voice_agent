"""Does saaras:v3-realtime actually send Telugu partials on phone audio?

Why this runs before any pipeline code
---------------------------------------
The whole remaining latency budget rests on one claim from a vendor doc: that
`saaras:v3-realtime` decodes incrementally and emits `transcript.partial` while
the caller is still speaking. If that is true, 0.373 s of sequential STT dead
time disappears and preemptive generation becomes possible for the first time.
If it is not true for TELUGU at 8 kHz over a phone line -- which is a much
narrower claim than the doc makes -- then rewriting the STT service buys
nothing and risks the one thing on this project that has always worked.

`saarika:v2.5`, which is what production runs today, has no partial path in
pipecat at all: `InterimTranscriptionFrame` is not even imported in its
service. So "Sarvam sends no partials" was a fact about the model in use, not
about Sarvam -- and it was written up this morning as the latter.

This replays a real caller recording at wall-clock speed, because the question
is specifically whether text arrives BEFORE the audio ends. Sending the file as
fast as the socket accepts it would answer a different and useless question.

    python tools/probe_sarvam_realtime.py
    python tools/probe_sarvam_realtime.py --file .tmp/audio/caller/wf1_run10.wav
"""

from __future__ import annotations

import argparse
import asyncio
import audioop
import base64
import json
import sys
import time
import wave
from pathlib import Path
from urllib.parse import urlencode

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

import websockets

BASE = "wss://api.sarvam.ai/speech-to-text-realtime/ws"
CHUNK_MS = 100


def env(name: str) -> str:
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(f"{name}=") and not line.startswith("#"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit(f"{name} not in .env")


def load(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as w:
        rate, width, chans = w.getframerate(), w.getsampwidth(), w.getnchannels()
        pcm = w.readframes(w.getnframes())
    if chans > 1:
        pcm = audioop.tomono(pcm, width, 0.5, 0.5)
    if width != 2:
        pcm = audioop.lin2lin(pcm, width, 2)
    if rate not in (8000, 16000):
        pcm, _ = audioop.ratecv(pcm, 2, 1, rate, 16000, None)
        rate = 16000
    return pcm, rate


async def run(path: Path, language: str, stream_type: str, quiet: bool = False,
              silence_ms: int = 500) -> int:
    pcm, rate = load(path)
    secs = len(pcm) / (2 * rate)
    query = urlencode({
        "model": "saaras:v3-realtime",
        "language_code": language,
        "mode": "transcribe",
        "stream_type": stream_type,
        "encoding": "linear16",
        "sample_rate": str(rate),
        # Sarvam's OWN server-side VAD gates finalisation. This is the number
        # that made the first probe wrong: it measured `vad.speech_end -> final`
        # at 0.12s and called that the STT cost -- but vad.speech_end itself
        # lags real speech end by exactly this window. The true figure is
        # silence_duration_ms + 0.12s, which at the 500ms default is ~0.62s,
        # WORSE than saarika's 0.373s. Live calls duly measured 1.5s / 1.0s /
        # 0.58s and the change was reverted.
        "silence_duration_ms": str(silence_ms),
    })
    print(f"{path.name}  {secs:.2f}s of {rate} Hz audio, stream_type={stream_type}\n")

    # Two numbers decide whether this model is worth switching to, and they
    # pull in opposite directions:
    #
    #   speech_end -> final   the STT dead time that disappears  (the win)
    #   last partial == final how often a speculative generation could be
    #                         REUSED rather than thrown away    (the catch)
    #
    # The catch is real and this probe already showed it once: one utterance
    # produced partials reading "అవును అవును" (yes yes) and a final reading
    # "నో నో నో ఐ డోంట్ హావ్" (no no no, I don't have). A speculation on that
    # partial would have generated a reply to the opposite answer. It could
    # never have been SPOKEN -- the coordinator releases buffered tokens only on
    # an exact match with the final -- so the cost is wasted tokens, not a wrong
    # answer. But it means the hit rate has to be measured, not assumed.
    partials = finals = 0
    first_partial_at = None
    last_partial = {}          # utterance_idx -> newest partial text
    gaps, matches, mismatches = [], 0, 0
    last_final_at = 0.0
    speech_end_at = {}
    started = time.monotonic()

    async with websockets.connect(
        f"{BASE}?{query}",
        additional_headers={"api-subscription-key": env("SARVAM_API_KEY")},
        max_size=None,
    ) as ws:

        async def send() -> None:
            step = int(rate * CHUNK_MS / 1000) * 2
            for i in range(0, len(pcm), step):
                # Wall-clock pacing. The question is whether text comes back
                # while the caller is still talking; firehosing the file would
                # answer a different question.
                await asyncio.sleep(CHUNK_MS / 1000)
                await ws.send(json.dumps({
                    "event": "audio_input",
                    "audio": base64.b64encode(pcm[i:i + step]).decode(),
                }))
            sent_done["at"] = time.monotonic() - started
            await ws.send(json.dumps({"event": "audio_end"}))

        sent_done = {}
        task = asyncio.create_task(send())
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=secs + 20)
                msg = json.loads(raw)
                kind = msg.get("type") or msg.get("event") or "?"
                at = time.monotonic() - started
                text = json.dumps(msg, ensure_ascii=False)
                idx = msg.get("utterance_idx")
                body = (msg.get("text") or "").strip()
                if "partial" in kind:
                    partials += 1
                    first_partial_at = first_partial_at or at
                    if body:
                        last_partial[idx] = body
                    if not quiet:
                        print(f"  {at:6.2f}s  PARTIAL  {text[:150]}")
                elif "final" in kind:
                    finals += 1
                    last_final_at = at
                    if idx in speech_end_at:
                        gaps.append(at - speech_end_at[idx])
                    if last_partial.get(idx) == body:
                        matches += 1
                    else:
                        mismatches += 1
                        if not quiet:
                            print(f"           partial was {last_partial.get(idx)!r}")
                    if not quiet:
                        print(f"  {at:6.2f}s  FINAL    {text[:150]}")
                else:
                    if "speech_end" in kind:
                        speech_end_at[idx] = at
                    if not quiet:
                        print(f"  {at:6.2f}s  {kind:8} {text[:120]}")
        except (asyncio.TimeoutError, websockets.ConnectionClosed):
            pass
        finally:
            task.cancel()

    import statistics
    print(f"\n  audio {secs:.2f}s   partials {partials}   finals {finals}")
    if gaps:
        print(f"  speech_end -> final : p50 {statistics.median(gaps):.3f}s  "
              f"mean {statistics.mean(gaps):.3f}s  max {max(gaps):.3f}s"
              f"   (saarika:v2.5 measured 0.373s ttfb)")
    if gaps and sent_done.get("at") is not None and finals:
        print(f"  audio END -> last final : {last_final_at - sent_done['at']:.3f}s"
              f"   <- THE PRODUCTION NUMBER (saarika:v2.5 = 0.373s)")
    if matches + mismatches:
        rate = matches / (matches + mismatches)
        print(f"  last partial == final : {matches}/{matches+mismatches}"
              f" = {rate*100:.0f}%   <- the speculation hit rate")
    if partials and first_partial_at is not None and first_partial_at < secs:
        print(f"  FIRST PARTIAL at {first_partial_at:.2f}s -- while the caller "
              f"was still speaking. Preemptive generation is possible.")
        return 0
    print("  NO partial arrived before the audio ended. This model buys "
          "nothing here; do not rewrite the STT service.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=".tmp/audio/caller/wf1_run10.wav")
    ap.add_argument("--language", default="te-IN")
    ap.add_argument("--stream-type", default="fast")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--silence-ms", type=int, default=500)
    a = ap.parse_args()
    return asyncio.run(run(Path(a.file), a.language, a.stream_type, a.quiet,
                       a.silence_ms))


if __name__ == "__main__":
    raise SystemExit(main())
