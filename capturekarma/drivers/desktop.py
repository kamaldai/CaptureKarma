"""Desktop driver: real OS cursor + SendInput. Scrolling is best-effort wheel emulation."""
from __future__ import annotations

import logging
from pathlib import Path
from types import ModuleType
from typing import Any

from capturekarma.motion.easing import Easing
from capturekarma.motion.ticker import Ticker
from capturekarma.scene.model import Point, Region, Scene, ScrollStep, StepTarget, WheelStep

from . import win_input
from .base import DriverError, StepError

log = logging.getLogger("capturekarma.drivers.desktop")


class DesktopDriver:
    def __init__(self, ticker: Ticker | None = None, input_module: ModuleType | Any = win_input):
        self._ticker = ticker or Ticker()
        self._in = input_module
        self._region: Region | None = None
        #: Buttons currently held by us. A drag that aborts between down and up would otherwise
        #: leave the real mouse pressed for the whole user session, not just for this run.
        self._pressed: set[str] = set()

    def setup(self, scene: Scene) -> Region:
        t = scene.target
        if t.region is not None:
            self._region = t.region
        else:
            assert t.window is not None
            hwnd, title = self._in.find_window(t.window)
            self._in.focus_window(hwnd)
            self._region = self._in.window_client_region(hwnd)
            log.info("desktop target %r -> %s", title, self._region)
        return self._region

    def _r(self) -> Region:
        if self._region is None:
            raise DriverError("driver not set up")
        return self._region

    def resolve(self, target: StepTarget) -> Point:
        if target.at is None:
            raise StepError("desktop scenes need [x, y] targets, not a selector")
        r = self._r()
        return (r.x + target.at[0], r.y + target.at[1])

    def pointer_to(self, x: int, y: int) -> None:
        self._in.set_cursor_pos(x, y)

    def mouse_down(self, button: str = "left") -> None:
        self._in.mouse_button(button, True)
        self._pressed.add(button)

    def mouse_up(self, button: str = "left") -> None:
        self._in.mouse_button(button, False)
        self._pressed.discard(button)

    def smooth_scroll(self, step: ScrollStep, duration: float, easing: Easing) -> None:
        if step.by is None:
            raise StepError("desktop scroll needs 'by'")
        self._wheel_over(step.by, duration, easing)

    def smooth_wheel(self, step: WheelStep, duration: float, easing: Easing) -> None:
        # Windows cannot tell a canvas zoom from a page scroll: both are wheel notches at the cursor.
        self._wheel_over(step.by, duration, easing)

    def _wheel_over(self, pixels: int, duration: float, easing: Easing) -> None:
        n = self._ticker.n_ticks(duration)
        deltas = list(win_input.wheel_steps(pixels, n, easing))
        for (i, _), delta in zip(self._ticker.ticks(duration), deltas):
            self._in.wheel(delta)

    def type_text(self, text: str, delay: float) -> None:
        self._in.type_text(text, delay)

    def press(self, key: str) -> None:
        try:
            self._in.press_key(key)
        except ValueError as exc:
            # parse_key rejects unknown key/modifier names: a scene problem, not a crash.
            raise StepError(f"cannot press {key!r}: {exc}") from exc

    def screenshot(self, path: Path) -> None:
        from PIL import ImageGrab
        r = self._r()
        ImageGrab.grab(bbox=(r.x, r.y, r.right, r.bottom), all_screens=True).save(path)

    def teardown(self) -> None:
        for button in sorted(self._pressed):
            log.debug("releasing %s mouse button left down by an interrupted step", button)
            self._in.mouse_button(button, False)
        self._pressed.clear()
        self._region = None
