"""Full pipeline on a real desktop: play the bundled web fixture scene and probe the MP4."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from capturekarma.player import Player, PlayOptions
from capturekarma.scene import parse_scene

pytestmark = [pytest.mark.win32, pytest.mark.integration]


def test_play_web_fixture_end_to_end(tmp_path: Path, fixture_url: str):
    scene = parse_scene({
        "version": 1, "name": "e2e",
        "target": {"kind": "web", "url": fixture_url, "viewport": [1000, 600]},
        "output": {"fps": 60, "lead_in": 0.3, "lead_out": 0.3},
        "defaults": {"hold": 0.2},
        "steps": [
            {"move": {"to": "#btn-primary"}}, {"click": {}},
            {"scroll": {"by": 600, "duration": 1.0}},
            # #email sits beside #btn-primary at the top of the fixture, so scroll back before
            # aiming at it: the driver refuses off-screen targets rather than scrolling for you.
            {"scroll": {"by": -600, "duration": 1.0}},
            {"cursor": "hidden"}, {"wait": 0.3}, {"cursor": "visible"},
            {"move": {"to": "#email"}}, {"click": {}}, {"type": {"text": "hi", "delay": 0.02}},
        ],
    })
    res = Player(scene, PlayOptions(out_dir=tmp_path)).run()
    assert res.video.exists() and res.partial is False and res.timeline.exists()
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        pytest.skip("ffprobe not on PATH; video produced but not probed")
    info = json.loads(subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=r_frame_rate,width,height:format=duration", "-of", "json", str(res.video)],
        capture_output=True, text=True, check=True).stdout)
    assert info["streams"][0]["r_frame_rate"] == "60/1"
    assert abs(float(info["format"]["duration"]) - res.duration) <= 0.5
    assert info["streams"][0]["width"] % 2 == 0 and info["streams"][0]["height"] % 2 == 0
