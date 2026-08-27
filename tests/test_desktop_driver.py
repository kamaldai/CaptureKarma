from types import SimpleNamespace

import pytest

from capturekarma.drivers.base import StepError, WindowNotFound
from capturekarma.drivers.desktop import DesktopDriver
from capturekarma.motion.easing import get_easing
from capturekarma.motion.ticker import Ticker
from capturekarma.scene.model import Region, Scene, ScrollStep, StepTarget, Target


class FakeInput:
    def __init__(self):
        self.calls: list[tuple] = []
        self.titles = ["Untitled - Notepad", "Other"]

    def find_window(self, sub):
        for i, t in enumerate(self.titles):
            if sub.lower() in t.lower():
                return 100 + i, t
        raise WindowNotFound(f"no window matching {sub!r}; visible: {self.titles}")

    def window_client_region(self, hwnd):
        return Region(50, 60, 800, 600)

    def focus_window(self, hwnd):
        self.calls.append(("focus", hwnd))

    def set_cursor_pos(self, x, y):
        self.calls.append(("pos", x, y))

    def mouse_button(self, button, down):
        self.calls.append(("btn", button, down))

    def wheel(self, delta):
        self.calls.append(("wheel", delta))

    def type_text(self, text, delay, sleep=None):
        self.calls.append(("type", text, delay))

    def press_key(self, name):
        self.calls.append(("press", name))


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _driver():
    fi = FakeInput()
    c = FakeClock()
    d = DesktopDriver(ticker=Ticker(hz=10, clock=c.now, sleep=c.sleep), input_module=fi)
    return d, fi


def test_setup_by_window_focuses_and_returns_region():
    d, fi = _driver()
    scene = Scene(name="n", target=Target(kind="desktop", window="notepad"), steps=())
    assert d.setup(scene) == Region(50, 60, 800, 600)
    assert ("focus", 100) in fi.calls


def test_setup_by_region_skips_window_lookup():
    d, fi = _driver()
    scene = Scene(name="n", target=Target(kind="desktop", region=Region(1, 2, 30, 40)), steps=())
    assert d.setup(scene) == Region(1, 2, 30, 40) and fi.calls == []


def test_setup_missing_window_raises():
    d, fi = _driver()
    with pytest.raises(WindowNotFound, match="Other"):
        d.setup(Scene(name="n", target=Target(kind="desktop", window="zzz"), steps=()))


def test_resolve_is_region_relative():
    d, fi = _driver()
    d.setup(Scene(name="n", target=Target(kind="desktop", window="notepad"), steps=()))
    assert d.resolve(StepTarget(at=(10, 20))) == (60, 80)
    with pytest.raises(StepError, match="selector"):
        d.resolve(StepTarget(selector="#x"))


def test_scroll_emits_wheel_deltas_summing_to_total():
    d, fi = _driver()
    d.setup(Scene(name="n", target=Target(kind="desktop", window="notepad"), steps=()))
    d.smooth_scroll(ScrollStep(by=300), duration=1.0, easing=get_easing("ease_in_out_cubic"))
    deltas = [c[1] for c in fi.calls if c[0] == "wheel"]
    assert len(deltas) == 10 and sum(deltas) == -360  # 300 px * WHEEL_DELTA / PX_PER_NOTCH


def test_click_type_press_forward_to_input():
    d, fi = _driver()
    d.setup(Scene(name="n", target=Target(kind="desktop", window="notepad"), steps=()))
    d.pointer_to(5, 6); d.mouse_down(); d.mouse_up(); d.type_text("hi", 0.01); d.press("Enter")
    assert ("pos", 5, 6) in fi.calls and ("btn", "left", True) in fi.calls and ("btn", "left", False) in fi.calls
    assert ("type", "hi", 0.01) in fi.calls and ("press", "Enter") in fi.calls


def test_press_reports_an_unknown_key_as_a_step_error():
    """A bad `press:` key is a scene problem, not a crash: parse_key's ValueError becomes StepError."""
    from capturekarma.drivers.win_input import parse_key

    class RealParsingInput(FakeInput):
        def press_key(self, name):
            parse_key(name)                 # the real name check, without touching SendInput
            self.calls.append(("press", name))

    d = DesktopDriver(input_module=RealParsingInput())
    with pytest.raises(StepError, match="Hyper"):
        d.press("Hyper")
    d.press("Enter")                        # a good key still goes through
