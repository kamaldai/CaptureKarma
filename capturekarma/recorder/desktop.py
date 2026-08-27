"""Record desktop interactions with pynput global hooks into RawEvents."""
from __future__ import annotations

import datetime as _dt
import logging
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
        self._mouse = None
        self._keys = None

    def _t(self) -> float:
        return self._clock() - self._t0

    def _inside(self, x: int, y: int) -> bool:
        """True when a screen point falls in the recorded region (half-open box)."""
        r = self.region
        return r.x <= x < r.right and r.y <= y < r.bottom

    # ---- pure handlers (unit-tested) ----
    def on_click(self, x: int, y: int, button_name: str, pressed: bool) -> None:
        if not pressed or not self._inside(x, y):
            return
        r = self.region
        button = button_name if button_name in ("left", "right", "middle") else "left"
        self.events.append(RawEvent(t=self._t(), kind="click", at=(x - r.x, y - r.y), button=button))  # type: ignore[arg-type]

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

        def _scroll(x, y, dx, dy):
            self.on_scroll(int(x), int(y), int(dx), int(dy))

        def _press(key):
            char = getattr(key, "char", None)
            name = getattr(key, "name", None)
            # pynput reports Ctrl+letter as control characters; map back to the letter
            if char is not None and len(char) == 1 and ord(char) < 32:
                char = chr(ord(char) + 96)
            self.on_press(name, char if (char is not None and char.isprintable()) else None)

        self._mouse = mouse.Listener(on_click=_click, on_scroll=_scroll)
        self._keys = keyboard.Listener(on_press=_press)
        for lst in (self._mouse, self._keys):
            lst.daemon = True
            lst.start()
        log.info("recording desktop region %s — press F9 to stop", self.region)

    def stop(self) -> list[RawEvent]:
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
