from capturekarma.recorder.desktop import DesktopRecorder
from capturekarma.scene.model import (
    ClickStep, MoveStep, PressStep, Region, ScrollStep, StepTarget, TypeStep, WaitStep,
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


def test_click_is_region_relative_and_press_only():
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
    c.t = 0.1; r.on_click(150, 260, "left", True)
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
