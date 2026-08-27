"""Record desktop interactions with pynput global hooks into RawEvents."""
from __future__ import annotations

import datetime as _dt
import logging
import math
import time
from pathlib import Path
from typing import Callable

from capturekarma._win import set_dpi_awareness
from capturekarma.drivers import win_input
from capturekarma.drivers.win_input import PX_PER_NOTCH
from capturekarma.scene import Scene, Target, dump_scene
from capturekarma.scene.model import Region

from .events import RawEvent
from .hotkey import StopHotkey
from .smooth import SmoothConfig, smooth

log = logging.getLogger("capturekarma.recorder.desktop")

# pynput Key.<name> -> our (Playwright-style) key names
PYNPUT_KEY_NAMES: dict[str, str] = {
    "enter": "Enter", "tab": "Tab", "backspace": "Backspace", "delete": "Delete", "esc": "Escape",
    "space": " ", "up": "ArrowUp", "down": "ArrowDown", "left": "ArrowLeft", "right": "ArrowRight",
    "home": "Home", "end": "End", "page_up": "PageUp", "page_down": "PageDown",
    "shift": "Shift", "shift_r": "Shift", "ctrl": "Control", "ctrl_l": "Control", "ctrl_r": "Control",
    "alt": "Alt", "alt_l": "Alt", "alt_r": "Alt", "alt_gr": "AltGraph", "cmd": "Meta", "cmd_r": "Meta",
    "caps_lock": "CapsLock", **{f"f{i}": f"F{i}" for i in range(1, 13)},
}
STOP_KEYS = {"f9", "esc"}

#: Drag sampling, shared with the web recorder (web_recorder.js) so both behave the same way.
DRAG_SAMPLE_SECONDS = 0.04   # keep a path point at least this often while the button is down ...
DRAG_SAMPLE_PX = 8.0         # ... or as soon as the pointer has moved this far from the last one
DRAG_MIN_PX = 6.0            # a press whose path is shorter than this is still a click ...
DRAG_MIN_SECONDS = 0.3       # ... unless it lasted at least this long and moved at all


def _foreground_window() -> int:
    """Handle of the window that currently has focus (0 when it cannot be determined)."""
    return win_input.get_foreground_window()


class DesktopRecorder:
    """Turn global mouse/keyboard events into RawEvents.

    `target_hwnd` limits key capture to the window being recorded: the pynput hook is global, so
    without it every keystroke typed anywhere while recording would land in the scene file.
    """

    def __init__(self, region: Region, clock: Callable[[], float] = time.perf_counter,
                 target_hwnd: int | None = None,
                 foreground: Callable[[], int] = _foreground_window):
        self.region = region
        self.target_hwnd = target_hwnd
        self._clock = clock
        self._foreground = foreground
        self._t0 = clock()
        self.events: list[RawEvent] = []
        self._press: dict | None = None   # in-progress drag candidate, None while no button is down
        self._mouse = None
        self._keys = None

    def _t(self) -> float:
        return self._clock() - self._t0

    def _inside(self, x: int, y: int) -> bool:
        """True when a screen point falls in the recorded region (half-open box)."""
        r = self.region
        return r.x <= x < r.right and r.y <= y < r.bottom

    # ---- pure handlers (unit-tested) ----
    def _rel(self, x: int, y: int) -> tuple[int, int]:
        return (x - self.region.x, y - self.region.y)

    def on_click(self, x: int, y: int, button_name: str, pressed: bool) -> None:
        button = button_name if button_name in ("left", "right", "middle") else "left"
        if pressed:
            self._press = None
            if not self._inside(x, y):
                # A gesture that starts outside the recorded region belongs to another window.
                return
            self._press = {"t": self._t(), "button": button, "path": [self._rel(x, y)], "last_t": self._t()}
            return
        press, self._press = self._press, None
        if press is None:
            return
        path: list[tuple[int, int]] = press["path"]
        end = self._rel(x, y)
        if end != path[-1]:
            path.append(end)
        duration = self._t() - press["t"]
        length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        moved = len(path) > 1
        if moved and (length >= DRAG_MIN_PX or duration >= DRAG_MIN_SECONDS):
            self.events.append(RawEvent(t=press["t"], kind="drag", path=tuple(path),  # type: ignore[arg-type]
                                        button=press["button"], duration=duration))
        else:
            self.events.append(RawEvent(t=press["t"], kind="click", at=path[0],  # type: ignore[arg-type]
                                        button=press["button"]))

    def on_move(self, x: int, y: int) -> None:
        """Sample the pointer while a button is down. Ignored entirely when nothing is pressed."""
        press = self._press
        if press is None:
            return
        t = self._t()
        pt = self._rel(x, y)
        if t - press["last_t"] >= DRAG_SAMPLE_SECONDS or math.dist(pt, press["path"][-1]) >= DRAG_SAMPLE_PX:
            press["path"].append(pt)
            press["last_t"] = t

    def on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        if dy and self._inside(x, y):
            self.events.append(RawEvent(t=self._t(), kind="scroll", delta=int(-dy * PX_PER_NOTCH)))

    def _target_has_focus(self) -> bool:
        """True when keystrokes belong to the recorded window (always true without a target)."""
        if self.target_hwnd is None:
            return True
        return self._foreground() == self.target_hwnd

    def on_press(self, key_name: str | None, char: str | None) -> None:
        if key_name in STOP_KEYS:
            return
        if not self._target_has_focus():
            # Privacy: typing in another window (a password manager, chat) is never recorded.
            log.debug("dropping a keystroke: the recorded window is not in the foreground")
            return
        if char is not None:
            self.events.append(RawEvent(t=self._t(), kind="key", key=char))
        elif key_name is not None:
            self.events.append(RawEvent(t=self._t(), kind="key", key=PYNPUT_KEY_NAMES.get(key_name, key_name)))

    # ---- pynput wiring ----
    def start(self) -> None:
        from pynput import keyboard, mouse

        if self._mouse is not None or self._keys is not None:
            log.debug("start() called while already recording; restarting listeners")
            self.stop()
        self._t0 = self._clock()

        def _click(x, y, button, pressed):
            self.on_click(int(x), int(y), button.name, pressed)

        def _move(x, y):
            self.on_move(int(x), int(y))

        def _scroll(x, y, dx, dy):
            self.on_scroll(int(x), int(y), int(dx), int(dy))

        def _press(key):
            char = getattr(key, "char", None)
            name = getattr(key, "name", None)
            # pynput reports Ctrl+letter as control characters; map back to the letter
            if char is not None and len(char) == 1 and ord(char) < 32:
                char = chr(ord(char) + 96)
            self.on_press(name, char if (char is not None and char.isprintable()) else None)

        self._mouse = mouse.Listener(on_click=_click, on_move=_move, on_scroll=_scroll)
        self._keys = keyboard.Listener(on_press=_press)
        for lst in (self._mouse, self._keys):
            lst.daemon = True
            lst.start()
        log.info("recording desktop region %s — press F9 to stop", self.region)

    def stop(self) -> list[RawEvent]:
        self._press = None      # a gesture still in progress when recording ends is discarded
        for lst in (self._mouse, self._keys):
            if lst is not None:
                lst.stop()
        self._mouse = self._keys = None
        return self.events

    def to_scene(self, name: str, window: str | None = None, config: SmoothConfig = SmoothConfig()) -> Scene:
        target = Target(kind="desktop", window=window) if window else Target(kind="desktop", region=self.region)
        return Scene(name=name, target=target, steps=tuple(smooth(self.events, config)))


def record_desktop(window: str, out_path: Path, name: str | None = None) -> Path:
    # Before any window lookup: without it Win32 reports logical px on a scaled display and the
    # CLI would record different coordinates than the GUI and the player, which do declare it.
    set_dpi_awareness()
    hwnd, title = win_input.find_window(window)
    win_input.focus_window(hwnd)
    region = win_input.window_client_region(hwnd)
    rec = DesktopRecorder(region, target_hwnd=hwnd)
    hotkey = StopHotkey()
    rec.start()
    hotkey.start()
    try:
        hotkey.triggered.wait()
    finally:
        hotkey.stop()
        rec.stop()
    scene = rec.to_scene(name or Path(out_path).stem, window=window)
    header = (f"recorded from window {title!r} on {_dt.date.today().isoformat()} — "
              "coordinates are relative to the window client area")
    dump_scene(scene, out_path, header=header)
    log.info("wrote %s (%d steps)", out_path, len(scene.steps))
    return Path(out_path)
