"""Runtime fix-ups for the frozen (PyInstaller) build. Every function is a no-op from source.

A PyInstaller bundle has no site-packages: Playwright's browsers and the `imageio-ffmpeg` binary
sit next to the executable under `_internal/`, and the libraries that look for them use paths
derived from `__file__` or from environment variables. `bootstrap()` points both at the bundle and
must run before `playwright` or `imageio_ffmpeg` is imported anywhere, so the entry scripts under
`packaging/` call it as their first statement.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger("capturekarma.frozen")

#: Sole argument that makes a frozen executable print the bundled Chromium path and exit. `ck
#: doctor` re-invokes itself with it because a bundle has no `python -c` to probe with.
CHROMIUM_PROBE_FLAG = "--ck-chromium-path"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path | None:
    """Directory holding the bundled data files (`_internal/`), or None when not frozen."""
    if not is_frozen():
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else Path(sys.executable).resolve().parent


def bundled_ffmpeg() -> Path | None:
    """The `imageio-ffmpeg` binary inside the bundle, or None if it is not there."""
    root = bundle_dir()
    if root is None:
        return None
    binaries = root / "imageio_ffmpeg" / "binaries"
    found = sorted(p for p in binaries.glob("ffmpeg*") if p.is_file())
    return found[0] if found else None


def bundled_browsers() -> Path | None:
    """The Playwright browsers directory inside the bundle, or None if the build shipped none."""
    root = bundle_dir()
    if root is None:
        return None
    browsers = root / "playwright" / "driver" / "package" / ".local-browsers"
    return browsers if browsers.is_dir() else None


def bootstrap() -> None:
    """Make Playwright and imageio-ffmpeg find what the bundle ships. No-op when not frozen.

    `PLAYWRIGHT_BROWSERS_PATH=0` tells Playwright to look for browsers inside its own package
    (`playwright/driver/package/.local-browsers`), which is where the build installs Chromium.
    When the bundle really does carry a browser there this **overrides** an inherited value, because
    Playwright's driver only accepts the exact Chromium revision it was built against: a machine-wide
    `PLAYWRIGHT_BROWSERS_PATH` pointing at some other install's cache (a developer box usually has
    one) would send a self-contained app looking for a revision that is not there. With no bundled
    browser there is nothing to prefer, so an inherited value is left alone.

    `IMAGEIO_FFMPEG_EXE` is set explicitly because `imageio_ffmpeg`'s own lookup goes through
    `importlib.resources`, which is not reliable for a frozen package. It uses `setdefault`: any
    ffmpeg build with `ddagrab` will do, so an operator who names one keeps it (as does one on PATH,
    which `capture.find_ffmpeg` prefers regardless).
    """
    if not is_frozen():
        return
    browsers = bundled_browsers()
    if browsers is None:
        log.warning("no bundled Chromium under %s; leaving browser discovery to the machine", bundle_dir())
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
    else:
        previous = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        if previous not in (None, "0"):
            log.info("ignoring PLAYWRIGHT_BROWSERS_PATH=%s in favour of the bundled Chromium in %s",
                     previous, browsers)
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

    exe = bundled_ffmpeg()
    if exe is None:
        log.warning("bundled ffmpeg not found under %s; falling back to PATH", bundle_dir())
    else:
        os.environ.setdefault("IMAGEIO_FFMPEG_EXE", str(exe))


def maybe_run_chromium_probe(argv: list[str] | None = None) -> None:
    """Handle `<exe> --ck-chromium-path` by printing Chromium's path and exiting.

    `ck doctor` asks a child process where Chromium is, because Playwright's sync driver tears its
    asyncio loop down noisily at interpreter exit. From source that child is `python -c ...`; in a
    bundle `sys.executable` is the application itself, so it needs this entry point instead.
    """
    args = sys.argv[1:] if argv is None else argv
    if args[:1] != [CHROMIUM_PROBE_FLAG]:
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        path = pw.chromium.executable_path
    sys.stdout.write(path + "\n")
    sys.stdout.flush()
    sys.exit(0)
