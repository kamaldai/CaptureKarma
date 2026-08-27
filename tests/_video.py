"""Probe a finished MP4's video stream, with or without `ffprobe`.

The bundled `imageio-ffmpeg` build ships `ffmpeg` but no `ffprobe`, which used to make every
container assertion skip on this machine. `ffmpeg -i <file>` prints the same facts on stderr, so
fall back to parsing its `Stream #0:0 ... Video: ...` line when `ffprobe` is missing.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from capturekarma.capture.ffmpeg import find_ffmpeg

#: `..., yuv420p(tv, bt709, progressive), 640x360 [SAR 1:1 DAR 16:9], ...`
_PIX_FMT_AND_SIZE = re.compile(r",\s*([a-z][a-z0-9]+)(?:\([^)]*\))?,\s*(\d+)x(\d+)\b")
_STREAM_LINE = re.compile(r"^\s*Stream #\d+:\d+.*: Video: ", re.M)


def _rate(text: str, unit: str) -> float | None:
    """`60 fps` / `59.94 tbr` / `1k tbr` -> float, or None when ffmpeg did not print it."""
    m = re.search(rf"(\d+(?:\.\d+)?)(k?)\s+{unit}\b", text)
    if not m:
        return None
    return float(m.group(1)) * (1000 if m.group(2) else 1)


def _fraction(value: str) -> float | None:
    try:
        num, _, den = value.partition("/")
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None


def _find_ffprobe() -> str | None:
    """`ffprobe` on PATH, or the sibling of whichever ffmpeg we are using."""
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        sibling = Path(ffmpeg).with_name(Path(ffmpeg).name.replace("ffmpeg", "ffprobe"))
        if sibling.exists():
            return str(sibling)
    return None


def video_stream_info(path: Path) -> dict:
    """`{pix_fmt, width, height, fps, tbr, duration, source}` for the first video stream.

    `tbr` is the *declared* frame rate (`r_frame_rate`); `fps` is the average one, which drops
    below it whenever the capture missed frames — assert against `tbr`. `duration` is None unless
    real `ffprobe` was available, because `ffmpeg -i` reports it only to centisecond precision.
    """
    probe = _find_ffprobe()
    if probe:
        out = subprocess.run(
            [probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=r_frame_rate,avg_frame_rate,width,height,pix_fmt:format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
        stream = data["streams"][0]
        return {"pix_fmt": stream["pix_fmt"], "width": int(stream["width"]), "height": int(stream["height"]),
                "fps": _fraction(stream.get("avg_frame_rate", "")) or _fraction(stream["r_frame_rate"]),
                "tbr": _fraction(stream["r_frame_rate"]),
                "duration": float(data["format"]["duration"]), "source": "ffprobe"}

    exe = find_ffmpeg()
    assert exe, "neither ffprobe nor ffmpeg is available to probe the video"
    # `ffmpeg -i <file>` with no output file: it prints the stream layout to stderr, then exits 1.
    text = subprocess.run([exe, "-hide_banner", "-i", str(path)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    match = _STREAM_LINE.search(text)
    assert match, f"no video stream line in ffmpeg output for {path}:\n{text}"
    line = text[match.start():].splitlines()[0]
    # Skip the codec tag's `(avc1 / 0x31637661)` so it cannot be mistaken for the frame size.
    body = re.sub(r"\(avc1[^)]*\)", "", line)
    size = _PIX_FMT_AND_SIZE.search(body)
    assert size, f"could not read pix_fmt and size from: {line}"
    return {"pix_fmt": size.group(1), "width": int(size.group(2)), "height": int(size.group(3)),
            "fps": _rate(body, "fps"), "tbr": _rate(body, "tbr"), "duration": None, "source": "ffmpeg"}
