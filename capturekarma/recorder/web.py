"""Record user actions in a real Chromium window into RawEvents, then into a Scene."""
from __future__ import annotations

import datetime as _dt
import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

from capturekarma._win import set_dpi_awareness
from capturekarma.scene import Scene, Target, dump_scene

from .events import RawEvent
from .hotkey import StopHotkey
from .smooth import SmoothConfig, smooth

log = logging.getLogger("capturekarma.recorder.web")
RECORDER_JS = (Path(__file__).parent / "web_recorder.js").read_text(encoding="utf-8")


class WebRecorder:
    def __init__(self, url: str, viewport: tuple[int, int] = (1920, 1080), headless: bool = False,
                 clock: Callable[[], float] = time.perf_counter):
        self.url = url
        self.viewport = viewport
        self._headless = headless
        self._clock = clock
        self.events: list[RawEvent] = []
        self.page = None
        self._pw = None
        self._browser = None
        self._context = None
        self._t0 = 0.0
        self._closed = threading.Event()
        #: The viewport the page actually got, measured after start(). Chromium clamps a window it
        #: cannot fit on the screen, so this is often shorter than `viewport` was asked for - and
        #: it, not the request, is the frame every recorded coordinate belongs to.
        self.actual_viewport: tuple[int, int] | None = None

    def _on_event(self, source, payload: str) -> None:
        d = json.loads(payload)
        t = self._clock() - self._t0
        kind = d["kind"]
        if kind == "click":
            at = tuple(d["at"]) if d.get("at") else None
            self.events.append(RawEvent(t=t, kind="click", selector=d.get("selector"), at=at,  # type: ignore[arg-type]
                                        button=d.get("button", "left")))
        elif kind == "drag":
            path = tuple((int(x), int(y)) for x, y in d["path"])
            self.events.append(RawEvent(t=t, kind="drag", path=path, button=d.get("button", "left"),  # type: ignore[arg-type]
                                        at=path[0], duration=float(d["duration_ms"]) / 1000.0))
        elif kind == "wheel":
            at = tuple(d["at"]) if d.get("at") else None
            self.events.append(RawEvent(t=t, kind="wheel", delta=int(d["delta"]), at=at))  # type: ignore[arg-type]
        elif kind == "scroll":
            self.events.append(RawEvent(t=t, kind="scroll", container=d.get("container"), delta=int(d["delta"])))
        elif kind == "key":
            self.events.append(RawEvent(t=t, kind="key", key=d["key"]))

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        w, h = self.viewport
        if not self._headless:
            # Before the browser window exists: Win32 must report physical px, here and for the
            # capture region the player derives from the coordinates recorded against this window.
            set_dpi_awareness()
            from capturekarma.drivers.web import fit_viewport_to_monitor
            w, h = fit_viewport_to_monitor(w, h)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self._headless,
            args=[f"--window-size={w},{h + 120}", "--window-position=0,0", "--no-first-run", "--disable-infobars"])
        self._browser.on("disconnected", lambda _b: self._closed.set())
        self._context = self._browser.new_context(viewport={"width": w, "height": h} if self._headless else None,
                                                  no_viewport=not self._headless)
        self._context.expose_binding("__ck_event", self._on_event)
        self._context.add_init_script(RECORDER_JS)
        self.page = self._context.new_page()
        if not self._headless:
            # Headed Chromium sizes the window, not the viewport: pin the page's inner size to the
            # requested viewport so `at:` coordinates recorded here match the driver on playback.
            from capturekarma.drivers.web import fit_window_to_viewport
            fit_window_to_viewport(self.page, self._context, w, h)
        self.page.on("close", lambda _p: self._closed.set())
        self.page.on("framenavigated",
                     lambda f: f.parent_frame is None and self.events.append(
                         RawEvent(t=self._clock() - self._t0, kind="navigate", url=f.url)))
        self._t0 = self._clock()
        self.page.goto(self.url, wait_until="load")
        iw, ih = self.page.evaluate("[window.innerWidth, window.innerHeight]")
        self.actual_viewport = (int(iw), int(ih))
        if self.actual_viewport != self.viewport:
            log.warning("viewport is %dx%d, not the requested %dx%d; recording against the real one",
                        iw, ih, *self.viewport)
        log.info("recording %s — perform the demo, press F9 (or close the browser) to stop", self.url)

    def wait(self, stop: threading.Event, poll: float = 0.1) -> None:
        """Block until `stop` is set or the browser goes away, pumping browser events meanwhile.

        Playwright's sync API dispatches incoming events (our __ck_event bindings, page close)
        only while the calling thread sits inside a Playwright call, so idling on the
        threading.Event alone would buffer the whole session and stamp every event with the
        time it was finally drained. Sleeping inside `wait_for_timeout` keeps them flowing.
        """
        from playwright.sync_api import Error as PlaywrightError

        while not stop.is_set() and not self._closed.is_set():
            page = self.page
            if page is None:
                return
            try:
                page.wait_for_timeout(poll * 1000)
            except PlaywrightError as exc:  # page/browser closed under us - that ends the wait
                log.debug("wait: %s", exc)
                self._closed.set()

    def stop(self) -> list[RawEvent]:
        for closer in (lambda: self._context and self._context.close(),
                       lambda: self._browser and self._browser.close(),
                       lambda: self._pw and self._pw.stop()):
            try:
                closer()
            except Exception as exc:  # noqa: BLE001 - browser may already be gone; keep closing the rest
                log.debug("stop: %s", exc)
        self._pw = self._browser = self._context = self.page = None
        return self.events

    def to_scene(self, name: str, config: SmoothConfig = SmoothConfig()) -> Scene:
        # The measured viewport, never the requested one: coordinates were recorded against it.
        viewport = self.actual_viewport or self.viewport
        return Scene(name=name, target=Target(kind="web", url=self.url, viewport=viewport),
                     steps=tuple(smooth(self.events, config)))


def record_web(url: str, out_path: Path, viewport: tuple[int, int] = (1920, 1080), name: str | None = None) -> Path:
    rec = WebRecorder(url, viewport)
    hotkey = StopHotkey()
    rec.start()
    hotkey.start()
    try:
        rec.wait(hotkey.triggered)
    finally:
        hotkey.stop()
        rec.stop()
    scene = rec.to_scene(name or Path(out_path).stem)
    header = f"recorded from {url} on {_dt.date.today().isoformat()} — edit freely; durations are derived when omitted"
    dump_scene(scene, out_path, header=header)
    log.info("wrote %s (%d steps)", out_path, len(scene.steps))
    return Path(out_path)
