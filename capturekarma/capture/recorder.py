"""ffmpeg capture process lifecycle."""
from __future__ import annotations

import collections
import logging
import subprocess
import threading
import time
from pathlib import Path

from capturekarma._win import is_remote_session
from capturekarma.scene.model import Region

from .ffmpeg import Capabilities, build_capture_args
from .monitors import CaptureError, Monitor  # noqa: F401  (re-export CaptureError)

log = logging.getLogger("capturekarma.capture")


class ScreenCapture:
    def __init__(self, caps: Capabilities, region: Region, monitor: Monitor, fps: int, out_path: Path,
                 use_ddagrab: bool = True):
        self.args = build_capture_args(caps, region, monitor, fps, out_path, use_ddagrab)
        self.out_path = Path(out_path)
        self.use_ddagrab = use_ddagrab
        self.frames = 0
        self._proc: subprocess.Popen[str] | None = None
        self._stderr: collections.deque[str] = collections.deque(maxlen=200)
        self._ready = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stderr_tail(self, n: int = 20) -> str:
        return "\n".join(list(self._stderr)[-n:])

    def start(self) -> None:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        log.debug("ffmpeg: %s", " ".join(self.args))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                      bufsize=1, creationflags=flags)
        self._threads = [threading.Thread(target=self._read_progress, daemon=True),
                         threading.Thread(target=self._read_stderr, daemon=True)]
        for t in self._threads:
            t.start()

    def _read_progress(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            if line.startswith("frame="):
                try:
                    self.frames = int(line.split("=", 1)[1].strip())
                except ValueError:
                    continue
                if self.frames >= 1:
                    self._ready.set()

    def _read_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        for line in self._proc.stderr:
            self._stderr.append(line.rstrip())

    def wait_ready(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._ready.wait(0.05):
                return
            if not self.alive:
                raise CaptureError(f"ffmpeg exited before producing frames (code {self._proc.returncode}):\n"
                                   f"{self.stderr_tail()}")
        self.stop(timeout=3.0, expect_output=False)
        raise CaptureError(f"ffmpeg produced no frames within {timeout}s:\n{self.stderr_tail()}")

    def stop(self, timeout: float = 10.0, expect_output: bool = True) -> Path:
        if self._proc is None:
            raise CaptureError("capture was never started")
        if self.alive:
            try:
                assert self._proc.stdin
                self._proc.stdin.write("q\n")
                self._proc.stdin.flush()
            except (OSError, ValueError):
                pass  # stdin already closed by ffmpeg; fall through to wait/terminate
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                log.warning("ffmpeg did not exit after 'q'; terminating")
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    # A kill cannot be refused; reap it so returncode is settled and the OS has
                    # released the output file before the checks below. A timeout here is pathological
                    # (unkillable process) and must surface, so TimeoutExpired is left to propagate.
                    self._proc.wait(timeout=3.0)
        for t in self._threads:
            t.join(timeout=2.0)
        if expect_output and (not self.out_path.exists() or self.out_path.stat().st_size == 0):
            raise CaptureError(f"ffmpeg exited (code {self._proc.returncode}) without writing {self.out_path}:\n"
                               f"{self.stderr_tail()}")
        return self.out_path


def start_capture(caps: Capabilities, region: Region, monitor: Monitor, fps: int, out_path: Path,
                  prefer_ddagrab: bool = True) -> ScreenCapture:
    """Start capturing and wait until frames flow. Falls back from ddagrab to gdigrab with a warning."""
    use_ddagrab = prefer_ddagrab and caps.ddagrab
    if use_ddagrab and monitor.rotated:
        # ddagrab hands back the unrotated panel surface, so offsets derived from virtual-screen
        # coordinates would silently capture the wrong area. gdigrab is in virtual-screen coordinates.
        log.warning("monitor %d is rotated; ddagrab does not honour rotation, using gdigrab", monitor.index)
        use_ddagrab = False
    if use_ddagrab and is_remote_session():
        # The Desktop Duplication API refuses to duplicate outputs of a Remote Desktop session
        # ("Failed duplicating output"); trying it only costs a failed start.
        log.warning("Remote Desktop session: Desktop Duplication is unavailable, using gdigrab (CPU capture)")
        use_ddagrab = False
    if use_ddagrab:
        cap = ScreenCapture(caps, region, monitor, fps, out_path, use_ddagrab=True)
        cap.start()
        try:
            cap.wait_ready()
            return cap
        except CaptureError as exc:
            log.warning("ddagrab capture failed, falling back to gdigrab (slower): %s", exc)
            if out_path.exists():
                out_path.unlink()
    cap = ScreenCapture(caps, region, monitor, fps, out_path, use_ddagrab=False)
    cap.start()
    cap.wait_ready()
    return cap
