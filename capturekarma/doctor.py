"""Environment checks with actionable fixes."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from capturekarma._frozen import CHROMIUM_PROBE_FLAG, bundle_dir, is_frozen
from capturekarma._win import IS_WINDOWS, set_dpi_awareness


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str | None = None


_CHROMIUM_PROBE = (
    "from playwright.sync_api import sync_playwright\n"
    "with sync_playwright() as p:\n"
    "    print(p.chromium.executable_path)\n"
)
_CHROMIUM_FIX = "run: uv sync && uv run playwright install chromium"
_FROZEN_FIX = "the bundle is incomplete - unzip CaptureKarma again, keeping _internal next to the .exe"


def _fix(from_source: str) -> str:
    """The remedy to print: a bundle's user has no uv, no repo and no `playwright install`."""
    return _FROZEN_FIX if is_frozen() else from_source


def _probe_command() -> list[str]:
    """How to ask a child process for Chromium's path.

    From source that is `python -c`; in a PyInstaller bundle `sys.executable` is CaptureKarma
    itself, which has no `-c`, so the entry scripts answer a private flag instead.
    """
    if is_frozen():
        return [sys.executable, CHROMIUM_PROBE_FLAG]
    return [sys.executable, "-c", _CHROMIUM_PROBE]


def _chromium_check() -> Check:
    """Ask a child interpreter where Chromium lives.

    Playwright's sync driver tears its asyncio loop down noisily at interpreter exit ("Task was
    destroyed but it is pending"), so the probe runs out-of-process to keep `ck doctor` readable.
    """
    try:
        proc = subprocess.run(_probe_command(), capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return Check("playwright chromium", False, str(exc), _fix(_CHROMIUM_FIX))
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    if proc.returncode != 0 or not lines:
        tail = [ln for ln in proc.stderr.splitlines() if ln.strip()]
        return Check("playwright chromium", False, tail[-1] if tail else "playwright probe failed",
                     _fix(_CHROMIUM_FIX))
    path = Path(lines[-1].strip())
    ok = path.exists()
    return Check("playwright chromium", ok, str(path) if ok else f"browser not installed ({path})",
                 None if ok else _fix("run: uv run playwright install chromium"))


def run_doctor() -> list[Check]:
    from capturekarma.capture import CaptureError, find_ffmpeg, list_monitors, probe

    checks: list[Check] = []
    root = bundle_dir()
    checks.append(Check("bundle", True,
                        f"frozen bundle at {root}" if root else "running from source (not frozen)"))
    checks.append(Check("windows", IS_WINDOWS, "Windows desktop session" if IS_WINDOWS else "not Windows",
                        None if IS_WINDOWS else "CaptureKarma v2 captures only on Windows 10/11"))
    checks.append(Check("dpi awareness", set_dpi_awareness(), "per-monitor v2 requested",
                        None if IS_WINDOWS else "n/a off Windows"))

    exe = find_ffmpeg()
    if not exe:
        checks.append(Check("ffmpeg", False, "not found",
                            _fix("install ffmpeg (winget install Gyan.FFmpeg) or `uv sync` for the "
                                 "bundled imageio-ffmpeg binary")))
    else:
        caps = probe(exe)
        checks.append(Check("ffmpeg", True, f"{caps.version} at {exe}"))
        checks.append(Check("ddagrab", caps.ddagrab,
                            "GPU desktop duplication capture available" if caps.ddagrab else "missing",
                            None if caps.ddagrab else
                            "install a full ffmpeg build (Gyan.FFmpeg); gdigrab fallback will be used"))
        checks.append(Check("h264_nvenc", caps.nvenc,
                            "NVIDIA hardware encoder available" if caps.nvenc else "not available",
                            None if caps.nvenc else
                            "libx264 software encoding will be used (fine up to 1440p60)"))
        checks.append(Check("libx264", caps.libx264,
                            "software encoder available" if caps.libx264 else "missing",
                            None if caps.libx264 else "install a full ffmpeg build"))

    checks.append(_chromium_check())

    if IS_WINDOWS:
        try:
            mons = list_monitors()
            checks.append(Check("monitors", True, "; ".join(
                f"{m.index}: {m.region.width}x{m.region.height} @({m.region.x},{m.region.y})"
                f"{' primary' if m.primary else ''}"
                for m in mons)))
        except CaptureError as exc:
            checks.append(Check("monitors", False, str(exc), None))
    return checks
