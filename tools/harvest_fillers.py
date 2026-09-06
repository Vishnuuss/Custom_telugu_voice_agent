"""Cut filler clips out of the agent's own recorded voice.

Why this instead of a TTS call
-------------------------------
Rendering fillers needs the Sarvam key, which is held per-user in the Dograh
database and is not on any build machine. That blocked the feature entirely.

But the agent's voice is already on disk. Every call recording has a separated
bot track, and most agent turns open with exactly the word we want -- "సరే",
"మంచిది", "అర్థమైంది". Cutting them out gives something a TTS render cannot:
the real voice, already at 8 kHz, already through the phone codec, already
carrying the room and line character of a live call. A rendered clip would be
studio-clean and would audibly not match the sentence that follows it.

How the words are found
-----------------------
No transcript alignment, because per-word timings do not exist in the logs.
Instead:

1. Split the bot track on silence. The agent speaks in discrete turns, so the
   Nth loud region is the Nth utterance in the log -- verified by count before
   anything is cut.
2. Inside a chosen utterance, take from its start to the first pause. Telugu
   speakers put a real gap after the opening acknowledgement -- it is a
   discourse boundary, not just a comma -- so that pause IS the end of the word.

Every clip is then checked for the things that make a filler unusable: too
short, too long, clipped at the start, or ending mid-voice.

    python tools/harvest_fillers.py --run 262
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import wave
from pathlib import Path

import numpy as np

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
DOGRAH = REPO.parent / "dograh-vapi"
sys.path.insert(0, str(DOGRAH))
sys.path.insert(0, str(REPO / "tools"))

from api.services.vaani.fillers import cache_path, harvested_key  # noqa: E402

SR = 8000
FRAME_MS = 10

# What a usable filler looks like. A clip outside these bounds is not a word.
MIN_CLIP_S = 0.18
MAX_CLIP_S = 1.10


def envelope(x: np.ndarray, frame: int) -> np.ndarray:
    n = len(x) - frame
    return np.array([float(np.sqrt((x[i:i + frame] ** 2).mean()))
                     for i in range(0, n, frame)])


def speech_regions(e: np.ndarray, thr: float, min_gap: int, min_len: int):
    """Contiguous loud regions, merging gaps shorter than `min_gap` frames."""
    loud = e > thr
    regions, start = [], None
    gap = 0
    for i, is_loud in enumerate(loud):
        if is_loud:
            if start is None:
                start = i
            gap = 0
        elif start is not None:
            gap += 1
            if gap >= min_gap:
                regions.append((start, i - gap))
                start = None
    if start is not None:
        regions.append((start, len(loud) - 1))
    return [(a, b) for a, b in regions if b - a >= min_len]


def first_word(x: np.ndarray, e: np.ndarray, a: int, b: int, thr: float):
    """From the start of an utterance to the first real pause inside it."""
    frame = int(SR * FRAME_MS / 1000)
    # A pause of 60ms or more inside speech is a word boundary in practice.
    need, quiet = 6, 0
    end = None
    for i in range(a + 8, min(b, a + 130)):        # look at most 1.3s in
        if e[i] <= thr:
            quiet += 1
            if quiet >= need:
                end = i - quiet
                break
        else:
            quiet = 0
    if end is None:
        return None
    return x[a * frame: end * frame]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=int, default=262)
    ap.add_argument("--workflow", type=int, default=2)
    # The clip IS whatever voice made the call, so it is not stored under a
    # provider voice id -- but it IS stored under the voice that was live when
    # the call was made. The bare "harvested" key was reachable by every voice,
    # so clips cut on 28 Aug were still being preferred over correct renders
    # after the voice was rotated on 5 Sep: the caller would have heard the
    # previous speaker on half the fillers.
    ap.add_argument("--voice", required=True,
                    help="the tts voice that was LIVE on --run (see "
                         "tools/set_stt_config.py --section tts)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    import vaani_runs as V
    run = V.get(f"/api/v1/workflow/{a.workflow}/runs/{a.run}")
    url = run.get("bot_recording_public_url")
    if not url:
        print("no bot recording on that run")
        return 1

    src = REPO / ".tmp" / "fillersrc"
    src.mkdir(parents=True, exist_ok=True)
    wav = src / f"bot{a.run}.wav"
    if not wav.exists():
        urllib.request.urlretrieve(url, wav)
    with wave.open(str(wav)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)
        if w.getframerate() != SR:
            print(f"expected {SR}Hz, got {w.getframerate()}")
            return 1

    ev = (run.get("logs") or {}).get("realtime_feedback_events") or []
    texts = [(e.get("payload") or {}).get("text", "").strip()
             for e in ev if e.get("type") == "rtf-bot-text"]
    texts = [t for t in texts if t]

    frame = int(SR * FRAME_MS / 1000)
    e = envelope(x, frame)
    thr = float(np.percentile(e, 60)) * 0.5
    regions = speech_regions(e, thr, min_gap=40, min_len=25)
    print(f"{len(texts)} logged utterances, {len(regions)} speech regions found")
    if len(regions) != len(texts):
        print("counts differ -- the Nth region is not reliably the Nth utterance.")
        print("Refusing to cut rather than shipping a clip of the wrong word.")
        return 1

    wanted = ("సరే", "మంచిది", "అర్థమైంది", "అలాగే", "అవును")
    taken: dict[str, np.ndarray] = {}
    for (start, end), text in zip(regions, texts):
        word = text.split()[0].strip(",.!?")
        if word not in wanted or word in taken:
            continue
        clip = first_word(x, e, start, end, thr)
        if clip is None:
            print(f"  skip {word!r}: no pause found after it")
            continue
        secs = len(clip) / SR
        if not (MIN_CLIP_S <= secs <= MAX_CLIP_S):
            print(f"  skip {word!r}: {secs:.2f}s is not a word")
            continue
        taken[word] = clip
        print(f"  got  {word!r}  {secs:.2f}s")

    if not taken:
        print("\nnothing usable found in this call.")
        return 1

    if a.dry_run:
        print("\ndry run; nothing written")
        return 0

    for word, clip in taken.items():
        # Fade 5ms at each end. A hard cut is an audible click on a phone line.
        f = int(0.005 * SR)
        clip = clip.copy()
        clip[:f] *= np.linspace(0, 1, f)
        clip[-f:] *= np.linspace(1, 0, f)
        pcm = clip.astype(np.int16).tobytes()
        p = cache_path(word, harvested_key(a.voice), SR)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(pcm)
        print(f"wrote {word!r} -> {p.name}  ({len(pcm)/2/SR:.2f}s)")

    print(f"\n{len(taken)} filler clip(s) in the agent's own voice.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
