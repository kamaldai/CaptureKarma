"""Full pipeline on a real desktop: play the bundled web fixture scene and probe the MP4."""
from pathlib import Path

import pytest

from capturekarma.player import Player, PlayOptions
from capturekarma.scene import parse_scene
from tests._video import video_stream_info

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
    info = video_stream_info(res.video)
    assert info["tbr"] == 60
    assert info["pix_fmt"] == "yuv420p"   # 4:2:0 so every player can decode it
    assert info["width"] % 2 == 0 and info["height"] % 2 == 0
    if info["duration"] is not None:      # only real ffprobe reports a precise container duration
        assert abs(info["duration"] - res.duration) <= 0.5
