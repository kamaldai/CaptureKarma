"""ffmpeg discovery, capability probing, and capture argument construction."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from capturekarma.scene.model import Region

from .monitors import Monitor

log = logging.getLogger("capturekarma.capture")


@dataclass(frozen=True)
class Capabilities:
    exe: str
    version: str
    ddagrab: bool
    nvenc: bool
    libx264: bool


def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001 - absence of the optional binary is a normal outcome
        log.debug("imageio-ffmpeg unavailable: %s", exc)
        return None


def _run(exe: str, *args: str) -> str:
    p = subprocess.run([exe, "-hide_banner", *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.stdout + p.stderr


def parse_probe_output(exe: str, version_text: str, filters_text: str, encoders_text: str) -> Capabilities:
    m = re.search(r"ffmpeg version (\S+)", version_text)
    return Capabilities(
        exe=exe,
        version=m.group(1) if m else "unknown",
        ddagrab=bool(re.search(r"^\s*\S*\s+ddagrab\s", filters_text, re.M)) or " ddagrab " in filters_text,
        nvenc=bool(re.search(r"^\s*V\S*\s+h264_nvenc\s", encoders_text, re.M)),
        libx264=bool(re.search(r"^\s*V\S*\s+libx264\s", encoders_text, re.M)),
    )


def probe(exe: str) -> Capabilities:
    return parse_probe_output(exe, _run(exe, "-version"), _run(exe, "-filters"), _run(exe, "-encoders"))


def even_region(region: Region) -> Region:
    return Region(region.x, region.y, region.width - region.width % 2, region.height - region.height % 2)


def build_capture_args(caps: Capabilities, region: Region, monitor: Monitor, fps: int, out_path: Path,
                       use_ddagrab: bool) -> list[str]:
    r = even_region(region)
    args: list[str] = [caps.exe, "-hide_banner", "-loglevel", "warning", "-nostats", "-progress", "pipe:1", "-y"]
    if use_ddagrab:
        spec = (f"ddagrab=output_idx={monitor.index}:offset_x={r.x - monitor.region.x}"
                f":offset_y={r.y - monitor.region.y}:video_size={r.width}x{r.height}"
                f":framerate={fps}:draw_mouse=0")
        args += ["-f", "lavfi", "-i", spec]
        if caps.nvenc:
            args += ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19", "-rc", "vbr"]
        else:
            args += ["-vf", "hwdownload,format=bgra", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                     "-pix_fmt", "yuv420p"]
    else:
        args += ["-f", "gdigrab", "-framerate", str(fps), "-offset_x", str(r.x), "-offset_y", str(r.y),
                 "-video_size", f"{r.width}x{r.height}", "-draw_mouse", "0", "-i", "desktop"]
        if caps.nvenc:
            args += ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19", "-rc", "vbr", "-pix_fmt", "yuv420p"]
        else:
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    args += ["-r", str(fps), "-movflags", "+faststart", str(out_path)]
    return args
