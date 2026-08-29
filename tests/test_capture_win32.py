import time
from pathlib import Path

import pytest

from capturekarma._win import is_remote_session, set_dpi_awareness
from capturekarma.capture.ffmpeg import find_ffmpeg, probe
from capturekarma.capture.monitors import list_monitors
from capturekarma.capture.recorder import start_capture
from capturekarma.scene.model import Region
from tests._video import video_stream_info

pytestmark = pytest.mark.win32


def test_record_one_second(tmp_path: Path):
    set_dpi_awareness()  # monitor regions must be physical pixels, as in the player
    exe = find_ffmpeg()
    assert exe, "ffmpeg not found (PATH or imageio-ffmpeg)"
    caps = probe(exe)
    mon = [m for m in list_monitors() if m.primary][0]
    region = Region(mon.region.x + 10, mon.region.y + 10, 640, 360)
    out = tmp_path / "clip.mp4"
    cap = start_capture(caps, region, mon, 60, out)
    time.sleep(1.0)
    result = cap.stop()
    assert result == out and out.exists() and out.stat().st_size > 0
    assert cap.frames >= 30
    if caps.ddagrab and not mon.rotated and not is_remote_session():
        # A silent gdigrab fallback still produces a valid MP4, so without this an ffmpeg-args
        # regression on the ddagrab branch would pass unnoticed (it did once - see the pix_fmt fix).
        assert cap.use_ddagrab is True, "ddagrab fell back to gdigrab; the GPU capture path is broken"
    info = video_stream_info(out)
    assert (info["width"], info["height"]) == (640, 360)
    assert info["tbr"] == 60
    assert info["pix_fmt"] == "yuv420p"   # 4:2:0 on every branch, so any player can decode it


def test_record_on_rotated_monitor_falls_back_to_gdigrab(tmp_path: Path):
    set_dpi_awareness()
    exe = find_ffmpeg()
    assert exe, "ffmpeg not found (PATH or imageio-ffmpeg)"
    rotated = [m for m in list_monitors() if m.rotated]
    if not rotated:
        pytest.skip("no rotated monitor attached")
    mon = rotated[0]
    out = tmp_path / "rotated.mp4"
    cap = start_capture(probe(exe), Region(mon.region.x + 10, mon.region.y + 10, 640, 360), mon, 30, out)
    time.sleep(1.0)
    assert cap.stop() == out and out.stat().st_size > 0
    assert cap.use_ddagrab is False
    assert cap.frames >= 15
