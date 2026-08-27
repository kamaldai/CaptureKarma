import datetime as dt
import json
import threading
from pathlib import Path

import pytest

from capturekarma.capture import CaptureError
from capturekarma.drivers.base import DriverError, StepError
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
    def __init__(self, clock: FakeClock, region=Region(100, 100, 800, 600),
                 fail_teardown=False, fail_type=False, fail_setup=False):
        self.clock = clock
        self.region = region
        self.calls: list[tuple] = []
        self.fail_on_selector: str | None = None
        self.fail_setup = fail_setup
        self.fail_teardown = fail_teardown
        self.fail_type = fail_type
        self.on_pointer = None   # called with the running pointer_to count; lets a test abort mid-move

    def setup(self, scene):
        self.calls.append(("setup",))
        if self.fail_setup:
            raise DriverError("window not found")
        return self.region

    def resolve(self, target):
        if self.fail_on_selector and target.selector == self.fail_on_selector:
            raise StepError(f"element not found: {target.selector}")
        if target.at:
            return (self.region.x + target.at[0], self.region.y + target.at[1])
        return (self.region.x + 400, self.region.y + 300)

    def pointer_to(self, x, y):
        self.calls.append(("pos", x, y))
        if self.on_pointer is not None:
            self.on_pointer(sum(1 for c in self.calls if c[0] == "pos"))
    def mouse_down(self, button="left"): self.calls.append(("down", button))
    def mouse_up(self, button="left"): self.calls.append(("up", button))
    def smooth_scroll(self, step, duration, easing):
        self.calls.append(("scroll", step.by, step.to, round(duration, 3)))
        self.clock.sleep(duration)   # a real driver blocks for the scroll's duration
    def type_text(self, text, delay):
        self.calls.append(("type", text, delay))
        if self.fail_type:
            raise RuntimeError("type boom")
    def press(self, key): self.calls.append(("press", key))
    def screenshot(self, path): Path(path).write_bytes(b"png"); self.calls.append(("shot", Path(path).name))
    def teardown(self):
        self.calls.append(("teardown",))
        if self.fail_teardown:
            raise RuntimeError("teardown boom")


class FakeCapture:
    def __init__(self, region, fps, out_path, fail_stop=False):
        self.region, self.fps, self.out_path = region, fps, Path(out_path)
        self.frames = 0
        self.stopped = False
        self.fail_stop = fail_stop

    def stop(self):
        self.stopped = True
        if self.fail_stop:
            raise RuntimeError("capture stop boom")
        self.out_path.write_bytes(b"mp4")
        self.frames = 123
        return self.out_path


class FakeOverlay:
    def __init__(self, style, ripple, visible, fail_on=None):
        self.style, self.ripple, self.visible = style, ripple, visible
        self.positions: list[tuple] = []
        self.vis: list[bool] = []
        self.clicks = 0
        self.started = self.stopped = False
        self.fail_on = fail_on

    def start(self):
        self.started = True
        if self.fail_on == "start":
            raise RuntimeError("overlay start boom")

    def stop(self):
        self.stopped = True
        if self.fail_on == "stop":
            raise RuntimeError("overlay stop boom")
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


def _player(tmp_path, scene_dict=SCENE, *, overlay_fail=None, capture_error=None,
            fail_stop=False, fail_teardown=False, fail_type=False, fail_setup=False, **kw):
    clock = FakeClock()
    ticker = Ticker(hz=10, clock=clock.now, sleep=clock.sleep)
    drv = FakeDriver(clock, fail_teardown=fail_teardown, fail_type=fail_type, fail_setup=fail_setup)
    caps: list[FakeCapture] = []
    ovs: list[FakeOverlay] = []

    def cap_factory(region, fps, out_path):
        if capture_error is not None:
            raise capture_error
        c = FakeCapture(region, fps, out_path, fail_stop=fail_stop); caps.append(c); return c

    def ov_factory(style, ripple, visible):
        o = FakeOverlay(style, ripple, visible, fail_on=overlay_fail); ovs.append(o); return o

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
    assert (tmp_path / "demo_20260827_120000.cursor.json").exists()   # error runs keep their timeline too


def test_desktop_scene_uses_region_relative_click_target(tmp_path):
    scene = {"version": 1, "name": "d", "target": {"kind": "desktop", "window": "N"},
             "steps": [{"click": {"to": [10, 20]}}]}
    p, drv, caps, ovs, clock = _player(tmp_path, scene_dict=scene)
    p.run()
    assert ovs[0].positions[-1] == (110, 120)


def test_cursor_visible_option_pins_visibility_over_scene_cursor_steps(tmp_path):
    scene = {**SCENE, "steps": [{"cursor": "visible"}, {"wait": 0.1}, {"cursor": "hidden"}]}
    p, drv, caps, ovs, clock = _player(tmp_path, scene_dict=scene, cursor_visible=False)
    res = p.run()
    assert ovs[0].visible is False and ovs[0].vis == []          # scene toggles are ignored, not replayed
    samples = json.loads(res.timeline.read_text())["samples"]
    assert samples and all(s[3] is False for s in samples)


def test_capture_factory_failure_stops_overlay_and_tears_down(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path, capture_error=CaptureError("ffmpeg not found"))
    with pytest.raises(CaptureError):
        p.run()
    assert ovs[0].started and ovs[0].stopped
    assert drv.calls[-1] == ("teardown",)
    assert not (tmp_path / "demo_20260827_120000.mp4").exists()


def test_overlay_start_failure_propagates_and_tears_down(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path, overlay_fail="start")
    with pytest.raises(RuntimeError, match="overlay start boom"):
        p.run()
    assert caps == []                                            # capture never started
    assert drv.calls[-1] == ("teardown",)


def test_capture_stop_failure_during_abort_propagates(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path, fail_stop=True)
    p.stop_event.set()
    with pytest.raises(RuntimeError, match="capture stop boom"):
        p.run()
    assert ovs[0].stopped and drv.calls[-1] == ("teardown",)


def test_capture_stop_failure_does_not_mask_step_error(tmp_path):
    scene = {**SCENE, "steps": [{"move": {"to": "#missing"}}]}
    p, drv, caps, ovs, clock = _player(tmp_path, scene_dict=scene, fail_stop=True)
    drv.fail_on_selector = "#missing"
    with pytest.raises(StepError) as ei:
        p.run()
    assert ei.value.step_index == 0
    assert ovs[0].stopped and drv.calls[-1] == ("teardown",)


def test_overlay_stop_failure_does_not_mask_step_error(tmp_path):
    scene = {**SCENE, "steps": [{"move": {"to": "#missing"}}]}
    p, drv, caps, ovs, clock = _player(tmp_path, scene_dict=scene, overlay_fail="stop")
    drv.fail_on_selector = "#missing"
    with pytest.raises(StepError):
        p.run()
    assert caps[0].stopped and drv.calls[-1] == ("teardown",)     # teardown runs even after overlay.stop() raised


def test_non_step_error_propagates_as_is_and_keeps_partial_video(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path, fail_type=True)
    with pytest.raises(RuntimeError, match="type boom"):
        p.run()
    assert not (tmp_path / "demo_20260827_120000.error.png").exists()   # only StepError gets a screenshot
    assert (tmp_path / "demo_20260827_120000.partial.mp4").exists()
    assert caps[0].stopped and ovs[0].stopped and drv.calls[-1] == ("teardown",)


def test_abort_mid_move_stops_before_the_click(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path)
    drv.on_pointer = lambda n: p.stop_event.set() if n >= 3 else None
    res = p.run()
    assert res.partial is True
    assert len(json.loads(res.timeline.read_text())["samples"]) >= 3
    assert not any(c[0] == "down" for c in drv.calls)
    assert drv.calls[-1] == ("teardown",)


def test_abort_between_steps_when_holds_are_zero(tmp_path):
    scene = {**SCENE, "defaults": {"hold": 0}, "output": {"fps": 60, "lead_in": 0, "lead_out": 0},
             "steps": [{"type": {"text": "a"}}, {"type": {"text": "b"}}]}
    p, drv, caps, ovs, clock = _player(tmp_path, scene_dict=scene)
    drv_calls = drv.calls

    def stop_after_first(text, delay):
        drv_calls.append(("type", text, delay))
        p.stop_event.set()

    drv.type_text = stop_after_first
    res = p.run()
    assert res.partial is True
    assert [c for c in drv.calls if c[0] == "type"] == [("type", "a", 0.05)]


def test_driver_setup_failure_still_tears_the_driver_down(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path, fail_setup=True)
    with pytest.raises(DriverError):
        p.run()
    assert ovs == [] and caps == []                # nothing was started
    assert drv.calls == [("setup",), ("teardown",)]
