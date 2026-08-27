"""Web driver: Playwright Chromium, virtual mouse, in-page eased scrolling."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from capturekarma.motion.easing import EASINGS, Easing
from capturekarma.motion.ticker import Ticker
from capturekarma.scene.model import Point, Region, Scene, ScrollStep, StepTarget, WheelStep

from .base import DriverError, StepError

log = logging.getLogger("capturekarma.drivers.web")
SCROLL_JS = (Path(__file__).parent / "web_scroll.js").read_text(encoding="utf-8")
_METRICS_JS = """() => ({
  sx: window.screenX, sy: window.screenY,
  ow: window.outerWidth, oh: window.outerHeight,
  iw: window.innerWidth, ih: window.innerHeight,
  dpr: window.devicePixelRatio,
})"""


def fit_window_to_viewport(page, context, width: int, height: int,
                           window_pos: tuple[int, int] = (0, 0)) -> None:
    """Resize the OS window so the page's inner size equals the requested viewport exactly.

    Headed Chromium sizes the *window*, so the page's inner size is the viewport minus the tab
    strip and window borders. Measure that chrome on a blank page, then grow the window by it via
    CDP so recording and playback agree on viewport CSS pixels. Headless Chromium has no OS window
    and sizes the viewport directly, so callers must skip this in headless mode.

    ``window_pos`` is the desired *viewport* origin in screen pixels (not the window origin).
    The window is offset by the chrome so the viewport lands at ``window_pos`` and therefore
    stays inside a single monitor even when the viewport equals the monitor size.
    """
    page.goto("about:blank")
    m = page.evaluate(_METRICS_JS)
    dw, dh = m["ow"] - m["iw"], m["oh"] - m["ih"]
    # Window chrome is typically: left/right = side, bottom ~= side, top = dh - side.
    side = max(0.0, dw / 2)
    top_chrome = max(0.0, dh - side)
    cdp = context.new_cdp_session(page)
    wid = cdp.send("Browser.getWindowForTarget")["windowId"]
    cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {
        "left": round(window_pos[0] - side), "top": round(window_pos[1] - top_chrome),
        "width": width + dw, "height": height + dh,
        "windowState": "normal"}})
    cdp.detach()
    page.wait_for_timeout(100)


#: Rough allowance (CSS px) for a headed Chromium window's own chrome: side borders, and the tab
#: strip plus the address bar. Only used to decide whether a *requested* viewport can possibly fit.
WINDOW_CHROME = (16, 120)


def fit_viewport_to_monitor(width: int, height: int, chrome: tuple[int, int] = WINDOW_CHROME,
                            monitors: list | None = None) -> tuple[int, int]:
    """Shrink a requested viewport so the browser window still fits on the primary monitor.

    Chromium silently clamps a window larger than the screen, so a 1920x1080 request on a 1080p
    display quietly yields a viewport ~75 px shorter than asked for - and every coordinate recorded
    against it is then wrong. Shrinking up front makes the size we ask for the size we get.

    Best effort: monitor sizes are physical px while the viewport is CSS px, so this is exact only
    at devicePixelRatio 1. `_measure()` records the truth after the window exists either way.
    """
    if monitors is None:
        from capturekarma._win import IS_WINDOWS, set_dpi_awareness
        if not IS_WINDOWS:
            return (width, height)
        from capturekarma.capture import CaptureError, list_monitors
        # Without this the enumeration reports *logical* px, so a 1920x1080 monitor at 125% scaling
        # measures 1536x864 and every viewport gets shrunk to a size that was never too big.
        set_dpi_awareness()
        try:
            monitors = list_monitors()
        except CaptureError as exc:
            log.warning("cannot enumerate monitors, using the requested viewport as-is: %s", exc)
            return (width, height)
    primary = next((m for m in monitors if m.primary), monitors[0] if monitors else None)
    if primary is None:
        return (width, height)
    max_w = max(1, primary.region.width - chrome[0])
    max_h = max(1, primary.region.height - chrome[1])
    w, h = min(width, max_w), min(height, max_h)
    if (w, h) != (width, height):
        log.warning("requested viewport %dx%d does not fit on the primary monitor (%dx%d) with the "
                    "browser's own chrome; using %dx%d instead",
                    width, height, primary.region.width, primary.region.height, w, h)
    return (w, h)


@dataclass(frozen=True)
class ViewportMetrics:
    origin_x: int   # physical px of viewport top-left on screen
    origin_y: int
    dpr: float
    css_w: int
    css_h: int


class WebDriver:
    #: Wheel events are emitted at this rate during a `wheel` step: fast enough to look continuous,
    #: slow enough that a viewer's own zoom easing keeps up.
    WHEEL_HZ = 30

    def __init__(self, headless: bool = False, window_pos: Point = (0, 0), ticker: Ticker | None = None):
        self._headless = headless
        self._window_pos = window_pos
        self._ticker = ticker or Ticker(hz=self.WHEEL_HZ)
        self._pw = None
        self._browser = None
        self._context = None
        self.page = None
        self.metrics: ViewportMetrics | None = None
        self.region: Region | None = None

    # ---- lifecycle ----
    def setup(self, scene: Scene) -> Region:
        from playwright.sync_api import Error as PWError, sync_playwright

        t = scene.target
        assert t.url is not None
        w, h = t.viewport
        if not self._headless:
            # Headless sizes the viewport directly, so there is no window to fit on a monitor.
            w, h = fit_viewport_to_monitor(w, h)
        try:
            self._pw = sync_playwright().start()
            args = [f"--window-position={self._window_pos[0]},{self._window_pos[1]}",
                    f"--window-size={w},{h + 120}", "--disable-infobars", "--no-first-run",
                    "--disable-features=TranslateUI"]
            self._browser = self._pw.chromium.launch(headless=self._headless, args=args)
            if self._headless:
                # no OS window in headless: emulate the viewport directly
                self._context = self._browser.new_context(viewport={"width": w, "height": h})
            else:
                self._context = self._browser.new_context(no_viewport=True)
            self._context.add_init_script(SCROLL_JS)
            self.page = self._context.new_page()
            if not self._headless:
                fit_window_to_viewport(self.page, self._context, w, h, self._window_pos)
            self.page.goto(t.url, wait_until="load")
            self._measure()
        except PWError as exc:
            self.teardown()
            raise DriverError(f"could not launch browser or open {t.url}: {exc}") from exc
        except BaseException:  # noqa: BLE001 - never leak a browser process; re-raised unchanged
            self.teardown()
            raise
        assert self.region is not None
        return self.region

    def _measure(self) -> None:
        assert self.page is not None
        m = self.page.evaluate(_METRICS_JS)
        dpr = float(m["dpr"])
        side = max(0.0, (m["ow"] - m["iw"]) / 2)   # headless reports outer == 0; clamp
        # oh-ih includes top chrome + bottom border (~side); bottom is ~side on Windows
        top = max(0.0, m["oh"] - m["ih"] - side)
        ox = round((m["sx"] + side) * dpr)
        oy = round((m["sy"] + top) * dpr)
        self.metrics = ViewportMetrics(ox, oy, dpr, int(m["iw"]), int(m["ih"]))
        self.region = Region(ox, oy, round(m["iw"] * dpr), round(m["ih"] * dpr))
        log.info("viewport %sx%s css @ dpr %.2f -> screen region %s", m["iw"], m["ih"], dpr, self.region)

    def teardown(self) -> None:
        for closer in (lambda: self._context and self._context.close(),
                       lambda: self._browser and self._browser.close(),
                       lambda: self._pw and self._pw.stop()):
            try:
                closer()
            except Exception as exc:  # noqa: BLE001 - teardown must run every closer; failures are logged
                log.warning("teardown: %s", exc)
        self._pw = self._browser = self._context = self.page = None

    # ---- coordinates ----
    def _m(self) -> ViewportMetrics:
        if self.metrics is None:
            raise DriverError("driver not set up")
        return self.metrics

    def to_css(self, x: int, y: int) -> tuple[float, float]:
        m = self._m()
        return ((x - m.origin_x) / m.dpr, (y - m.origin_y) / m.dpr)

    def to_screen(self, cx: float, cy: float) -> Point:
        m = self._m()
        return (round(m.origin_x + cx * m.dpr), round(m.origin_y + cy * m.dpr))

    # ---- Driver protocol ----
    def resolve(self, target: StepTarget) -> Point:
        assert self.page is not None
        m = self._m()
        if target.selector is not None:
            from playwright.sync_api import Error as PWError

            sel = target.selector
            try:
                loc = self.page.locator(sel).first
                box = loc.bounding_box() if loc.count() else None
            except PWError as exc:
                # A malformed or engine-rejected selector is a scene problem, not a crash.
                raise StepError(f"invalid or failing selector {sel!r}: {exc}") from exc
            if box is None:
                raise StepError(f"element not found or not visible: {target.selector!r}")
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            if not (0 <= cx < m.css_w and 0 <= cy < m.css_h):
                raise StepError(f"target {target.selector!r} is off-screen at css ({cx:.0f}, {cy:.0f}); "
                                "add a scroll step before it")
        else:
            assert target.at is not None
            cx, cy = target.at
        return self.to_screen(cx, cy)

    def pointer_to(self, x: int, y: int) -> None:
        assert self.page is not None
        cx, cy = self.to_css(x, y)
        self.page.mouse.move(cx, cy)

    def mouse_down(self, button: str = "left") -> None:
        assert self.page is not None
        self.page.mouse.down(button=button)

    def mouse_up(self, button: str = "left") -> None:
        assert self.page is not None
        self.page.mouse.up(button=button)

    def smooth_scroll(self, step: ScrollStep, duration: float, easing: Easing) -> None:
        assert self.page is not None
        name = next((n for n, f in EASINGS.items() if f is easing), "ease_in_out_cubic")
        try:
            self.page.evaluate(
                "([sel, by, to, ms, ease]) => window.__ckSmoothScroll(sel, by, to, ms, ease)",
                [step.container, step.by, step.to, int(duration * 1000), name])
        except Exception as exc:  # Playwright Error wraps the JS rejection
            raise StepError(f"scroll failed: {exc}") from exc

    def smooth_wheel(self, step: WheelStep, duration: float, easing: Easing) -> None:
        """Emit wheel deltas at the *current* virtual mouse position (Playwright semantics).

        The player has already moved the cursor there, so this only paces the deltas. They are
        quantised with carry-over so they sum to exactly `step.by` however the easing distributes
        them - the same technique as `win_input.wheel_steps`, but in pixels with no unit conversion.
        """
        assert self.page is not None
        n = self._ticker.n_ticks(duration)
        emitted = 0
        for i, _ in self._ticker.ticks(duration):
            target = round(step.by * easing(i / n))
            delta, emitted = target - emitted, target
            if delta:
                self.page.mouse.wheel(0, delta)
        if emitted != step.by:   # an easing that does not end at exactly 1.0 must not lose pixels
            self.page.mouse.wheel(0, step.by - emitted)

    def type_text(self, text: str, delay: float) -> None:
        assert self.page is not None
        self.page.keyboard.type(text, delay=delay * 1000)

    def press(self, key: str) -> None:
        assert self.page is not None
        self.page.keyboard.press(key)

    def screenshot(self, path: Path) -> None:
        assert self.page is not None
        self.page.screenshot(path=str(path))
