"""Record user actions in a real Chromium window into RawEvents, then into a Scene."""
from __future__ import annotations

import datetime as _dt
import json
import logging
import threading
import time
from pathlib import Path
from typing import Callable

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

    def _on_event(self, source, payload: str) -> None:
        d = json.loads(payload)
        t = self._clock() - self._t0
        kind = d["kind"]
        if kind == "click":
            at = tuple(d["at"]) if d.get("at") else None
            self.events.append(RawEvent(t=t, kind="click", selector=d.get("selector"), at=at,  # type: ignore[arg-type]
                                        button=d.get("button", "left")))
        elif kind == "scroll":
            self.events.append(RawEvent(t=t, kind="scroll", container=d.get("container"), delta=int(d["delta"])))
        elif kind == "key":
            self.events.append(RawEvent(t=t, kind="key", key=d["key"]))

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        w, h = self.viewport
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
        self.page.on("close", lambda _p: self._closed.set())
        self.page.on("framenavigated",
                     lambda f: f.parent_frame is None and self.events.append(
                         RawEvent(t=self._clock() - self._t0, kind="navigate", url=f.url)))
        self._t0 = self._clock()
        self.page.goto(self.url, wait_until="load")
        log.info("recording %s — perform the demo, press F9 (or close the browser) to stop", self.url)

    def wait(self, stop: threading.Event, poll: float = 0.1) -> None:
        while not stop.is_set() and not self._closed.is_set():
            stop.wait(poll)

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
        return Scene(name=name, target=Target(kind="web", url=self.url, viewport=self.viewport),
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
