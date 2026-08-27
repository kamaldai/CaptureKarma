import datetime as dt
import json
import threading
from pathlib import Path

import pytest

from capturekarma.drivers.base import StepError
from capturekarma.motion.ticker import Ticker
from capturekarma.player.player import Player, PlayOptions
from capturekarma.scene import parse_scene
from capturekarma.scene.model import Region


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeDriver:
    def __init__(self, clock: FakeClock, region=Region(100, 100, 800, 600)):
        self.clock = clock
        self.region = region
        self.calls: list[tuple] = []
        self.fail_on_selector: str | None = None

    def setup(self, scene):
        self.calls.append(("setup",)); return self.region

    def resolve(self, target):
        if self.fail_on_selector and target.selector == self.fail_on_selector:
            raise StepError(f"element not found: {target.selector}")
        if target.at:
            return (self.region.x + target.at[0], self.region.y + target.at[1])
        return (self.region.x + 400, self.region.y + 300)

    def pointer_to(self, x, y): self.calls.append(("pos", x, y))
    def mouse_down(self, button="left"): self.calls.append(("down", button))
    def mouse_up(self, button="left"): self.calls.append(("up", button))
    def smooth_scroll(self, step, duration, easing):
        self.calls.append(("scroll", step.by, step.to, round(duration, 3)))
        self.clock.sleep(duration)   # a real driver blocks for the scroll's duration
    def type_text(self, text, delay): self.calls.append(("type", text, delay))
    def press(self, key): self.calls.append(("press", key))
    def screenshot(self, path): Path(path).write_bytes(b"png"); self.calls.append(("shot", Path(path).name))
    def teardown(self): self.calls.append(("teardown",))


class FakeCapture:
    def __init__(self, region, fps, out_path):
        self.region, self.fps, self.out_path = region, fps, Path(out_path)
        self.frames = 0
        self.stopped = False

    def stop(self):
        self.stopped = True
        self.out_path.write_bytes(b"mp4")
        self.frames = 123
        return self.out_path


class FakeOverlay:
    def __init__(self, style, ripple, visible):
        self.style, self.ripple, self.visible = style, ripple, visible
        self.positions: list[tuple] = []
        self.vis: list[bool] = []
        self.clicks = 0
        self.started = self.stopped = False

    def start(self): self.started = True
    def stop(self): self.stopped = True
    def set_position(self, x, y): self.positions.append((x, y))
    def set_visible(self, v): self.vis.append(v)
    def click(self): self.clicks += 1


SCENE = {
    "version": 1, "name": "demo",
    "target": {"kind": "web", "url": "http://x", "viewport": [800, 600]},
    "output": {"fps": 60, "lead_in": 0.5, "lead_out": 0.5},
    "cursor": {"speed": 1000},
    "defaults": {"hold": 0.2},
    "steps": [
        {"move": {"to": [100, 100]}},
        {"click": {}},
        {"scroll": {"by": 900}},
        {"type": {"text": "hi", "delay": 0.01}},
        {"press": "Enter"},
        {"cursor": "hidden"},
        {"wait": 0.3},
        {"cursor": "visible"},
    ],
}


def _player(tmp_path, scene_dict=SCENE, **kw):
    clock = FakeClock()
    ticker = Ticker(hz=10, clock=clock.now, sleep=clock.sleep)
    drv = FakeDriver(clock)
    caps: list[FakeCapture] = []
    ovs: list[FakeOverlay] = []

    def cap_factory(region, fps, out_path):
        c = FakeCapture(region, fps, out_path); caps.append(c); return c

    def ov_factory(style, ripple, visible):
        o = FakeOverlay(style, ripple, visible); ovs.append(o); return o

    scene = parse_scene(scene_dict)
    p = Player(scene, PlayOptions(out_dir=tmp_path, hz=10, **kw), driver=drv, capture_factory=cap_factory,
               overlay_factory=ov_factory, ticker=ticker, now=lambda: dt.datetime(2026, 8, 27, 12, 0, 0))
    return p, drv, caps, ovs, clock


def test_run_produces_video_and_timeline(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path)
    res = p.run()
    assert res.video == tmp_path / "demo_20260827_120000.mp4" and res.video.exists()
    assert res.timeline == tmp_path / "demo_20260827_120000.cursor.json" and res.partial is False
    assert res.frames == 123
    data = json.loads(res.timeline.read_text())
    assert data["region"] == [100, 100, 800, 600] and data["hz"] == 10 and len(data["samples"]) > 5
    assert caps[0].stopped and ovs[0].started and ovs[0].stopped
    assert drv.calls[0] == ("setup",) and drv.calls[-1] == ("teardown",)


def test_step_sequence(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path)
    p.run()
    kinds = [c[0] for c in drv.calls]
    # move: distance from region center (500,400) to (200,200) = 361 px at 1000 px/s -> 0.36 s -> 4 ticks at 10 Hz
    assert kinds.count("pos") == 1 + 4          # initial center + move ticks
    assert drv.calls[kinds.index("down") - 1][0] == "pos"       # click happens after the move
    assert ("down", "left") in drv.calls and ("up", "left") in drv.calls
    assert ("scroll", 900, None, 1.0) in drv.calls              # 900px / 900 px/s = 1.0 s
    assert ("type", "hi", 0.01) in drv.calls and ("press", "Enter") in drv.calls
    assert ovs[0].vis == [False, True] and ovs[0].clicks == 1
    assert ovs[0].positions[-1] == (200, 200)


def test_timing_includes_lead_in_holds_and_lead_out(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path)
    res = p.run()
    # lead_in 0.5 + move 0.4 (4 ticks) + hold 0.2 + click (0.08 press + hold 0.2) + scroll 1.0 + hold 0.2
    # + type hold 0.2 + press hold 0.2 + cursor (no hold) + wait 0.3 + hold 0.2 + cursor + lead_out 0.5 = 3.98
    assert res.duration == pytest.approx(3.98, abs=0.15)


def test_cursor_visible_override_and_style(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path, cursor_visible=False, cursor_style="default")
    p.run()
    assert ovs[0].visible is False and ovs[0].style == "default"


def test_abort_keeps_partial_video(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path)
    p.stop_event.set()
    res = p.run()
    assert res.partial is True and res.video.name == "demo_20260827_120000.partial.mp4" and res.video.exists()
    assert not (tmp_path / "demo_20260827_120000.mp4").exists()
    assert caps[0].stopped and drv.calls[-1] == ("teardown",)


def test_step_error_adds_index_and_screenshot_and_cleans_up(tmp_path):
    scene = {**SCENE, "steps": [{"wait": 0.1}, {"move": {"to": "#missing"}}]}
    p, drv, caps, ovs, clock = _player(tmp_path, scene_dict=scene)
    drv.fail_on_selector = "#missing"
    with pytest.raises(StepError) as ei:
        p.run()
    assert ei.value.step_index == 1 and "step 2" in str(ei.value)
    assert ei.value.screenshot == tmp_path / "demo_20260827_120000.error.png" and ei.value.screenshot.exists()
    assert caps[0].stopped and ovs[0].stopped and drv.calls[-1] == ("teardown",)
    assert (tmp_path / "demo_20260827_120000.partial.mp4").exists()


def test_desktop_scene_uses_region_relative_click_target(tmp_path):
    scene = {"version": 1, "name": "d", "target": {"kind": "desktop", "window": "N"},
             "steps": [{"click": {"to": [10, 20]}}]}
    p, drv, caps, ovs, clock = _player(tmp_path, scene_dict=scene)
    p.run()
    assert ovs[0].positions[-1] == (110, 120)
