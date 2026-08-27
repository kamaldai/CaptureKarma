from pathlib import Path
from unittest.mock import patch

from capturekarma.capture.ffmpeg import Capabilities
from capturekarma.capture.monitors import Monitor
from capturekarma.capture.recorder import CaptureError, start_capture
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
