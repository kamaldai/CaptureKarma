"""Plays a Scene: drives the target, draws the cursor overlay, captures video."""
from __future__ import annotations

import datetime as _dt
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from capturekarma._win import high_res_timer, set_dpi_awareness
from capturekarma.drivers.base import Driver, StepError
from capturekarma.motion import (
    Ticker, bezier_path, drag_duration, get_easing, move_duration, polyline_path, scroll_duration,
)
from capturekarma.scene.model import (
    ClickStep, CursorStep, DragStep, MoveStep, Point, PressStep, Region, Scene, ScrollStep, Step,
    StepTarget, TypeStep, WaitStep, WheelStep,
)

from .timeline import CursorTimeline

log = logging.getLogger("capturekarma.player")


@dataclass(frozen=True)
class PlayOptions:
    out_dir: Path | None = None
    cursor_visible: bool | None = None
    cursor_style: str | None = None
    hz: int = 120
    prefer_ddagrab: bool = True


@dataclass(frozen=True)
class RunResult:
    video: Path
    timeline: Path
    partial: bool
    duration: float
    frames: int


class _Aborted(Exception):
    pass


def make_driver(scene: Scene) -> Driver:
    if scene.target.kind == "web":
        from capturekarma.drivers.web import WebDriver
        return WebDriver()
    from capturekarma.drivers.desktop import DesktopDriver
    return DesktopDriver()


def default_capture_factory(prefer_ddagrab: bool = True) -> Callable[[Region, int, Path], object]:
    from capturekarma.capture import CaptureError, find_ffmpeg, list_monitors, monitor_for_region, probe, start_capture

    def factory(region: Region, fps: int, out_path: Path):
        exe = find_ffmpeg()
        if not exe:
            raise CaptureError("ffmpeg not found. Install ffmpeg or `uv add imageio-ffmpeg`; run `ck doctor`.")
        caps = probe(exe)
        monitor = monitor_for_region(region, list_monitors())
        return start_capture(caps, region, monitor, fps, out_path, prefer_ddagrab=prefer_ddagrab)

    return factory


def default_overlay_factory(style: str, ripple: bool, visible: bool):
    from capturekarma.cursor import CursorOverlay
    return CursorOverlay(style=style, ripple=ripple, visible=visible)


class Player:
    def __init__(self, scene: Scene, options: PlayOptions = PlayOptions(), *,
                 driver: Driver | None = None,
                 capture_factory: Callable[[Region, int, Path], object] | None = None,
                 overlay_factory: Callable[[str, bool, bool], object] | None = None,
                 ticker: Ticker | None = None,
                 stop_event: threading.Event | None = None,
                 now: Callable[[], _dt.datetime] | None = None):
        self.scene = scene
        self.options = options
        self.driver = driver or make_driver(scene)
        self._capture_factory = capture_factory or default_capture_factory(options.prefer_ddagrab)
        self._overlay_factory = overlay_factory or default_overlay_factory
        self.ticker = ticker or Ticker(hz=options.hz)
        self.stop_event = stop_event or threading.Event()
        self._now = now or _dt.datetime.now
        self.timeline = CursorTimeline()
        self._t0: float | None = None  # None until the run clock starts, so a t0 of exactly 0.0 still counts
        self._clock = self.ticker.now  # same clock as the ticker so timeline timestamps line up
        self._pointer: Point = (0, 0)
        self._visible = scene.cursor.visible if options.cursor_visible is None else options.cursor_visible
        self._overlay = None
        self._move_index = 0

    # ---- helpers ----
    def _elapsed(self) -> float:
        return 0.0 if self._t0 is None else self._clock() - self._t0

    def _check_abort(self) -> None:
        if self.stop_event.is_set():
            raise _Aborted()

    def _sample(self, click: bool = False) -> None:
        self.timeline.add(self._elapsed(), *self._pointer, self._visible, click)

    def _hold(self, seconds: float) -> None:
        if seconds <= 0:
            return
        for _ in self.ticker.ticks(seconds):
            self._check_abort()
            self._sample()

    def _easing(self, step: Step):
        return get_easing(step.easing or self.scene.defaults.easing)

    def _hold_for(self, step: Step) -> float:
        return self.scene.defaults.hold if step.hold is None else step.hold

    def _move(self, target: Point, step: Step) -> None:
        dist = math.dist(self._pointer, target)
        duration = step.duration if step.duration is not None else move_duration(dist, self.scene.cursor.speed)
        n = self.ticker.n_ticks(duration)
        path = bezier_path(self._pointer, target, n, self._easing(step), self._move_index)
        self._move_index += 1
        for (i, _), pt in zip(self.ticker.ticks(duration), path):
            self._check_abort()
            self._set_pointer(pt)
            self._sample()

    def _set_pointer(self, pt: Point) -> None:
        self._pointer = pt
        self.driver.pointer_to(*pt)
        self._overlay.set_position(*pt)

    def _click(self, step: ClickStep) -> None:
        self.driver.mouse_down(step.button)
        self._overlay.click()
        self._sample(click=True)
        self.ticker.wait(0.08)
        self.driver.mouse_up(step.button)

    def _drag(self, step: DragStep) -> None:
        """Move to path[0], press, follow the polyline over `duration`, release."""
        path = [self._region_point(pt) for pt in step.path]
        self._move(path[0], step)
        length = sum(math.dist(a, b) for a, b in zip(path, path[1:]))
        duration = (step.duration if step.duration is not None
                    else drag_duration(length, self.scene.cursor.speed))
        self.driver.mouse_down(step.button)
        self._overlay.click()
        self._sample(click=True)
        n = self.ticker.n_ticks(duration)
        pts = polyline_path(path, n, self._easing(step))
        for (i, _), pt in zip(self.ticker.ticks(duration), pts):
            self._check_abort()   # a long drag must still abort promptly, not only between steps
            self._set_pointer(pt)
            self._sample()
        self.driver.mouse_up(step.button)

    def _region_point(self, pt: Point) -> Point:
        """A scene-space drag point (web: viewport CSS px, desktop: region-relative) in screen px."""
        return self.driver.resolve(StepTarget(at=pt))

    def _run_step(self, idx: int, step: Step) -> None:
        if isinstance(step, WaitStep):
            self._hold(step.seconds)
        elif isinstance(step, MoveStep):
            self._move(self.driver.resolve(step.to), step)
        elif isinstance(step, ClickStep):
            if step.to is not None:
                self._move(self.driver.resolve(step.to), step)
            self._click(step)
        elif isinstance(step, DragStep):
            self._drag(step)
        elif isinstance(step, WheelStep):
            if step.at is not None:
                self._move(self.driver.resolve(step.at), step)
            duration = step.duration if step.duration is not None else scroll_duration(step.by)
            self.driver.smooth_wheel(step, duration, self._easing(step))
            self._sample()
        elif isinstance(step, ScrollStep):
            px = step.by if step.by is not None else (step.to or 0)
            duration = step.duration if step.duration is not None else scroll_duration(px)
            self.driver.smooth_scroll(step, duration, self._easing(step))
            self._sample()
        elif isinstance(step, TypeStep):
            self.driver.type_text(step.text, step.delay)
        elif isinstance(step, PressStep):
            self.driver.press(step.key)
        elif isinstance(step, CursorStep):
            if self.options.cursor_visible is not None:
                # An explicit cursor_visible pins the cursor for the whole run; scene toggles defer to it.
                log.debug("cursor step ignored: visibility pinned by options")
            else:
                self._visible = step.visible
                self._overlay.set_visible(step.visible)
            self._sample()
            return  # no hold after a visibility toggle
        self._hold(self._hold_for(step))

    # ---- main ----
    def run(self) -> RunResult:
        set_dpi_awareness()
        stamp = self._now().strftime("%Y%m%d_%H%M%S")
        out_dir = Path(self.options.out_dir or Path(self.scene.output.dir).expanduser())
        out_dir.mkdir(parents=True, exist_ok=True)
        base = out_dir / f"{self.scene.name}_{stamp}"
        out = lambda ext: Path(f"{base}{ext}")  # noqa: E731 - str concat; with_suffix would eat a dotted scene name
        video = out(".mp4")
        style = self.options.cursor_style or self.scene.cursor.style

        region: Region | None = None
        capture = None
        partial = False
        error: BaseException | None = None
        timeline: Path | None = None
        try:
            region = self.driver.setup(self.scene)
            self._overlay = self._overlay_factory(style, self.scene.cursor.ripple, self._visible)
            self._overlay.start()
            self._pointer = region.center
            self._overlay.set_position(*self._pointer)
            self.driver.pointer_to(*self._pointer)
            capture = self._capture_factory(region, self.scene.output.fps, video)
            with high_res_timer():
                self._t0 = self._clock()
                self._hold(self.scene.output.lead_in)
                for idx, step in enumerate(self.scene.steps):
                    self._check_abort()  # blocking steps (scroll, type) can only be aborted between steps
                    log.info("step %d/%d: %s", idx + 1, len(self.scene.steps), type(step).__name__)
                    try:
                        self._run_step(idx, step)
                    except StepError as exc:
                        shot = out(".error.png")
                        try:
                            self.driver.screenshot(shot)
                        except Exception as shot_exc:  # noqa: BLE001 - screenshot is best-effort diagnostics
                            log.warning("could not save error screenshot: %s", shot_exc)
                            shot = None
                        raise StepError(exc.message, step_index=idx, screenshot=shot) from exc
                self._hold(self.scene.output.lead_out)
        except _Aborted:
            log.warning("aborted by user; keeping partial video")
            partial = True
        except BaseException as exc:
            partial = True
            error = exc
        finally:
            duration = self._elapsed()
            frames = 0
            if capture is not None:
                try:
                    written = capture.stop()
                    frames = getattr(capture, "frames", 0)
                    if partial and written.exists():
                        target = out(".partial.mp4")
                        written.replace(target)
                        video = target
                except Exception as cap_exc:  # noqa: BLE001 - never mask the original error
                    log.error("stopping capture failed: %s", cap_exc)
                    if error is None:
                        error = cap_exc
            if region is not None:
                # Abort and error runs get a companion timeline too: it is the record of what was played.
                try:
                    timeline = self.timeline.dump(out(".cursor.json"), region, self.ticker.hz)
                except Exception as tl_exc:  # noqa: BLE001 - never mask the original error
                    log.error("writing cursor timeline failed: %s", tl_exc)
                    if error is None:
                        error = tl_exc
            if self._overlay is not None:
                try:
                    self._overlay.stop()
                except Exception as ov_exc:  # noqa: BLE001 - never mask the original error, and never skip teardown
                    log.error("overlay stop failed: %s", ov_exc)
                    if error is None:
                        error = ov_exc
            try:
                self.driver.teardown()
            except Exception as td_exc:  # noqa: BLE001 - never mask the original error
                log.error("driver teardown failed: %s", td_exc)
                if error is None:
                    error = td_exc
        if error is not None:
            raise error
        if timeline is None:  # unreachable: on a non-error path region is set and the dump succeeded
            raise RuntimeError("cursor timeline was not written")
        log.info("saved %s (%.1fs, %d frames)", video, duration, frames)
        return RunResult(video=video, timeline=timeline, partial=partial, duration=duration, frames=frames)
