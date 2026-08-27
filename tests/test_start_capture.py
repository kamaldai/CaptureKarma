import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from capturekarma.capture.ffmpeg import Capabilities
from capturekarma.capture.monitors import Monitor
from capturekarma.capture.recorder import CaptureError, ScreenCapture, start_capture
from capturekarma.scene.model import Region

CAPS = Capabilities(exe="ffmpeg", version="7.1", ddagrab=True, nvenc=True, libx264=True)
LANDSCAPE = Monitor(0, Region(0, 0, 1920, 1080), True)
PORTRAIT = Monitor(1, Region(0, 0, 1080, 1920), False, rotated=True)
REGION = Region(10, 10, 640, 360)


def _ddagrab_flags(screen_capture) -> list[bool]:
    """use_ddagrab passed to each ScreenCapture construction, in order."""
    return [c.kwargs["use_ddagrab"] for c in screen_capture.call_args_list]


def test_rotated_monitor_never_attempts_ddagrab(tmp_path: Path):
    with patch("capturekarma.capture.recorder.ScreenCapture") as sc:
        cap = start_capture(CAPS, REGION, PORTRAIT, 60, tmp_path / "out.mp4")
    assert _ddagrab_flags(sc) == [False]
    assert cap is sc.return_value
    sc.return_value.start.assert_called_once()
    sc.return_value.wait_ready.assert_called_once()


def test_unrotated_monitor_prefers_ddagrab(tmp_path: Path):
    with patch("capturekarma.capture.recorder.ScreenCapture") as sc:
        start_capture(CAPS, REGION, LANDSCAPE, 60, tmp_path / "out.mp4")
    assert _ddagrab_flags(sc) == [True]


def test_ddagrab_failure_falls_back_to_gdigrab(tmp_path: Path):
    with patch("capturekarma.capture.recorder.ScreenCapture") as sc:
        sc.return_value.wait_ready.side_effect = [CaptureError("no frames"), None]
        start_capture(CAPS, REGION, LANDSCAPE, 60, tmp_path / "out.mp4")
    assert _ddagrab_flags(sc) == [True, False]


class _FakeStdin:
    def write(self, text: str) -> int:
        return len(text)

    def flush(self) -> None:
        pass


class _FakePopen:
    """Minimal Popen stand-in whose wait() outcomes are scripted.

    Outcomes: "timeout" raises TimeoutExpired, an int settles that returncode.
    poll() reports None until a wait() settles, so `alive` is True while it refuses to die.
    """

    def __init__(self, *outcomes: object):
        self.stdin = _FakeStdin()
        self.stdout = iter(())
        self.stderr = iter(())
        self.returncode: int | None = None
        self.wait_calls = 0
        self.terminate_calls = 0
        self.kill_calls = 0
        self._outcomes = list(outcomes)

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        self.wait_calls += 1
        outcome = self._outcomes.pop(0)
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=timeout)
        self.returncode = int(outcome)
        return self.returncode

    def terminate(self) -> None:
        self.terminate_calls += 1

    def kill(self) -> None:
        self.kill_calls += 1


def _started(fake: _FakePopen, out_path: Path) -> ScreenCapture:
    cap = ScreenCapture(CAPS, REGION, LANDSCAPE, 60, out_path)
    with patch("capturekarma.capture.recorder.subprocess.Popen", return_value=fake):
        cap.start()
    return cap


def test_stop_reaps_the_process_after_kill(tmp_path: Path):
    """q and terminate both time out: kill once, then wait again so nothing is left unreaped."""
    out = tmp_path / "out.mp4"
    out.write_bytes(b"video")
    fake = _FakePopen("timeout", "timeout", -9)
    cap = _started(fake, out)
    assert cap.stop() == out
    assert fake.terminate_calls == 1
    assert fake.kill_calls == 1
    assert fake.wait_calls == 3


def test_stop_error_message_reports_a_settled_returncode(tmp_path: Path):
    """The regression: without the post-kill wait, returncode was still None here."""
    fake = _FakePopen("timeout", "timeout", -9)
    cap = _started(fake, tmp_path / "missing.mp4")
    with pytest.raises(CaptureError, match=r"code -9") as excinfo:
        cap.stop()
    assert "code None" not in str(excinfo.value)


def test_stop_propagates_timeout_from_an_unkillable_process(tmp_path: Path):
    fake = _FakePopen("timeout", "timeout", "timeout")
    cap = _started(fake, tmp_path / "out.mp4")
    with pytest.raises(subprocess.TimeoutExpired):
        cap.stop()
    assert fake.kill_calls == 1
