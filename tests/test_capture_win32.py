import json
import subprocess
import time
from pathlib import Path

import pytest

from capturekarma._win import set_dpi_awareness
from capturekarma.capture.ffmpeg import find_ffmpeg, probe
from capturekarma.capture.monitors import list_monitors
from capturekarma.capture.recorder import start_capture
from capturekarma.scene.model import Region

pytestmark = pytest.mark.win32


def _ffprobe(exe: str, path: Path) -> dict:
    ffprobe = str(Path(exe).with_name(Path(exe).name.replace("ffmpeg", "ffprobe")))
    cmd = [ffprobe if Path(ffprobe).exists() else "ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=r_frame_rate,width,height:format=duration", "-of", "json", str(path)]
    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        pytest.skip("ffprobe unavailable")
    return json.loads(completed.stdout)


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
    info = _ffprobe(exe, out)
    assert info["streams"][0]["width"] == 640 and info["streams"][0]["height"] == 360
    assert info["streams"][0]["r_frame_rate"] == "60/1"


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
