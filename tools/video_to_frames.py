#!/usr/bin/env python3
"""Slice an MP4 into a numbered JPEG sequence for scroll-scrubbed storytelling.

A scroll-scrub hero is just a <canvas> that draws frame N as you scroll. The
whole engineering problem is the *budget*: every frame is downloaded before the
effect can play smoothly, so frame count x frame weight is the number that
decides whether the section ships or stalls. This tool reports that number
loudly, because it is the one thing that is easy to get wrong and expensive to
discover late.

Usage:
    python tools/video_to_frames.py INPUT.mp4 -o .tmp/frames/hero
    python tools/video_to_frames.py INPUT.mp4 -o out --fps 24 --width 1600 -q 4

Notes learned on this machine (Windows, ffmpeg 9.0 via winget):
  - ffmpeg is installed but its PATH entry only appears in *new* shells, so this
    script resolves the binary itself rather than trusting PATH.
  - JPEG quality is ffmpeg's -q:v scale: 2 is best, 31 is worst. 3-6 is the
    useful band for hero imagery; above 8 the compression shows on gradients.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

# Where winget's Gyan.FFmpeg package lands. Checked only if PATH lookup fails.
WINGET_FFMPEG_GLOB = os.path.join(
    os.path.expanduser("~"),
    "AppData", "Local", "Microsoft", "WinGet", "Packages",
    "Gyan.FFmpeg*", "**", "bin",
)


def resolve_binary(name: str) -> str:
    """Find ffmpeg/ffprobe on PATH, falling back to the winget install dir."""
    found = shutil.which(name)
    if found:
        return found

    exe = f"{name}.exe" if os.name == "nt" else name
    for bindir in glob.glob(WINGET_FFMPEG_GLOB, recursive=True):
        candidate = os.path.join(bindir, exe)
        if os.path.isfile(candidate):
            return candidate

    sys.exit(
        f"error: {name} not found.\n"
        f"Install it with:  winget install --id Gyan.FFmpeg -e"
    )


def probe(video: str) -> dict:
    """Return duration/fps/dimensions for the source video."""
    ffprobe = resolve_binary("ffprobe")
    out = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,nb_frames",
            "-show_entries", "format=duration",
            "-of", "json", video,
        ],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)
    stream = data["streams"][0]

    num, _, den = stream["r_frame_rate"].partition("/")
    src_fps = float(num) / float(den or 1)

    return {
        "width": stream["width"],
        "height": stream["height"],
        "fps": src_fps,
        "duration": float(data["format"]["duration"]),
    }


def human(nbytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Extract a JPEG frame sequence from a video for scroll scrubbing."
    )
    ap.add_argument("input", help="source video (mp4/mov/webm)")
    ap.add_argument("-o", "--outdir", required=True, help="output directory")
    ap.add_argument("--fps", type=float, default=25.0,
                    help="frames per second to extract (default: 25)")
    ap.add_argument("--width", type=int, default=1920,
                    help="output width in px, height auto to keep aspect (default: 1920)")
    ap.add_argument("-q", "--quality", type=int, default=4,
                    help="JPEG quality, 2=best 31=worst (default: 4)")
    ap.add_argument("--prefix", default="frame", help="filename prefix (default: frame)")
    ap.add_argument("--start", type=float, help="start time in seconds")
    ap.add_argument("--duration", type=float, help="seconds to extract from --start")
    ap.add_argument("--max-frames", type=int, default=600,
                    help="abort if the sequence would exceed this many frames (default: 600)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite a non-empty output directory")
    args = ap.parse_args()

    if not os.path.isfile(args.input):
        sys.exit(f"error: no such file: {args.input}")
    if not 2 <= args.quality <= 31:
        sys.exit("error: --quality must be between 2 (best) and 31 (worst)")

    ffmpeg = resolve_binary("ffmpeg")
    info = probe(args.input)

    span = args.duration if args.duration else info["duration"] - (args.start or 0)
    projected = int(span * args.fps)
    if projected > args.max_frames and not args.force:
        sys.exit(
            f"error: this would produce ~{projected} frames, over the {args.max_frames} limit.\n"
            f"       Every frame is downloaded before the scrub is smooth. Either lower\n"
            f"       --fps (try {max(1, int(args.max_frames / span))}), shorten with --duration,\n"
            f"       or pass --force if you have measured the payload and accept it."
        )

    if os.path.isdir(args.outdir) and os.listdir(args.outdir) and not args.force:
        sys.exit(f"error: {args.outdir} is not empty; pass --force to overwrite")
    os.makedirs(args.outdir, exist_ok=True)

    pattern = os.path.join(args.outdir, f"{args.prefix}_%04d.jpg")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if args.start:
        cmd += ["-ss", str(args.start)]          # before -i = fast seek
    cmd += ["-i", args.input]
    if args.duration:
        cmd += ["-t", str(args.duration)]
    cmd += [
        "-vf", f"fps={args.fps},scale={args.width}:-2:flags=lanczos",
        "-q:v", str(args.quality),
        pattern,
    ]

    print(f"source : {info['width']}x{info['height']} @ {info['fps']:.2f}fps, "
          f"{info['duration']:.2f}s")
    print(f"extract: {args.fps}fps -> {args.width}px wide, JPEG q{args.quality}")

    subprocess.run(cmd, check=True)

    frames = sorted(glob.glob(os.path.join(args.outdir, f"{args.prefix}_*.jpg")))
    if not frames:
        sys.exit("error: ffmpeg produced no frames")

    total = sum(os.path.getsize(f) for f in frames)
    avg = total / len(frames)

    print()
    print(f"frames : {len(frames)}  ({os.path.basename(frames[0])} .. "
          f"{os.path.basename(frames[-1])})")
    print(f"weight : {human(total)} total, {human(avg)} average")
    print(f"pattern: {args.prefix}_%04d.jpg  (1-indexed, 4-digit zero pad)")

    # The payload verdict. 8 MB is roughly 3s on a mid-tier 4G connection, which
    # is about as long as a hero can stall before it reads as broken.
    if total > 8 * 1024 * 1024:
        print()
        print(f"WARNING: {human(total)} is heavy for a preloaded sequence. Reduce --fps,")
        print(f"         drop --width, or raise -q before shipping this.")


if __name__ == "__main__":
    main()
