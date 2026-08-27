import threading

from capturekarma.recorder.desktop import DesktopRecorder
from capturekarma.scene import dump_scene, load_scene
from capturekarma.scene.model import (
    ClickStep, DragStep, MoveStep, PressStep, Region, ScrollStep, StepTarget, TypeStep, WaitStep,
)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _rec():
    c = Clock()
    r = DesktopRecorder(Region(100, 200, 800, 600), clock=c)
    return r, c


def test_click_is_recorded_once_on_release_at_the_press_point():
    r, c = _rec()
    c.t = 1.0
    r.on_click(150, 260, "left", True)
    r.on_click(150, 260, "left", False)
    assert len(r.events) == 1 and r.events[0].at == (50, 60) and r.events[0].button == "left"


def test_click_outside_region_ignored():
    r, c = _rec()
    r.on_click(5, 5, "left", True)
    assert r.events == []


def test_scroll_notches_to_pixels_down_positive():
    r, c = _rec()
    r.on_scroll(300, 300, 0, -2)   # pynput: dy<0 = scroll down
    assert r.events[0].kind == "scroll" and r.events[0].delta == 200


def test_scroll_outside_region_ignored():
    r, c = _rec()
    r.on_scroll(5, 5, 0, -2)
    assert r.events == []


def test_keys():
    r, c = _rec()
    r.on_press(None, "a"); r.on_press("enter", None); r.on_press("shift", None); r.on_press("f9", None)
    assert [e.key for e in r.events] == ["a", "Enter", "Shift"]   # f9 (stop key) not recorded


def test_to_scene():
    r, c = _rec()
    c.t = 0.1; r.on_click(150, 260, "left", True); r.on_click(150, 260, "left", False)
    c.t = 0.5; r.on_scroll(300, 300, 0, -3)
    c.t = 0.9; r.on_press(None, "h"); c.t = 1.0; r.on_press(None, "i")
    s = r.to_scene("d", window="Notepad")
    assert s.target.kind == "desktop" and s.target.window == "Notepad" and s.target.region is None
    assert s.steps == (MoveStep(to=StepTarget(at=(50, 60))), ClickStep(), WaitStep(seconds=0.4), ScrollStep(by=300),
                       WaitStep(seconds=0.4), TypeStep(text="hi"))


class FakeListener:
    """Stand-in for pynput's Listener: records lifecycle calls, touches no real hooks."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.daemon = False
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_start_is_idempotent_and_stops_previous_listeners(monkeypatch):
    from pynput import keyboard, mouse

    made: dict[str, list[FakeListener]] = {"mouse": [], "keys": []}

    def factory(bucket):
        def make(**kwargs):
            lst = FakeListener(**kwargs)
            made[bucket].append(lst)
            return lst
        return make

    monkeypatch.setattr(mouse, "Listener", factory("mouse"))
    monkeypatch.setattr(keyboard, "Listener", factory("keys"))

    r, c = _rec()
    r.start()
    r.start()

    assert len(made["mouse"]) == 2 and len(made["keys"]) == 2
    assert all(lst.started and lst.daemon for lst in made["mouse"] + made["keys"])
    assert made["mouse"][0].stopped and made["keys"][0].stopped        # first pair stopped by restart
    assert not made["mouse"][1].stopped and not made["keys"][1].stopped

    r.stop()
    assert made["mouse"][1].stopped and made["keys"][1].stopped


def test_keys_recorded_only_while_the_target_window_is_in_the_foreground():
    """Privacy: with a target window, keystrokes typed into other windows are never recorded."""
    fg = {"hwnd": 4242}
    r = DesktopRecorder(Region(0, 0, 800, 600), clock=Clock(), target_hwnd=4242,
                        foreground=lambda: fg["hwnd"])
    r.on_press(None, "a")
    fg["hwnd"] = 99                     # user alt-tabbed to their password manager
    r.on_press(None, "s")
    r.on_press("enter", None)
    fg["hwnd"] = 4242
    r.on_press(None, "b")
    assert [e.key for e in r.events] == ["a", "b"]


def test_keys_always_recorded_without_a_target_window():
    calls: list[int] = []

    def fg() -> int:
        calls.append(1)
        return 7

    r = DesktopRecorder(Region(0, 0, 800, 600), clock=Clock(), target_hwnd=None, foreground=fg)
    r.on_press(None, "a")
    r.on_press("enter", None)
    assert [e.key for e in r.events] == ["a", "Enter"]
    assert calls == []                  # no foreground lookup at all when there is no target


def test_clicks_and_scrolls_are_not_gated_on_the_foreground_window():
    r = DesktopRecorder(Region(0, 0, 800, 600), clock=Clock(), target_hwnd=1, foreground=lambda: 2)
    r.on_click(10, 10, "left", True)
    r.on_click(10, 10, "left", False)
    r.on_scroll(10, 10, 0, -1)
    assert [e.kind for e in r.events] == ["click", "scroll"]


def test_record_desktop_sets_dpi_awareness_before_looking_up_the_window(tmp_path, monkeypatch):
    from capturekarma.drivers import win_input
    from capturekarma.recorder import desktop as desktop_mod

    calls: list[str] = []

    def fake_find_window(substring: str):
        calls.append("find_window")
        return 1234, "Fixture Window"

    monkeypatch.setattr(desktop_mod, "set_dpi_awareness", lambda: calls.append("set_dpi_awareness") or True)
    monkeypatch.setattr(win_input, "find_window", fake_find_window, raising=False)
    monkeypatch.setattr(win_input, "focus_window",
                        lambda hwnd: calls.append("focus_window"), raising=False)
    monkeypatch.setattr(win_input, "window_client_region",
                        lambda hwnd: calls.append("window_client_region") or Region(0, 0, 800, 600),
                        raising=False)
    monkeypatch.setattr(DesktopRecorder, "start", lambda self: calls.append("start"))
    monkeypatch.setattr(DesktopRecorder, "stop", lambda self: calls.append("stop") or self.events)

    class FakeHotkey:
        def __init__(self):
            self.triggered = threading.Event()
            self.triggered.set()

        def start(self):
            calls.append("hotkey.start")

        def stop(self):
            calls.append("hotkey.stop")

    monkeypatch.setattr(desktop_mod, "StopHotkey", FakeHotkey)

    out = tmp_path / "d.yaml"
    assert desktop_mod.record_desktop("Fixture", out) == out
    assert out.exists()
    assert calls.index("set_dpi_awareness") < calls.index("find_window")
    for later in ("window_client_region", "start"):
        assert calls.index("set_dpi_awareness") < calls.index(later)


def test_record_desktop_passes_the_target_window_to_the_recorder(tmp_path, monkeypatch):
    from capturekarma.drivers import win_input
    from capturekarma.recorder import desktop as desktop_mod

    made: list[DesktopRecorder] = []
    real_init = DesktopRecorder.__init__

    def spy_init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        made.append(self)

    monkeypatch.setattr(desktop_mod, "set_dpi_awareness", lambda: True)
    monkeypatch.setattr(win_input, "find_window", lambda s: (4242, "Fixture Window"), raising=False)
    monkeypatch.setattr(win_input, "focus_window", lambda hwnd: None, raising=False)
    monkeypatch.setattr(win_input, "window_client_region", lambda hwnd: Region(0, 0, 800, 600), raising=False)
    monkeypatch.setattr(DesktopRecorder, "__init__", spy_init)
    monkeypatch.setattr(DesktopRecorder, "start", lambda self: None)
    monkeypatch.setattr(DesktopRecorder, "stop", lambda self: self.events)

    class FakeHotkey:
        def __init__(self):
            self.triggered = threading.Event()
            self.triggered.set()

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(desktop_mod, "StopHotkey", FakeHotkey)
    desktop_mod.record_desktop("Fixture", tmp_path / "d.yaml")
    assert [r.target_hwnd for r in made] == [4242]


def test_recorder_scene_survives_a_dump_load_round_trip(tmp_path):
    r, c = _rec()
    c.t = 0.1; r.on_click(150, 260, "left", True); r.on_click(150, 260, "left", False)
    c.t = 0.5; r.on_scroll(300, 300, 0, -3)
    c.t = 0.9; r.on_press(None, "h")
    c.t = 1.0; r.on_press(None, "i")
    c.t = 1.4; r.on_press("enter", None)
    scene = r.to_scene("round-trip", window="Notepad")
    path = tmp_path / "round-trip.yaml"
    dump_scene(scene, path)
    assert load_scene(path) == scene


def test_recorder_scene_with_a_region_target_survives_a_round_trip(tmp_path):
    r, c = _rec()
    c.t = 0.2; r.on_click(150, 260, "left", True); r.on_click(150, 260, "left", False)
    scene = r.to_scene("region-scene")          # no window -> region target
    path = tmp_path / "region-scene.yaml"
    dump_scene(scene, path)
    assert load_scene(path) == scene


def test_press_move_release_becomes_a_drag_not_a_click():
    r, c = _rec()
    c.t = 1.0; r.on_click(150, 260, "left", True)
    c.t = 1.1; r.on_move(200, 300)
    c.t = 1.2; r.on_move(260, 340)
    c.t = 1.4; r.on_click(260, 340, "left", False)
    assert [e.kind for e in r.events] == ["drag"]
    e = r.events[0]
    assert e.path == ((50, 60), (100, 100), (160, 140))       # region-relative
    assert e.button == "left" and round(e.duration, 3) == 0.4


def test_a_press_that_barely_moves_stays_a_click():
    r, c = _rec()
    c.t = 1.0; r.on_click(150, 260, "left", True)
    c.t = 1.05; r.on_move(152, 261)
    c.t = 1.1; r.on_click(152, 261, "left", False)
    assert [e.kind for e in r.events] == ["click"]
    assert r.events[0].at == (50, 60)                         # the *press* point, as before


def test_a_long_slow_press_with_any_movement_is_a_drag():
    r, c = _rec()
    c.t = 1.0; r.on_click(150, 260, "left", True)
    c.t = 1.5; r.on_move(153, 262)
    c.t = 1.6; r.on_click(153, 262, "left", False)
    assert [e.kind for e in r.events] == ["drag"]


def test_moves_are_sampled_by_time_and_distance():
    r, c = _rec()
    c.t = 1.0; r.on_click(150, 260, "left", True)
    for k in range(1, 4):                  # three moves 1 px apart, 2 ms apart: too small, too soon
        c.t = 1.0 + k * 0.002
        r.on_move(150 + k, 260)
    c.t = 1.01; r.on_move(200, 260)        # 50 px from the last kept point: kept
    c.t = 1.5; r.on_click(200, 260, "left", False)
    assert r.events[0].path == ((50, 60), (100, 60))


def test_moves_outside_a_press_are_ignored():
    r, c = _rec()
    r.on_move(300, 300)
    r.on_move(400, 400)
    assert r.events == []


def test_a_press_that_starts_outside_the_region_is_ignored_entirely():
    r, c = _rec()
    r.on_click(5, 5, "left", True)
    r.on_move(300, 300)
    r.on_click(300, 300, "left", False)
    assert r.events == []


def test_drag_to_scene_produces_a_move_then_a_drag():
    r, c = _rec()
    c.t = 0.1; r.on_click(150, 260, "left", True)
    c.t = 0.5; r.on_move(400, 400)
    c.t = 0.9; r.on_click(400, 400, "left", False)
    s = r.to_scene("d", window="Notepad")
    assert s.steps == (MoveStep(to=StepTarget(at=(50, 60))),
                       DragStep(path=((50, 60), (300, 200)), duration=0.8))


def test_drag_scene_survives_a_round_trip(tmp_path):
    r, c = _rec()
    c.t = 0.1; r.on_click(150, 260, "left", True)
    c.t = 0.5; r.on_move(400, 400)
    c.t = 0.9; r.on_click(400, 400, "left", False)
    scene = r.to_scene("drag-scene", window="Notepad")
    path = tmp_path / "drag-scene.yaml"
    dump_scene(scene, path)
    assert load_scene(path) == scene


def test_a_long_press_that_barely_moves_is_a_click_not_a_drag():
    """A 1 px tremor over 350 ms is a click held too long; a drag would lose the selector."""
    r, c = _rec()
    c.t = 1.0; r.on_click(150, 260, "left", True)
    c.t = 1.35; r.on_move(151, 260)
    c.t = 1.4; r.on_click(151, 260, "left", False)
    assert [e.kind for e in r.events] == ["click"]
    assert r.events[0].at == (50, 60)


def test_a_long_press_that_travels_far_enough_is_still_a_drag():
    r, c = _rec()
    c.t = 1.0; r.on_click(150, 260, "left", True)
    c.t = 1.35; r.on_move(154, 260)          # 4 px >= the long-press floor
    c.t = 1.4; r.on_click(154, 260, "left", False)
    assert [e.kind for e in r.events] == ["drag"]


def test_a_drag_that_leaves_the_window_is_clamped_to_the_region():
    r, c = _rec()                            # Region(100, 200, 800, 600)
    c.t = 1.0; r.on_click(150, 260, "left", True)
    c.t = 1.1; r.on_move(50, 100)            # up and left of the region
    c.t = 1.2; r.on_move(2000, 1500)         # past the far corner
    c.t = 1.3; r.on_click(2000, 1500, "left", False)
    assert r.events[0].path == ((50, 60), (0, 0), (799, 599))
    assert all(0 <= x < 800 and 0 <= y < 600 for x, y in r.events[0].path)
