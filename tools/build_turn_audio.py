"""Cut real caller audio into labelled turn-end / mid-turn clips.

This is the dataset the text classifier could not be built from.

Why audio
---------
The text model plateaued at 9% of turns at a safe threshold, because short
Telugu answers are genuinely ambiguous once written down: "మా" is a whole turn
in one call and the first word of a sentence in another. Falling intonation and
pause length separate them and neither survives transcription. That is why Smart
Turn is an audio model, and why Telugu -- which it does not cover -- needs one.

Where the labels come from, and why they are real
-------------------------------------------------
Not generated, not guessed. Each production run's event log records when a final
transcript arrived, which is a moment the caller HAD finished speaking. So:

    POSITIVE  the 1.5s of caller audio ending at a turn end
    NEGATIVE  a 1.5s window ending mid-utterance, before the caller stopped

The negatives are the important half. Sampling them from *inside* speech, at
least 0.6s before the turn actually ended, gives the model the exact decision it
faces at runtime: audio is arriving, is this person done? Silence-only negatives
would teach it to detect silence, which VAD already does.

Windows are taken from the SEPARATED caller track, so the agent's voice is never
in frame.

    python tools/build_turn_audio.py --limit 400
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

WINDOW_S = 1.5          # what the model sees
MIN_NEG_OFFSET = 0.6    # a negative must end this far before the real turn end
SR = 8000               # phone band; production audio is already 8 kHz


def read_wav(path: Path):
    with wave.open(str(path)) as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            return None, 0
        n = w.getnframes()
        return w.readframes(n), w.getframerate()


def write_wav(path: Path, frames: bytes, rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)


def slice_ending_at(frames: bytes, rate: int, end_s: float):
    """The WINDOW_S of audio ending at end_s, or None if it does not fit."""
    end = int(end_s * rate) * 2
    start = end - int(WINDOW_S * rate) * 2
    if start < 0 or end > len(frames):
        return None
    return frames[start:end]


def turn_ends(run: dict) -> list[tuple[float, float]]:
    """(speech_start, speech_end) for each finalised caller utterance.

    Times are relative to the start of the recording, which is why the first
    event's timestamp is the reference point rather than wall clock.
    """
    events = (run.get("logs") or {}).get("realtime_feedback_events") or []
    if not events:
        return []
    from datetime import datetime

    def ts(x):
        return datetime.fromisoformat(str(x).replace("Z", "+00:00")).timestamp()

    try:
        t0 = ts(events[0].get("timestamp"))
    except Exception:
        return []
    out = []
    for e in events:
        if e.get("type") != "rtf-user-transcription":
            continue
        p = e.get("payload") or {}
        if not p.get("final"):
            continue
        try:
            start = ts(p.get("timestamp")) - t0
            end = ts(p.get("end_timestamp") or e.get("timestamp")) - t0
        except Exception:
            continue
        if end > start >= 0:
            out.append((start, end))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", default=".tmp/audio/caller")
    ap.add_argument("--runs", default=".tmp/harvest/runs")
    ap.add_argument("--out", default=".tmp/audio/dataset")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()

    wavs = sorted(Path(a.audio).glob("*.wav"))
    if a.limit:
        wavs = wavs[: a.limit]
    out = Path(a.out)
    print(f"{len(wavs)} caller recording(s)\n", flush=True)

    pos = neg = skipped = 0
    index = []
    for n, wav in enumerate(wavs, 1):
        stem = wav.stem                       # wf5_run2086
        try:
            wf, run_id = stem.split("_run")
            wf = wf.replace("wf", "")
        except ValueError:
            continue
        meta = Path(a.runs) / f"{wf}_{run_id}.json"
        if not meta.exists():
            skipped += 1
            continue
        try:
            run = json.loads(meta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            skipped += 1
            continue
        turns = turn_ends(run)
        if not turns:
            skipped += 1
            continue
        frames, rate = read_wav(wav)
        if not frames:
            skipped += 1
            continue

        for i, (start, end) in enumerate(turns):
            clip = slice_ending_at(frames, rate, end)
            if clip:
                p = out / "turn_end" / f"{stem}_t{i}.wav"
                write_wav(p, clip, rate)
                index.append({"path": str(p), "label": 1, "run": run_id})
                pos += 1
            # Mid-utterance: the caller is still talking. Only meaningful if the
            # utterance is long enough to have a genuine middle.
            if end - start > WINDOW_S + MIN_NEG_OFFSET:
                clip = slice_ending_at(frames, rate, end - MIN_NEG_OFFSET)
                if clip:
                    p = out / "mid_turn" / f"{stem}_t{i}.wav"
                    write_wav(p, clip, rate)
                    index.append({"path": str(p), "label": 0, "run": run_id})
                    neg += 1
        if n % 50 == 0:
            print(f"  {n}/{len(wavs)}  turn_end={pos} mid_turn={neg}", flush=True)

    (out / "index.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in index), encoding="utf-8")
    print(f"\n  {pos} turn-end clips")
    print(f"  {neg} mid-turn clips")
    print(f"  {skipped} recording(s) skipped (no run log, or no final transcript)")
    print(f"  index -> {out/'index.jsonl'}")
    if neg < 200:
        print("\nToo few mid-turn clips to train a useful classifier. Most calls "
              "are short answers with no genuine middle; more calls, or a "
              "shorter window, would be needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
