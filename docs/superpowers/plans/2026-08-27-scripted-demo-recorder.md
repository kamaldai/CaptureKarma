# Scripted Demo Recorder (CaptureKarma v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v1 wheel-event screen recorder with a record-then-replay demo tool: a recorder writes a YAML scene of what the user did, a player replays it with deterministic eased cursor/scroll motion and a rendered cursor overlay while ffmpeg captures the region to 60 fps H.264 MP4.

**Architecture:** Plain Python library (`capturekarma/`) with dumb `Driver` implementations (Playwright for web, Win32 `SendInput` for desktop), a player that owns all motion via a drift-corrected 120 Hz ticker, a Win32 layered click-through overlay window that draws the cursor, and ffmpeg `ddagrab` capture (NVENC or libx264) with `draw_mouse=0`. A typer CLI (`ck`) and a thin PySide6 GUI call the same library functions.

**Tech Stack:** Python 3.12, uv, Playwright (Chromium), pynput, ctypes (user32/gdi32/winmm/shcore), Pillow, numpy, PyYAML, typer, PySide6, imageio-ffmpeg (bundled ffmpeg 7.1 with ddagrab/nvenc/libx264 verified on the dev machine), pytest.

**Spec:** `docs/superpowers/specs/2026-08-27-scripted-demo-recorder-design.md`

## Global Constraints

- Python `>=3.12`; project managed with `uv` (`uv sync`, `uv run ...`). `.python-version` is `3.12`.
- Windows 10/11 only for anything touching the screen. Tests that need Windows are marked `@pytest.mark.win32`; tests that need a browser are marked `@pytest.mark.integration`. Pure-logic tests run anywhere.
- **All coordinates in player, overlay, capture, desktop driver are physical screen pixels.** Scene desktop targets are region-relative; scene web `at` targets are viewport CSS px.
- **No swallowed exceptions.** Never `except Exception: print(...)`. Raise `SceneError`, `StepError`, `DriverError`, `CaptureError` with context; let the CLI/GUI render them.
- **No runtime randomness** in motion. Deterministic output for identical scene.
- Drivers stay dumb: no easing/timing inside `pointer_to`, `mouse_down`, `mouse_up`, `type_text`, `press`. Only `smooth_scroll` is time-aware.
- Output MP4: H.264, `yuv420p`, `+faststart`, fps from scene (default 60), even dimensions.
- Use `ctypes` for Win32 (no pywin32). Use `logging` (logger name `capturekarma.*`), never `print`, in library code.
- Commit after every task with the message given. Run `uv run pytest -q` before each commit; all non-skipped tests must pass.
- Encoding: all source files UTF-8, LF line endings (`.gitattributes` enforces `* text=auto eol=lf`).

---

## File structure

```
pyproject.toml                    uv project, deps, `ck` entry point, pytest config
.gitattributes                    eol=lf
CLAUDE.md                         project guide for Claude Code
README.md                         user docs (rewritten)
capturekarma/
  __init__.py                     __version__
  _win.py                         set_dpi_awareness(), high_res_timer(), IS_WINDOWS
  scene/
    __init__.py                   re-exports
    model.py                      dataclasses: Region, Point, Target, Output, CursorConfig, Defaults, StepTarget, steps, Scene, EASING_NAMES
    loader.py                     SceneError, parse_scene(dict), load_scene(path), scene_to_dict, dump_scene
  motion/
    __init__.py
    easing.py                     Easing type, EASINGS, get_easing
    path.py                       move_duration, scroll_duration, bezier_path
    ticker.py                     Ticker (hz, ticks(duration), sleep_until)
  capture/
    __init__.py
    monitors.py                   Monitor, list_monitors, monitor_for_region, virtual_screen (win32 ctypes)
    ffmpeg.py                     find_ffmpeg, probe, Capabilities, even_region, build_capture_args
    recorder.py                   CaptureError, ScreenCapture, start_capture (ddagrab→gdigrab fallback)
  cursor/
    __init__.py
    sprites.py                    FRAME_SIZE, HOTSPOT, Ripple, load_sprite, render_frame, default arrow generator
    overlay.py                    CursorOverlay (win32 layered window thread)
  drivers/
    __init__.py
    base.py                       Driver protocol, StepError, DriverError, WindowNotFound
    win_input.py                  ctypes SendInput/SetCursorPos/window helpers
    desktop.py                    DesktopDriver
    web.py                        WebDriver (Playwright)
    web_scroll.js                 window.__ckSmoothScroll
  recorder/
    __init__.py
    events.py                     RawEvent
    smooth.py                     SmoothConfig, smooth(events) -> steps
    hotkey.py                     StopHotkey (pynput)
    web.py                        WebRecorder
    web_recorder.js               init script: listeners + uniqueSelector
    desktop.py                    DesktopRecorder (pynput)
  player/
    __init__.py
    timeline.py                   CursorTimeline
    player.py                     PlayOptions, RunResult, Player
  doctor.py                       Check, run_doctor
  cli.py                          typer app: record web|desktop, play, doctor
  gui/
    __init__.py
    worker.py                     Worker(QThread) with log/done/failed signals
    main_window.py                MainWindow
    app.py                        main()
examples/
  web-demo.yaml
  desktop-notepad.yaml
tests/
  conftest.py                     markers, fixture_url fixture
  fixtures/page.html              deterministic test page (tall, buttons, input, inner scroll box)
  test_scene.py, test_easing.py, test_path.py, test_ticker.py, test_monitors.py,
  test_ffmpeg_args.py, test_capture_win32.py, test_sprites.py, test_overlay_win32.py,
  test_win_input.py, test_desktop_driver.py, test_web_driver.py, test_smooth.py,
  test_web_recorder.py, test_desktop_recorder.py, test_player.py, test_cli.py,
  test_e2e_win32.py
```

---

### Task 1: Repo scaffold and old-code removal

**Files:**
- Create: `pyproject.toml` (replace), `.gitattributes`, `capturekarma/__init__.py`, `capturekarma/_win.py`, all package `__init__.py` files listed above (empty), `tests/conftest.py`, `tests/fixtures/page.html`, `tests/test_scaffold.py`, `CLAUDE.md` (initial)
- Delete: `CaptureKarma/` (whole dir), `marketing_screen_capture.py`, `main.py`, `requirements.txt`, `CaptureKarma.spec`, `.vscode/settings.json` (already deleted in working tree), `uv.lock` (regenerated)
- Keep: `LICENSE`, `README.md` (rewritten in Task 13), `resources/`, `.gitignore`, `.python-version`

**Interfaces:**
- Produces: `capturekarma._win.IS_WINDOWS: bool`, `set_dpi_awareness() -> bool`, `high_res_timer()` context manager. Pytest markers `win32`, `integration`. Fixture `fixture_url` (file:// URL of `tests/fixtures/page.html`).

- [ ] **Step 1: Remove old code**

```bash
git rm -r -q CaptureKarma marketing_screen_capture.py main.py requirements.txt CaptureKarma.spec
git rm -q --cached .vscode/settings.json 2>/dev/null || true
rm -f uv.lock
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "capturekarma"
version = "2.0.0a1"
description = "Record a product demo once, replay it with cinematic cursor and scroll motion, capture to MP4."
readme = "README.md"
license = { file = "LICENSE" }
requires-python = ">=3.12"
dependencies = [
    "playwright>=1.47",
    "pynput>=1.7.7",
    "Pillow>=10.4",
    "numpy>=2.0",
    "PyYAML>=6.0",
    "typer>=0.12",
    "PySide6>=6.7",
    "imageio-ffmpeg>=0.5",
]

[project.scripts]
ck = "capturekarma.cli:main"

[dependency-groups]
dev = ["pytest>=8.3"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["capturekarma"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "win32: needs a Windows desktop session (screen, Win32 APIs)",
    "integration: needs Playwright Chromium installed",
]
addopts = "-ra"
```

- [ ] **Step 3: Write `.gitattributes`**

```
* text=auto eol=lf
*.png binary
*.ico binary
*.icns binary
```

- [ ] **Step 4: Write `capturekarma/__init__.py` and empty package inits**

`capturekarma/__init__.py`:
```python
"""CaptureKarma — record a demo once, replay it cinematically, capture to MP4."""

__version__ = "2.0.0a1"
```

Create empty `__init__.py` in: `capturekarma/scene`, `capturekarma/motion`, `capturekarma/capture`, `capturekarma/cursor`, `capturekarma/drivers`, `capturekarma/recorder`, `capturekarma/player`, `capturekarma/gui`, and `tests/__init__.py` (empty).

- [ ] **Step 5: Write `capturekarma/_win.py`**

```python
"""Small Win32 helpers shared across the package. Safe to import on any OS."""
from __future__ import annotations

import contextlib
import logging
import sys

IS_WINDOWS = sys.platform == "win32"
log = logging.getLogger("capturekarma.win")


def set_dpi_awareness() -> bool:
    """Declare per-monitor-v2 DPI awareness so Win32 APIs return physical pixels.

    Returns True if awareness is set (or already set), False on non-Windows or failure.
    Must be called before any window is created.
    """
    if not IS_WINDOWS:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
    try:
        if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return True
        # ERROR_ACCESS_DENIED (5) means awareness was already set for this process.
        if ctypes.get_last_error() == 5 or ctypes.GetLastError() == 5:
            return True
    except AttributeError:
        pass  # pre-1703 Windows: fall through to shcore
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        return True
    except Exception as exc:  # noqa: BLE001 - reported to caller via return value
        log.warning("Could not set DPI awareness: %s", exc)
        return False


@contextlib.contextmanager
def high_res_timer():
    """Request 1 ms scheduler resolution while the block runs (no-op off Windows)."""
    if not IS_WINDOWS:
        yield
        return
    import ctypes

    winmm = ctypes.windll.winmm
    winmm.timeBeginPeriod(1)
    try:
        yield
    finally:
        winmm.timeEndPeriod(1)
```

- [ ] **Step 6: Write `tests/conftest.py`**

```python
from __future__ import annotations

import sys
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    skip_win = pytest.mark.skip(reason="requires a Windows desktop session")
    for item in items:
        if "win32" in item.keywords and sys.platform != "win32":
            item.add_marker(skip_win)


@pytest.fixture
def fixture_url() -> str:
    return (FIXTURES / "page.html").resolve().as_uri()
```

- [ ] **Step 7: Write `tests/fixtures/page.html`**

A deterministic page: 4000 px tall, a header, three buttons with distinct ids/text, a text input, and an inner scrollable box.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>CaptureKarma Fixture</title>
<style>
  html, body { margin: 0; font-family: sans-serif; }
  body { height: 4000px; background: linear-gradient(#f8fafc, #cbd5e1); }
  header { height: 80px; background: #1e293b; color: #fff; display: flex; align-items: center; padding: 0 24px; }
  .row { display: flex; gap: 16px; padding: 24px; }
  button { padding: 12px 20px; font-size: 16px; }
  #email { width: 260px; padding: 8px; font-size: 16px; }
  #box { margin: 24px; width: 300px; height: 200px; overflow-y: auto; border: 2px solid #334155; background: #fff; }
  #box .inner { height: 1500px; background: repeating-linear-gradient(#fff 0 49px, #e2e8f0 49px 50px); }
  #deep { position: absolute; top: 3000px; left: 24px; }
</style>
</head>
<body>
<header><h1>Fixture Page</h1></header>
<div class="row">
  <button id="btn-primary" data-testid="primary">Primary</button>
  <button id="btn-secondary">Secondary</button>
  <button class="plain">Plain</button>
  <input id="email" type="email" placeholder="email">
</div>
<div id="box"><div class="inner"></div></div>
<button id="deep">Deep Button</button>
</body>
</html>
```

- [ ] **Step 8: Write `tests/test_scaffold.py`**

```python
import capturekarma
from capturekarma import _win


def test_version():
    assert capturekarma.__version__.startswith("2.")


def test_high_res_timer_is_a_context_manager():
    with _win.high_res_timer():
        pass


def test_set_dpi_awareness_returns_bool():
    assert isinstance(_win.set_dpi_awareness(), bool)
```

- [ ] **Step 9: Write initial `CLAUDE.md`**

```markdown
# CaptureKarma (v2)

Record a product demo once, replay it with cinematic cursor/scroll motion, capture to MP4.
Design: `docs/superpowers/specs/2026-08-27-scripted-demo-recorder-design.md`.
Plan: `docs/superpowers/plans/2026-08-27-scripted-demo-recorder.md`.

## Commands

- `uv sync` — install (Python 3.12, managed by uv)
- `uv run playwright install chromium` — one-time browser install
- `uv run pytest -q` — unit tests (Windows-only and browser tests auto-skip when unavailable)
- `uv run pytest -q -m "win32 or integration"` — the full set, on a Windows desktop with Chromium
- `uv run ck doctor` — check ffmpeg/ddagrab/NVENC/Playwright
- `uv run ck record web <url> -o scene.yaml`, `uv run ck play scene.yaml`

## Layout

`capturekarma/scene` (YAML model), `motion` (easing/paths/ticker), `cursor` (overlay), `capture` (ffmpeg),
`drivers` (web = Playwright, desktop = Win32 SendInput), `recorder` (events → smoothing → scene),
`player` (orchestrates a run), `cli.py`, `doctor.py`, `gui/` (thin PySide6 shell).

## Conventions

- Physical screen pixels everywhere except scene files (desktop targets region-relative, web `at` in viewport CSS px).
- Drivers are dumb; the player owns motion and timing. Only `smooth_scroll` is time-aware inside a driver.
- No swallowed exceptions; raise `SceneError` / `StepError` / `DriverError` / `CaptureError`.
- No runtime randomness in motion. `logging`, never `print`, in library code. ctypes for Win32, no pywin32.
- TDD: each task lands with its tests. Mark Windows-only tests `win32`, browser tests `integration`.

## Working agreement

The main Claude session orchestrates (design, plan, review, integrate). Implementation tasks are dispatched to
Opus subagents (`model: "opus"`), one task at a time, each reviewed before the next.
```

- [ ] **Step 10: Install and run**

```bash
uv sync
uv run pytest -q
```
Expected: 3 passed.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "chore: scaffold capturekarma v2 package, remove v1 code"
```

---

### Task 2: Scene model, loader, validation

**Files:**
- Create: `capturekarma/scene/model.py`, `capturekarma/scene/loader.py`, `capturekarma/scene/__init__.py` (re-exports)
- Test: `tests/test_scene.py`

**Interfaces:**
- Produces (model): `Point = tuple[int, int]`; `Region(x, y, width, height)` frozen with `.right`, `.bottom`, `.center -> Point`, `.contains(other: Region) -> bool`; `Target(kind, url, viewport, window, region)`; `Output(fps, dir, lead_in, lead_out)`; `CursorConfig(visible, style, ripple, speed)`; `Defaults(easing, hold)`; `StepTarget(selector, at)`; steps `WaitStep(seconds)`, `MoveStep(to)`, `ClickStep(to, button)`, `ScrollStep(by, to, container)`, `TypeStep(text, delay)`, `PressStep(key)`, `CursorStep(visible)` — all with `duration`, `easing`, `hold` optional; `Step` union; `Scene(name, target, steps, output, cursor, defaults, version)`; `EASING_NAMES`.
- Produces (loader): `SceneError(ValueError)` with `.step_index: int | None`; `parse_scene(data: dict) -> Scene`; `load_scene(path) -> Scene`; `scene_to_dict(scene) -> dict`; `dump_scene(scene, path, header: str | None = None) -> None`.

- [ ] **Step 1: Write failing tests `tests/test_scene.py`**

```python
from pathlib import Path

import pytest
import yaml

from capturekarma.scene import (
    ClickStep, CursorStep, MoveStep, PressStep, Region, SceneError, ScrollStep,
    StepTarget, TypeStep, WaitStep, dump_scene, load_scene, parse_scene, scene_to_dict,
)

WEB = {
    "version": 1,
    "name": "demo",
    "target": {"kind": "web", "url": "https://example.com", "viewport": [1280, 720]},
    "steps": [
        {"wait": 1.0},
        {"move": {"to": "text=Pricing"}},
        {"click": {}},
        {"scroll": {"by": 900, "duration": 2.5}},
        {"type": {"text": "hi", "delay": 0.06}},
        {"press": "Enter"},
        {"cursor": "hidden"},
        {"move": {"to": [640, 400], "duration": 1.2}},
        {"cursor": "visible"},
    ],
}


def test_parse_web_scene_defaults_and_steps():
    s = parse_scene(WEB)
    assert s.name == "demo" and s.target.kind == "web" and s.target.viewport == (1280, 720)
    assert s.output.fps == 60 and s.output.lead_in == 0.5 and s.cursor.speed == 1400
    assert s.defaults.easing == "ease_in_out_cubic" and s.defaults.hold == 0.6
    assert s.steps[0] == WaitStep(seconds=1.0)
    assert s.steps[1] == MoveStep(to=StepTarget(selector="text=Pricing"))
    assert s.steps[2] == ClickStep()
    assert s.steps[3] == ScrollStep(by=900, duration=2.5)
    assert s.steps[4] == TypeStep(text="hi", delay=0.06)
    assert s.steps[5] == PressStep(key="Enter")
    assert s.steps[6] == CursorStep(visible=False)
    assert s.steps[7] == MoveStep(to=StepTarget(at=(640, 400)), duration=1.2)


def test_parse_desktop_scene_with_window():
    s = parse_scene({"version": 1, "name": "d", "target": {"kind": "desktop", "window": "Notepad"},
                     "steps": [{"click": {"to": [10, 20]}}]})
    assert s.steps[0] == ClickStep(to=StepTarget(at=(10, 20)))


def test_parse_desktop_scene_with_region():
    s = parse_scene({"version": 1, "name": "d", "target": {"kind": "desktop", "region": [0, 0, 800, 600]},
                     "steps": []})
    assert s.target.region == Region(0, 0, 800, 600)


@pytest.mark.parametrize("bad, msg", [
    ({**WEB, "version": 2}, "version"),
    ({**WEB, "name": ""}, "name"),
    ({**WEB, "target": {"kind": "web"}}, "url"),
    ({**WEB, "target": {"kind": "desktop"}}, "window"),
    ({**WEB, "target": {"kind": "tv", "url": "x"}}, "kind"),
    ({**WEB, "bogus": 1}, "bogus"),
    ({**WEB, "steps": [{"jump": 1}]}, "jump"),
    ({**WEB, "steps": [{"move": {"to": "a"}, "click": {}}]}, "exactly one"),
    ({**WEB, "steps": [{"scroll": {}}]}, "by"),
    ({**WEB, "steps": [{"scroll": {"by": 1, "to": 2}}]}, "by"),
    ({**WEB, "steps": [{"wait": -1}]}, "negative"),
    ({**WEB, "steps": [{"move": {"to": "a", "duration": -1}}]}, "negative"),
    ({**WEB, "steps": [{"move": {"to": "a", "easing": "bouncy"}}]}, "easing"),
    ({**WEB, "steps": [{"cursor": "sometimes"}]}, "cursor"),
    ({**WEB, "steps": [{"move": {"to": "a", "bogus": 1}}]}, "bogus"),
    ({**WEB, "output": {"fps": 0}}, "fps"),
])
def test_invalid_scenes_raise_scene_error(bad, msg):
    with pytest.raises(SceneError) as ei:
        parse_scene(bad)
    assert msg in str(ei.value)


def test_step_index_is_reported():
    with pytest.raises(SceneError) as ei:
        parse_scene({**WEB, "steps": [{"wait": 1}, {"scroll": {}}]})
    assert ei.value.step_index == 1 and "step 2" in str(ei.value)


def test_desktop_rejects_selector_and_container_and_scroll_to():
    base = {"version": 1, "name": "d", "target": {"kind": "desktop", "window": "N"}}
    with pytest.raises(SceneError, match="selector"):
        parse_scene({**base, "steps": [{"move": {"to": "text=x"}}]})
    with pytest.raises(SceneError, match="in"):
        parse_scene({**base, "steps": [{"scroll": {"by": 1, "in": "#m"}}]})
    with pytest.raises(SceneError, match="to"):
        parse_scene({**base, "steps": [{"scroll": {"to": 100}}]})


def test_round_trip_through_yaml(tmp_path: Path):
    s = parse_scene(WEB)
    p = tmp_path / "s.yaml"
    dump_scene(s, p, header="recorded from https://example.com on 2026-08-27")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# recorded from https://example.com on 2026-08-27\n")
    assert load_scene(p) == s
    assert yaml.safe_load(text)["steps"][6] == {"cursor": "hidden"}


def test_scene_to_dict_omits_defaults():
    d = scene_to_dict(parse_scene(WEB))
    assert d["steps"][2] == {"click": {}}
    assert d["steps"][5] == {"press": "Enter"}
    assert "duration" not in d["steps"][1]["move"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_scene.py -q`
Expected: ImportError / collection error.

- [ ] **Step 3: Write `capturekarma/scene/model.py`**

```python
"""Scene data model. Frozen dataclasses; parsing/validation lives in loader.py."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

Point = tuple[int, int]

EASING_NAMES: tuple[str, ...] = ("linear", "ease_in_out_cubic", "ease_out_cubic", "ease_in_out_quint")


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def contains(self, other: "Region") -> bool:
        return (self.x <= other.x and self.y <= other.y
                and other.right <= self.right and other.bottom <= self.bottom)


@dataclass(frozen=True)
class Target:
    kind: Literal["web", "desktop"]
    url: str | None = None
    viewport: tuple[int, int] = (1920, 1080)
    window: str | None = None
    region: Region | None = None


@dataclass(frozen=True)
class Output:
    fps: int = 60
    dir: str = "~/Videos/CaptureKarma"
    lead_in: float = 0.5
    lead_out: float = 0.5


@dataclass(frozen=True)
class CursorConfig:
    visible: bool = True
    style: str = "default"
    ripple: bool = True
    speed: float = 1400.0


@dataclass(frozen=True)
class Defaults:
    easing: str = "ease_in_out_cubic"
    hold: float = 0.6


@dataclass(frozen=True)
class StepTarget:
    """Web: selector (Playwright) or `at` in viewport CSS px. Desktop: `at` region-relative px."""
    selector: str | None = None
    at: Point | None = None


@dataclass(frozen=True, kw_only=True)
class StepBase:
    duration: float | None = None
    easing: str | None = None
    hold: float | None = None


@dataclass(frozen=True, kw_only=True)
class WaitStep(StepBase):
    seconds: float


@dataclass(frozen=True, kw_only=True)
class MoveStep(StepBase):
    to: StepTarget


@dataclass(frozen=True, kw_only=True)
class ClickStep(StepBase):
    to: StepTarget | None = None
    button: Literal["left", "right", "middle"] = "left"


@dataclass(frozen=True, kw_only=True)
class ScrollStep(StepBase):
    by: int | None = None          # positive = down
    to: int | None = None          # absolute offset (web only)
    container: str | None = None   # selector of scroll container (web only)


@dataclass(frozen=True, kw_only=True)
class TypeStep(StepBase):
    text: str
    delay: float = 0.05


@dataclass(frozen=True, kw_only=True)
class PressStep(StepBase):
    key: str


@dataclass(frozen=True, kw_only=True)
class CursorStep(StepBase):
    visible: bool


Step = Union[WaitStep, MoveStep, ClickStep, ScrollStep, TypeStep, PressStep, CursorStep]


@dataclass(frozen=True)
class Scene:
    name: str
    target: Target
    steps: tuple[Step, ...]
    output: Output = field(default_factory=Output)
    cursor: CursorConfig = field(default_factory=CursorConfig)
    defaults: Defaults = field(default_factory=Defaults)
    version: int = 1
```

Note `Scene.steps` is a **tuple** (hashable/frozen); the loader converts lists.

- [ ] **Step 4: Write `capturekarma/scene/loader.py`**

```python
"""YAML <-> Scene with strict validation."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from .model import (
    EASING_NAMES, ClickStep, CursorConfig, CursorStep, Defaults, MoveStep, Output, Point,
    PressStep, Region, Scene, ScrollStep, Step, StepTarget, Target, TypeStep, WaitStep,
)

STEP_KEYS = ("wait", "move", "click", "scroll", "type", "press", "cursor")
OVERRIDE_KEYS = ("duration", "easing", "hold")


class SceneError(ValueError):
    def __init__(self, message: str, step_index: int | None = None):
        prefix = f"step {step_index + 1}: " if step_index is not None else ""
        super().__init__(prefix + message)
        self.step_index = step_index


def _require_keys(d: dict, allowed: tuple[str, ...], where: str, idx: int | None = None) -> None:
    unknown = sorted(set(d) - set(allowed))
    if unknown:
        raise SceneError(f"{where}: unknown key(s) {', '.join(unknown)}", idx)


def _point(v: Any, where: str, idx: int | None) -> Point:
    if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(n, int) for n in v)):
        raise SceneError(f"{where}: expected [x, y] integers, got {v!r}", idx)
    return (int(v[0]), int(v[1]))


def _non_negative(v: Any, name: str, idx: int | None) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
        raise SceneError(f"{name} must be a non-negative number, got {v!r} (negative or invalid)", idx)
    return float(v)


def _target(v: Any, kind: str, idx: int) -> StepTarget:
    if isinstance(v, str):
        if kind == "desktop":
            raise SceneError("desktop scenes cannot use a selector target; use [x, y]", idx)
        if not v:
            raise SceneError("selector must not be empty", idx)
        return StepTarget(selector=v)
    return StepTarget(at=_point(v, "to", idx))


def _overrides(d: dict, idx: int) -> dict:
    out: dict[str, Any] = {}
    if "duration" in d:
        out["duration"] = _non_negative(d["duration"], "duration", idx)
    if "hold" in d:
        out["hold"] = _non_negative(d["hold"], "hold", idx)
    if "easing" in d:
        if d["easing"] not in EASING_NAMES:
            raise SceneError(f"unknown easing {d['easing']!r}; choose from {', '.join(EASING_NAMES)}", idx)
        out["easing"] = d["easing"]
    return out


def _parse_step(raw: Any, kind: str, idx: int) -> Step:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise SceneError("each step must be a mapping with exactly one key "
                         f"(one of {', '.join(STEP_KEYS)}), got {raw!r}", idx)
    (key, val), = raw.items()
    if key not in STEP_KEYS:
        raise SceneError(f"unknown step type {key!r}; choose from {', '.join(STEP_KEYS)}", idx)

    if key == "wait":
        if isinstance(val, dict):
            _require_keys(val, ("seconds",) + OVERRIDE_KEYS, "wait", idx)
            return WaitStep(seconds=_non_negative(val.get("seconds", 0), "wait", idx), **_overrides(val, idx))
        return WaitStep(seconds=_non_negative(val, "wait", idx))
    if key == "press":
        if isinstance(val, dict):
            _require_keys(val, ("key",) + OVERRIDE_KEYS, "press", idx)
            k = val.get("key")
        else:
            k = val
        if not isinstance(k, str) or not k:
            raise SceneError("press needs a key name, e.g. Enter", idx)
        return PressStep(key=k, **(_overrides(val, idx) if isinstance(val, dict) else {}))
    if key == "cursor":
        if val not in ("visible", "hidden"):
            raise SceneError(f"cursor must be 'visible' or 'hidden', got {val!r}", idx)
        return CursorStep(visible=(val == "visible"))

    if not isinstance(val, dict):
        raise SceneError(f"{key} step must be a mapping, got {val!r}", idx)
    ov = _overrides(val, idx)
    if key == "move":
        _require_keys(val, ("to",) + OVERRIDE_KEYS, "move", idx)
        if "to" not in val:
            raise SceneError("move needs a 'to' target", idx)
        return MoveStep(to=_target(val["to"], kind, idx), **ov)
    if key == "click":
        _require_keys(val, ("to", "button") + OVERRIDE_KEYS, "click", idx)
        button = val.get("button", "left")
        if button not in ("left", "right", "middle"):
            raise SceneError(f"click button must be left/right/middle, got {button!r}", idx)
        to = _target(val["to"], kind, idx) if "to" in val else None
        return ClickStep(to=to, button=button, **ov)
    if key == "scroll":
        _require_keys(val, ("by", "to", "in") + OVERRIDE_KEYS, "scroll", idx)
        has_by, has_to = "by" in val, "to" in val
        if has_by == has_to:
            raise SceneError("scroll needs exactly one of 'by' or 'to'", idx)
        if kind == "desktop":
            if has_to:
                raise SceneError("scroll 'to' is only supported for web scenes; use 'by'", idx)
            if "in" in val:
                raise SceneError("scroll 'in' (container) is only supported for web scenes", idx)
        for k in ("by", "to"):
            if k in val and (not isinstance(val[k], int) or isinstance(val[k], bool)):
                raise SceneError(f"scroll '{k}' must be an integer number of pixels", idx)
        return ScrollStep(by=val.get("by"), to=val.get("to"), container=val.get("in"), **ov)
    # type
    _require_keys(val, ("text", "delay") + OVERRIDE_KEYS, "type", idx)
    if not isinstance(val.get("text"), str):
        raise SceneError("type needs a 'text' string", idx)
    return TypeStep(text=val["text"], delay=_non_negative(val.get("delay", 0.05), "delay", idx), **ov)


def parse_scene(data: Any) -> Scene:
    if not isinstance(data, dict):
        raise SceneError("scene file must be a mapping at the top level")
    _require_keys(data, ("version", "name", "target", "output", "cursor", "defaults", "steps"), "scene")
    if data.get("version") != 1:
        raise SceneError(f"unsupported scene version {data.get('version')!r}; expected 1")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SceneError("scene needs a non-empty 'name'")

    t = data.get("target")
    if not isinstance(t, dict):
        raise SceneError("scene needs a 'target' mapping")
    _require_keys(t, ("kind", "url", "viewport", "window", "region"), "target")
    kind = t.get("kind")
    if kind not in ("web", "desktop"):
        raise SceneError(f"target.kind must be 'web' or 'desktop', got {kind!r}")
    if kind == "web" and not t.get("url"):
        raise SceneError("web target needs a 'url'")
    if kind == "desktop" and not (t.get("window") or t.get("region")):
        raise SceneError("desktop target needs a 'window' title or a 'region' [x, y, w, h]")
    viewport = (1920, 1080)
    if "viewport" in t:
        vp = t["viewport"]
        if not (isinstance(vp, list) and len(vp) == 2 and all(isinstance(n, int) and n > 0 for n in vp)):
            raise SceneError("target.viewport must be [width, height] positive integers")
        viewport = (vp[0], vp[1])
    region = None
    if t.get("region") is not None:
        r = t["region"]
        if not (isinstance(r, list) and len(r) == 4 and all(isinstance(n, int) for n in r)) or r[2] <= 0 or r[3] <= 0:
            raise SceneError("target.region must be [x, y, width, height] with positive size")
        region = Region(*r)
    target = Target(kind=kind, url=t.get("url"), viewport=viewport, window=t.get("window"), region=region)

    o = data.get("output", {}) or {}
    _require_keys(o, ("fps", "dir", "lead_in", "lead_out"), "output")
    fps = o.get("fps", 60)
    if not isinstance(fps, int) or isinstance(fps, bool) or not 1 <= fps <= 240:
        raise SceneError(f"output.fps must be an integer 1..240, got {fps!r}")
    output = Output(fps=fps, dir=str(o.get("dir", Output.dir)),
                    lead_in=_non_negative(o.get("lead_in", 0.5), "output.lead_in", None),
                    lead_out=_non_negative(o.get("lead_out", 0.5), "output.lead_out", None))

    c = data.get("cursor", {}) or {}
    _require_keys(c, ("visible", "style", "ripple", "speed"), "cursor")
    speed = c.get("speed", 1400)
    if not isinstance(speed, (int, float)) or speed <= 0:
        raise SceneError("cursor.speed must be a positive number (px/s)")
    cursor = CursorConfig(visible=bool(c.get("visible", True)), style=str(c.get("style", "default")),
                          ripple=bool(c.get("ripple", True)), speed=float(speed))

    d = data.get("defaults", {}) or {}
    _require_keys(d, ("easing", "hold"), "defaults")
    easing = d.get("easing", "ease_in_out_cubic")
    if easing not in EASING_NAMES:
        raise SceneError(f"defaults.easing unknown easing {easing!r}; choose from {', '.join(EASING_NAMES)}")
    defaults = Defaults(easing=easing, hold=_non_negative(d.get("hold", 0.6), "defaults.hold", None))

    raw_steps = data.get("steps", [])
    if not isinstance(raw_steps, list):
        raise SceneError("'steps' must be a list")
    steps = tuple(_parse_step(s, kind, i) for i, s in enumerate(raw_steps))
    return Scene(name=name.strip(), target=target, steps=steps, output=output, cursor=cursor,
                 defaults=defaults, version=1)


def load_scene(path: str | Path) -> Scene:
    p = Path(path)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SceneError(f"{p}: invalid YAML: {exc}") from exc
    except OSError as exc:
        raise SceneError(f"{p}: cannot read scene file: {exc}") from exc
    return parse_scene(data)


def _target_out(t: StepTarget) -> Any:
    return t.selector if t.selector is not None else list(t.at)  # type: ignore[arg-type]


def _step_to_dict(step: Step) -> dict:
    ov = {k: v for k, v in (("duration", step.duration), ("easing", step.easing), ("hold", step.hold)) if v is not None}
    if isinstance(step, WaitStep):
        return {"wait": step.seconds} if not ov else {"wait": {"seconds": step.seconds, **ov}}
    if isinstance(step, MoveStep):
        return {"move": {"to": _target_out(step.to), **ov}}
    if isinstance(step, ClickStep):
        body: dict = {}
        if step.to is not None:
            body["to"] = _target_out(step.to)
        if step.button != "left":
            body["button"] = step.button
        return {"click": {**body, **ov}}
    if isinstance(step, ScrollStep):
        body = {"by": step.by} if step.by is not None else {"to": step.to}
        if step.container:
            body["in"] = step.container
        return {"scroll": {**body, **ov}}
    if isinstance(step, TypeStep):
        body = {"text": step.text}
        if step.delay != 0.05:
            body["delay"] = step.delay
        return {"type": {**body, **ov}}
    if isinstance(step, PressStep):
        return {"press": step.key} if not ov else {"press": {"key": step.key, **ov}}
    if isinstance(step, CursorStep):
        return {"cursor": "visible" if step.visible else "hidden"}
    raise TypeError(f"unknown step {step!r}")


def scene_to_dict(scene: Scene) -> dict:
    t: dict[str, Any] = {"kind": scene.target.kind}
    if scene.target.kind == "web":
        t["url"] = scene.target.url
        t["viewport"] = list(scene.target.viewport)
    else:
        if scene.target.window:
            t["window"] = scene.target.window
        if scene.target.region:
            r = scene.target.region
            t["region"] = [r.x, r.y, r.width, r.height]
    return {
        "version": 1,
        "name": scene.name,
        "target": t,
        "output": asdict(scene.output),
        "cursor": asdict(scene.cursor),
        "defaults": asdict(scene.defaults),
        "steps": [_step_to_dict(s) for s in scene.steps],
    }


class _Dumper(yaml.SafeDumper):
    pass


def _represent_list_flow(dumper: yaml.SafeDumper, data: list):
    # Short numeric lists ([x, y], [w, h], [x, y, w, h]) render inline for readability.
    flow = len(data) <= 4 and all(isinstance(v, (int, float)) for v in data)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=flow)


_Dumper.add_representer(list, _represent_list_flow)


def dump_scene(scene: Scene, path: str | Path, header: str | None = None) -> None:
    text = yaml.dump(scene_to_dict(scene), Dumper=_Dumper, sort_keys=False, allow_unicode=True)
    if header:
        text = "# " + header.strip() + "\n" + text
    Path(path).write_text(text, encoding="utf-8", newline="\n")
```

- [ ] **Step 5: Write `capturekarma/scene/__init__.py`**

```python
from .loader import SceneError, dump_scene, load_scene, parse_scene, scene_to_dict
from .model import (
    EASING_NAMES, ClickStep, CursorConfig, CursorStep, Defaults, MoveStep, Output, Point, PressStep,
    Region, Scene, ScrollStep, Step, StepBase, StepTarget, Target, TypeStep, WaitStep,
)

__all__ = [n for n in dir() if not n.startswith("_")]
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_scene.py -q`
Expected: all pass. If a parametrized message assertion fails, adjust the error text in the loader (not the test) so the keyword in the test appears.

- [ ] **Step 7: Commit**

```bash
git add capturekarma/scene tests/test_scene.py
git commit -m "feat(scene): YAML scene model, loader, strict validation"
```

---

### Task 3: Motion — easing, paths, ticker

**Files:**
- Create: `capturekarma/motion/easing.py`, `capturekarma/motion/path.py`, `capturekarma/motion/ticker.py`, `capturekarma/motion/__init__.py`
- Test: `tests/test_easing.py`, `tests/test_path.py`, `tests/test_ticker.py`

**Interfaces:**
- Consumes: `capturekarma.scene.model.Point`, `EASING_NAMES`; `capturekarma._win.high_res_timer`.
- Produces: `Easing = Callable[[float], float]`; `EASINGS: dict[str, Easing]`; `get_easing(name) -> Easing`; `move_duration(distance: float, speed: float, lo=0.35, hi=2.0) -> float`; `scroll_duration(pixels: int, lo=0.5, hi=4.0, px_per_s=900.0) -> float`; `bezier_path(start: Point, end: Point, n_ticks: int, easing: Easing, index: int, curvature=0.15) -> list[Point]` (exactly `n_ticks` points, last == `end`); `Ticker(hz=120, clock=time.perf_counter, sleep=time.sleep)` with `.hz`, `.now() -> float`, `.n_ticks(duration) -> int`, `.ticks(duration) -> Iterator[tuple[int, float]]` yielding `(i, t_norm)` for `i = 1..n` at deadlines `start + i/hz` (late ticks don't sleep), `.sleep_until(deadline)`, `.wait(seconds)`.

- [ ] **Step 1: Write failing tests**

`tests/test_easing.py`:
```python
import pytest

from capturekarma.motion.easing import EASINGS, get_easing
from capturekarma.scene.model import EASING_NAMES


def test_all_scene_easing_names_exist():
    assert set(EASING_NAMES) == set(EASINGS)


@pytest.mark.parametrize("name", EASING_NAMES)
def test_easing_endpoints_and_monotonic(name):
    f = get_easing(name)
    assert f(0.0) == pytest.approx(0.0) and f(1.0) == pytest.approx(1.0)
    xs = [i / 200 for i in range(201)]
    ys = [f(x) for x in xs]
    assert all(b >= a - 1e-12 for a, b in zip(ys, ys[1:]))


def test_unknown_easing():
    with pytest.raises(ValueError, match="bouncy"):
        get_easing("bouncy")
```

`tests/test_path.py`:
```python
import pytest

from capturekarma.motion.easing import get_easing
from capturekarma.motion.path import bezier_path, move_duration, scroll_duration


def test_move_duration_clamps():
    assert move_duration(0, 1400) == 0.35
    assert move_duration(1400, 1400) == pytest.approx(1.0)
    assert move_duration(100000, 1400) == 2.0


def test_scroll_duration_clamps():
    assert scroll_duration(0) == 0.5
    assert scroll_duration(900) == pytest.approx(1.0)
    assert scroll_duration(-900) == pytest.approx(1.0)
    assert scroll_duration(100000) == 4.0


def test_bezier_path_shape():
    e = get_easing("ease_in_out_cubic")
    pts = bezier_path((0, 0), (600, 0), 120, e, index=0)
    assert len(pts) == 120
    assert pts[-1] == (600, 0)
    assert all(isinstance(p[0], int) and isinstance(p[1], int) for p in pts)
    # arcs off the chord: some points have non-zero y, and they bulge to one side only
    ys = [p[1] for p in pts]
    assert max(abs(y) for y in ys) > 5
    assert (min(ys) >= 0) or (max(ys) <= 0)


def test_bezier_alternates_side_by_index():
    e = get_easing("linear")
    a = bezier_path((0, 0), (600, 0), 60, e, index=0)
    b = bezier_path((0, 0), (600, 0), 60, e, index=1)
    assert a[30][1] == -b[30][1] != 0


def test_bezier_is_deterministic_and_zero_distance():
    e = get_easing("linear")
    assert bezier_path((10, 10), (500, 300), 50, e, 3) == bezier_path((10, 10), (500, 300), 50, e, 3)
    assert bezier_path((7, 7), (7, 7), 5, e, 0) == [(7, 7)] * 5


def test_bezier_x_progress_follows_easing():
    e = get_easing("ease_in_out_cubic")
    pts = bezier_path((0, 0), (1000, 0), 100, e, index=0)
    # at t=0.5 easing is 0.5 -> x≈500
    assert abs(pts[49][0] - 500) <= 15
    # first quarter moves less than middle quarter (ease-in)
    assert pts[24][0] - pts[0][0] < pts[74][0] - pts[49][0]
```

`tests/test_ticker.py`:
```python
from capturekarma.motion.ticker import Ticker


class FakeClock:
    def __init__(self):
        self.t = 100.0
        self.sleeps: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_ticks_count_and_normalised_time():
    c = FakeClock()
    tk = Ticker(hz=10, clock=c.now, sleep=c.sleep)
    out = list(tk.ticks(1.0))
    assert [i for i, _ in out] == list(range(1, 11))
    assert out[-1][1] == 1.0 and abs(out[4][1] - 0.5) < 1e-9
    assert abs(c.t - 101.0) < 1e-6  # advanced exactly one second


def test_min_one_tick():
    c = FakeClock()
    assert Ticker(hz=10, clock=c.now, sleep=c.sleep).n_ticks(0.0) == 1
    assert len(list(Ticker(hz=10, clock=c.now, sleep=c.sleep).ticks(0.0))) == 1


def test_late_tick_catches_up_without_sleeping():
    c = FakeClock()
    tk = Ticker(hz=10, clock=c.now, sleep=c.sleep)
    gen = tk.ticks(0.5)
    next(gen)          # tick 1 at +0.1
    n_before = len(c.sleeps)
    c.t += 0.35        # simulate a stall past ticks 2,3,4
    next(gen); next(gen); next(gen)
    assert c.sleeps[n_before:] == []   # late ticks never sleep
    i, t = next(gen)   # tick 5 at +0.5; only ~0.05 remains to sleep
    assert i == 5 and t == 1.0
    assert abs(c.t - 100.5) < 1e-6


def test_now_uses_injected_clock():
    c = FakeClock()
    assert Ticker(hz=10, clock=c.now, sleep=c.sleep).now() == 100.0


def test_wait_advances_clock():
    c = FakeClock()
    Ticker(hz=10, clock=c.now, sleep=c.sleep).wait(0.3)
    assert abs(c.t - 100.3) < 1e-6
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_easing.py tests/test_path.py tests/test_ticker.py -q`
Expected: ImportError.

- [ ] **Step 3: Write `capturekarma/motion/easing.py`**

```python
"""Easing functions [0,1] -> [0,1]. Names must match scene.model.EASING_NAMES."""
from __future__ import annotations

from typing import Callable

Easing = Callable[[float], float]


def linear(t: float) -> float:
    return t


def ease_in_out_cubic(t: float) -> float:
    return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in_out_quint(t: float) -> float:
    return 16 * t ** 5 if t < 0.5 else 1 - ((-2 * t + 2) ** 5) / 2


EASINGS: dict[str, Easing] = {
    "linear": linear,
    "ease_in_out_cubic": ease_in_out_cubic,
    "ease_out_cubic": ease_out_cubic,
    "ease_in_out_quint": ease_in_out_quint,
}


def get_easing(name: str) -> Easing:
    try:
        return EASINGS[name]
    except KeyError:
        raise ValueError(f"unknown easing {name!r}; choose from {', '.join(EASINGS)}") from None
```

- [ ] **Step 4: Write `capturekarma/motion/path.py`**

```python
"""Deterministic cursor paths and duration heuristics."""
from __future__ import annotations

import math

from capturekarma.scene.model import Point

from .easing import Easing


def move_duration(distance: float, speed: float, lo: float = 0.35, hi: float = 2.0) -> float:
    """Seconds for a cursor move: distance / speed clamped to [lo, hi]."""
    return max(lo, min(hi, distance / speed))


def scroll_duration(pixels: int, lo: float = 0.5, hi: float = 4.0, px_per_s: float = 900.0) -> float:
    return max(lo, min(hi, abs(pixels) / px_per_s))


def _cubic(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    u = 1 - t
    return u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3


def bezier_path(start: Point, end: Point, n_ticks: int, easing: Easing, index: int,
                curvature: float = 0.15) -> list[Point]:
    """Points along a cubic Bezier from start to end, one per tick.

    The chord is bowed perpendicular by `curvature * chord_length`; the side alternates with
    `index` parity so successive moves look natural but remain fully deterministic.
    Returns exactly n_ticks points; the last equals `end`.
    """
    n = max(1, n_ticks)
    (x0, y0), (x3, y3) = start, end
    dx, dy = x3 - x0, y3 - y0
    length = math.hypot(dx, dy)
    if length == 0:
        return [end] * n
    nx, ny = -dy / length, dx / length
    side = 1.0 if index % 2 == 0 else -1.0
    off = side * curvature * length
    c1 = (x0 + dx / 3 + nx * off, y0 + dy / 3 + ny * off)
    c2 = (x0 + 2 * dx / 3 + nx * off, y0 + 2 * dy / 3 + ny * off)
    pts: list[Point] = []
    for i in range(1, n + 1):
        t = easing(i / n)
        pts.append((round(_cubic(x0, c1[0], c2[0], x3, t)), round(_cubic(y0, c1[1], c2[1], y3, t))))
    pts[-1] = end
    return pts
```

- [ ] **Step 5: Write `capturekarma/motion/ticker.py`**

```python
"""Drift-corrected fixed-rate ticker."""
from __future__ import annotations

import time
from typing import Callable, Iterator


class Ticker:
    def __init__(self, hz: int = 120, clock: Callable[[], float] = time.perf_counter,
                 sleep: Callable[[float], None] = time.sleep, spin_threshold: float = 0.002):
        if hz <= 0:
            raise ValueError("hz must be positive")
        self.hz = hz
        self._clock = clock
        self._sleep = sleep
        self._spin = spin_threshold

    def now(self) -> float:
        """Current time from the injected clock (the player uses this for timeline timestamps)."""
        return self._clock()

    def n_ticks(self, duration: float) -> int:
        return max(1, round(duration * self.hz))

    def sleep_until(self, deadline: float) -> None:
        """Sleep in coarse steps, then spin for the final `spin_threshold` seconds for accuracy."""
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return
            if remaining > self._spin:
                self._sleep(remaining - self._spin)
            else:
                self._sleep(0)
                if self._clock() >= deadline:
                    return

    def ticks(self, duration: float) -> Iterator[tuple[int, float]]:
        """Yield (i, i/n) for i in 1..n at deadlines start + i/hz. Late ticks are not slept for."""
        n = self.n_ticks(duration)
        start = self._clock()
        for i in range(1, n + 1):
            deadline = start + i / self.hz if duration > 0 else start
            self.sleep_until(deadline)
            yield i, i / n

    def wait(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self.sleep_until(self._clock() + seconds)
```

Note on the fake-clock test: `sleep(0)` in the spin branch advances the fake clock by 0 and then `_clock() >= deadline` is only true when remaining hit 0, so with the FakeClock the spin branch performs `sleep(remaining - spin)` then `sleep(0)` loops... To keep the fake deterministic, the spin branch must make progress: change the else-branch to `self._sleep(remaining)` when `remaining <= self._spin` — with a real clock this is a ≤2 ms sleep (fine on Windows under `timeBeginPeriod(1)`), with the fake clock it lands exactly on the deadline. **Use this version:**

```python
    def sleep_until(self, deadline: float) -> None:
        while True:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return
            self._sleep(remaining - self._spin if remaining > self._spin else remaining)
```

With this, `test_late_tick_catches_up_without_sleeping` expects zero sleeps after the stall — `remaining <= 0` returns immediately without calling sleep, so `c.sleeps[1:]` for the three late ticks is empty and `all(...)` on an empty list is True. Good.

- [ ] **Step 6: Write `capturekarma/motion/__init__.py`**

```python
from .easing import EASINGS, Easing, get_easing
from .path import bezier_path, move_duration, scroll_duration
from .ticker import Ticker

__all__ = ["EASINGS", "Easing", "get_easing", "bezier_path", "move_duration", "scroll_duration", "Ticker"]
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_easing.py tests/test_path.py tests/test_ticker.py -q`
Expected: all pass. If `test_bezier_x_progress_follows_easing` is off by more than tolerance, verify `_cubic` and that `t = easing(i / n)` is applied to the Bezier parameter (not to the index).

- [ ] **Step 8: Commit**

```bash
git add capturekarma/motion tests/test_easing.py tests/test_path.py tests/test_ticker.py
git commit -m "feat(motion): easing, deterministic bezier paths, drift-corrected ticker"
```

---

### Task 4: Capture — monitors, ffmpeg discovery/args, ScreenCapture process

**Files:**
- Create: `capturekarma/capture/monitors.py`, `capturekarma/capture/ffmpeg.py`, `capturekarma/capture/recorder.py`, `capturekarma/capture/__init__.py`
- Test: `tests/test_monitors.py`, `tests/test_ffmpeg_args.py`, `tests/test_capture_win32.py`

**Interfaces:**
- Consumes: `Region` from scene model; `IS_WINDOWS`.
- Produces: `Monitor(index: int, region: Region, primary: bool)`; `list_monitors() -> list[Monitor]` (win32; raises `CaptureError` elsewhere); `monitor_for_region(region, monitors) -> Monitor`; `Capabilities(exe, version, ddagrab, nvenc, libx264)`; `find_ffmpeg() -> str | None`; `probe(exe) -> Capabilities`; `even_region(region) -> Region`; `build_capture_args(caps, region, monitor, fps, out_path, use_ddagrab: bool) -> list[str]`; `CaptureError(Exception)`; `ScreenCapture(caps, region, monitor, fps, out_path, use_ddagrab)` with `.start()`, `.wait_ready(timeout=10.0)`, `.stop(timeout=10.0) -> Path`, `.alive`, `.stderr_tail(n=20) -> str`, `.frames: int`; `start_capture(caps, region, monitor, fps, out_path, prefer_ddagrab=True) -> ScreenCapture` (starts and waits ready; falls back to gdigrab with a warning).

- [ ] **Step 1: Write failing tests**

`tests/test_monitors.py`:
```python
import pytest

from capturekarma.capture.monitors import Monitor, monitor_for_region
from capturekarma.capture.recorder import CaptureError
from capturekarma.scene.model import Region

MONS = [Monitor(0, Region(0, 0, 2560, 1440), True), Monitor(1, Region(2560, 0, 1920, 1080), False)]


def test_region_inside_second_monitor():
    assert monitor_for_region(Region(2600, 10, 800, 600), MONS).index == 1


def test_region_spanning_monitors_is_error():
    with pytest.raises(CaptureError, match="single monitor"):
        monitor_for_region(Region(2000, 0, 1000, 500), MONS)


@pytest.mark.win32
def test_list_monitors_real():
    from capturekarma.capture.monitors import list_monitors
    mons = list_monitors()
    assert mons and any(m.primary for m in mons)
    assert all(m.region.width > 0 and m.region.height > 0 for m in mons)
```

`tests/test_ffmpeg_args.py`:
```python
from pathlib import Path

from capturekarma.capture.ffmpeg import Capabilities, build_capture_args, even_region, parse_probe_output
from capturekarma.capture.monitors import Monitor
from capturekarma.scene.model import Region

CAPS_NV = Capabilities(exe="ffmpeg", version="7.1", ddagrab=True, nvenc=True, libx264=True)
CAPS_SW = Capabilities(exe="ffmpeg", version="7.1", ddagrab=True, nvenc=False, libx264=True)
MON = Monitor(1, Region(2560, 0, 1920, 1080), False)
OUT = Path("out.mp4")


def test_even_region_trims_odd():
    assert even_region(Region(1, 1, 101, 51)) == Region(1, 1, 100, 50)
    assert even_region(Region(0, 0, 100, 50)) == Region(0, 0, 100, 50)


def test_ddagrab_nvenc_args():
    args = build_capture_args(CAPS_NV, Region(2660, 100, 800, 600), MON, 60, OUT, use_ddagrab=True)
    assert args[0] == "ffmpeg" and args[-1] == str(OUT)
    joined = " ".join(args)
    assert "-f lavfi -i ddagrab=output_idx=1:offset_x=100:offset_y=100:video_size=800x600:framerate=60:draw_mouse=0" in joined
    assert "-c:v h264_nvenc" in joined and "-movflags +faststart" in joined
    assert "hwdownload" not in joined
    assert "-progress pipe:1" in joined and "-nostats" in joined


def test_ddagrab_libx264_downloads_frames():
    joined = " ".join(build_capture_args(CAPS_SW, Region(2660, 100, 800, 600), MON, 30, OUT, use_ddagrab=True))
    assert "-vf hwdownload,format=bgra" in joined
    assert "-c:v libx264 -preset veryfast -crf 18" in joined and "-pix_fmt yuv420p" in joined


def test_gdigrab_args_use_screen_coords():
    joined = " ".join(build_capture_args(CAPS_SW, Region(2660, 100, 800, 600), MON, 60, OUT, use_ddagrab=False))
    assert "-f gdigrab" in joined and "-offset_x 2660 -offset_y 100" in joined
    assert "-video_size 800x600" in joined and "-draw_mouse 0" in joined and "-i desktop" in joined
    assert "hwdownload" not in joined


def test_parse_probe_output():
    caps = parse_probe_output("ffmpeg",
        version_text="ffmpeg version 7.1-essentials_build Copyright",
        filters_text=" ... ddagrab           |->V ...",
        encoders_text=" V..... libx264 ...\n V....D h264_nvenc ...")
    assert caps == Capabilities("ffmpeg", "7.1-essentials_build", True, True, True)
```

`tests/test_capture_win32.py`:
```python
import json
import subprocess
import time
from pathlib import Path

import pytest

from capturekarma.capture.ffmpeg import find_ffmpeg, probe
from capturekarma.capture.monitors import list_monitors
from capturekarma.capture.recorder import start_capture
from capturekarma.scene.model import Region

pytestmark = pytest.mark.win32


def _ffprobe(exe: str, path: Path) -> dict:
    ffprobe = str(Path(exe).with_name(Path(exe).name.replace("ffmpeg", "ffprobe")))
    cmd = [ffprobe if Path(ffprobe).exists() else "ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=r_frame_rate,width,height:format=duration", "-of", "json", str(path)]
    return json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)


def test_record_one_second(tmp_path: Path):
    exe = find_ffmpeg()
    assert exe, "ffmpeg not found (PATH or imageio-ffmpeg)"
    caps = probe(exe)
    mon = [m for m in list_monitors() if m.primary][0]
    region = Region(mon.region.x + 10, mon.region.y + 10, 640, 360)
    out = tmp_path / "clip.mp4"
    cap = start_capture(caps, region, mon, 60, out)
    time.sleep(1.0)
    result = cap.stop()
    assert result == out and out.exists() and out.stat().st_size > 0
    assert cap.frames >= 30
    info = _ffprobe(exe, out)
    assert info["streams"][0]["width"] == 640 and info["streams"][0]["height"] == 360
    assert info["streams"][0]["r_frame_rate"] == "60/1"
```

`imageio-ffmpeg` does not ship ffprobe; the test uses ffprobe from PATH if the sibling doesn't exist. If neither exists, skip with `pytest.skip("ffprobe unavailable")` inside `_ffprobe` when `FileNotFoundError` is raised.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_monitors.py tests/test_ffmpeg_args.py -q` → ImportError.

- [ ] **Step 3: Write `capturekarma/capture/recorder.py` exception first, then `monitors.py`**

`capturekarma/capture/monitors.py`:
```python
"""Monitor enumeration in physical pixels (requires DPI awareness set first)."""
from __future__ import annotations

from dataclasses import dataclass

from capturekarma._win import IS_WINDOWS
from capturekarma.scene.model import Region


class CaptureError(Exception):
    """Raised for capture setup/runtime failures (monitors, ffmpeg)."""


@dataclass(frozen=True)
class Monitor:
    index: int          # DXGI output index on adapter 0 == EnumDisplayMonitors order (single-GPU assumption)
    region: Region      # physical px, virtual-screen coordinates
    primary: bool


def list_monitors() -> list[Monitor]:
    if not IS_WINDOWS:
        raise CaptureError("monitor enumeration requires Windows")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    MONITORINFOF_PRIMARY = 1

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

    MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                         ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    found: list[Monitor] = []

    def cb(hmon, hdc, lprc, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            found.append(Monitor(len(found), Region(r.left, r.top, r.right - r.left, r.bottom - r.top),
                                 bool(info.dwFlags & MONITORINFOF_PRIMARY)))
        return True

    if not user32.EnumDisplayMonitors(None, None, MonitorEnumProc(cb), 0):
        raise CaptureError("EnumDisplayMonitors failed")
    if not found:
        raise CaptureError("no monitors found")
    return found


def monitor_for_region(region: Region, monitors: list[Monitor]) -> Monitor:
    for m in monitors:
        if m.region.contains(region):
            return m
    desc = "; ".join(f"monitor {m.index}: {m.region}" for m in monitors)
    raise CaptureError(f"capture region {region} must lie within a single monitor ({desc})")
```

Then `capturekarma/capture/recorder.py` re-exports `CaptureError` from monitors (`from .monitors import CaptureError`) so both import paths work.

- [ ] **Step 4: Write `capturekarma/capture/ffmpeg.py`**

```python
"""ffmpeg discovery, capability probing, and capture argument construction."""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from capturekarma.scene.model import Region

from .monitors import Monitor

log = logging.getLogger("capturekarma.capture")


@dataclass(frozen=True)
class Capabilities:
    exe: str
    version: str
    ddagrab: bool
    nvenc: bool
    libx264: bool


def find_ffmpeg() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # noqa: BLE001 - absence of the optional binary is a normal outcome
        log.debug("imageio-ffmpeg unavailable: %s", exc)
        return None


def _run(exe: str, *args: str) -> str:
    p = subprocess.run([exe, "-hide_banner", *args], capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return p.stdout + p.stderr


def parse_probe_output(exe: str, version_text: str, filters_text: str, encoders_text: str) -> Capabilities:
    m = re.search(r"ffmpeg version (\S+)", version_text)
    return Capabilities(
        exe=exe,
        version=m.group(1) if m else "unknown",
        ddagrab=bool(re.search(r"^\s*\S*\s+ddagrab\s", filters_text, re.M)) or " ddagrab " in filters_text,
        nvenc=bool(re.search(r"^\s*V\S*\s+h264_nvenc\s", encoders_text, re.M)),
        libx264=bool(re.search(r"^\s*V\S*\s+libx264\s", encoders_text, re.M)),
    )


def probe(exe: str) -> Capabilities:
    return parse_probe_output(exe, _run(exe, "-version"), _run(exe, "-filters"), _run(exe, "-encoders"))


def even_region(region: Region) -> Region:
    return Region(region.x, region.y, region.width - region.width % 2, region.height - region.height % 2)


def build_capture_args(caps: Capabilities, region: Region, monitor: Monitor, fps: int, out_path: Path,
                       use_ddagrab: bool) -> list[str]:
    r = even_region(region)
    args: list[str] = [caps.exe, "-hide_banner", "-loglevel", "warning", "-nostats", "-progress", "pipe:1", "-y"]
    if use_ddagrab:
        spec = (f"ddagrab=output_idx={monitor.index}:offset_x={r.x - monitor.region.x}"
                f":offset_y={r.y - monitor.region.y}:video_size={r.width}x{r.height}"
                f":framerate={fps}:draw_mouse=0")
        args += ["-f", "lavfi", "-i", spec]
        if caps.nvenc:
            args += ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19", "-rc", "vbr"]
        else:
            args += ["-vf", "hwdownload,format=bgra", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                     "-pix_fmt", "yuv420p"]
    else:
        args += ["-f", "gdigrab", "-framerate", str(fps), "-offset_x", str(r.x), "-offset_y", str(r.y),
                 "-video_size", f"{r.width}x{r.height}", "-draw_mouse", "0", "-i", "desktop"]
        if caps.nvenc:
            args += ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19", "-rc", "vbr", "-pix_fmt", "yuv420p"]
        else:
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"]
    args += ["-r", str(fps), "-movflags", "+faststart", str(out_path)]
    return args
```

- [ ] **Step 5: Write `ScreenCapture` in `capturekarma/capture/recorder.py`**

```python
"""ffmpeg capture process lifecycle."""
from __future__ import annotations

import collections
import logging
import subprocess
import threading
import time
from pathlib import Path

from capturekarma.scene.model import Region

from .ffmpeg import Capabilities, build_capture_args
from .monitors import CaptureError, Monitor  # noqa: F401  (re-export CaptureError)

log = logging.getLogger("capturekarma.capture")


class ScreenCapture:
    def __init__(self, caps: Capabilities, region: Region, monitor: Monitor, fps: int, out_path: Path,
                 use_ddagrab: bool = True):
        self.args = build_capture_args(caps, region, monitor, fps, out_path, use_ddagrab)
        self.out_path = Path(out_path)
        self.use_ddagrab = use_ddagrab
        self.frames = 0
        self._proc: subprocess.Popen[str] | None = None
        self._stderr: collections.deque[str] = collections.deque(maxlen=200)
        self._ready = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stderr_tail(self, n: int = 20) -> str:
        return "\n".join(list(self._stderr)[-n:])

    def start(self) -> None:
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        log.debug("ffmpeg: %s", " ".join(self.args))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(self.args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                      bufsize=1, creationflags=flags)
        self._threads = [threading.Thread(target=self._read_progress, daemon=True),
                         threading.Thread(target=self._read_stderr, daemon=True)]
        for t in self._threads:
            t.start()

    def _read_progress(self) -> None:
        assert self._proc and self._proc.stdout
        for line in self._proc.stdout:
            if line.startswith("frame="):
                try:
                    self.frames = int(line.split("=", 1)[1].strip())
                except ValueError:
                    continue
                if self.frames >= 1:
                    self._ready.set()

    def _read_stderr(self) -> None:
        assert self._proc and self._proc.stderr
        for line in self._proc.stderr:
            self._stderr.append(line.rstrip())

    def wait_ready(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._ready.wait(0.05):
                return
            if not self.alive:
                raise CaptureError(f"ffmpeg exited before producing frames (code {self._proc.returncode}):\n"
                                   f"{self.stderr_tail()}")
        self.stop(timeout=3.0, expect_output=False)
        raise CaptureError(f"ffmpeg produced no frames within {timeout}s:\n{self.stderr_tail()}")

    def stop(self, timeout: float = 10.0, expect_output: bool = True) -> Path:
        if self._proc is None:
            raise CaptureError("capture was never started")
        if self.alive:
            try:
                assert self._proc.stdin
                self._proc.stdin.write("q\n")
                self._proc.stdin.flush()
            except (OSError, ValueError):
                pass  # stdin already closed by ffmpeg; fall through to wait/terminate
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                log.warning("ffmpeg did not exit after 'q'; terminating")
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        for t in self._threads:
            t.join(timeout=2.0)
        if expect_output and (not self.out_path.exists() or self.out_path.stat().st_size == 0):
            raise CaptureError(f"ffmpeg exited (code {self._proc.returncode}) without writing {self.out_path}:\n"
                               f"{self.stderr_tail()}")
        return self.out_path


def start_capture(caps: Capabilities, region: Region, monitor: Monitor, fps: int, out_path: Path,
                  prefer_ddagrab: bool = True) -> ScreenCapture:
    """Start capturing and wait until frames flow. Falls back from ddagrab to gdigrab with a warning."""
    if prefer_ddagrab and caps.ddagrab:
        cap = ScreenCapture(caps, region, monitor, fps, out_path, use_ddagrab=True)
        cap.start()
        try:
            cap.wait_ready()
            return cap
        except CaptureError as exc:
            log.warning("ddagrab capture failed, falling back to gdigrab (slower): %s", exc)
            if out_path.exists():
                out_path.unlink()
    cap = ScreenCapture(caps, region, monitor, fps, out_path, use_ddagrab=False)
    cap.start()
    cap.wait_ready()
    return cap
```

- [ ] **Step 6: Write `capturekarma/capture/__init__.py`**

```python
from .ffmpeg import Capabilities, build_capture_args, even_region, find_ffmpeg, probe
from .monitors import CaptureError, Monitor, list_monitors, monitor_for_region
from .recorder import ScreenCapture, start_capture

__all__ = ["Capabilities", "build_capture_args", "even_region", "find_ffmpeg", "probe", "CaptureError",
           "Monitor", "list_monitors", "monitor_for_region", "ScreenCapture", "start_capture"]
```

- [ ] **Step 7: Run all capture tests (on Windows)**

Run: `uv run pytest tests/test_monitors.py tests/test_ffmpeg_args.py tests/test_capture_win32.py -q`
Expected: all pass. `test_record_one_second` proves ddagrab+NVENC actually works on this machine. If ddagrab fails with a d3d11 error in the NVENC path, check the stderr tail; if nvenc rejects d3d11 frames, add `"-vf", "hwdownload,format=bgra"` also on the nvenc path in `build_capture_args` and update `test_ddagrab_nvenc_args` accordingly (report this in the task summary).

- [ ] **Step 8: Commit**

```bash
git add capturekarma/capture tests/test_monitors.py tests/test_ffmpeg_args.py tests/test_capture_win32.py
git commit -m "feat(capture): monitor enumeration, ffmpeg probing, ddagrab/gdigrab capture process"
```

---

### Task 5: Cursor — sprites and Win32 overlay window

**Files:**
- Create: `capturekarma/cursor/sprites.py`, `capturekarma/cursor/overlay.py`, `capturekarma/cursor/__init__.py`, `capturekarma/cursor/assets/.gitkeep`
- Test: `tests/test_sprites.py`, `tests/test_overlay_win32.py`

**Interfaces:**
- Produces: `FRAME_SIZE = 160`, `HOTSPOT = (80, 80)` (cursor tip position inside the frame), `RIPPLE_DURATION = 0.4`; `Ripple(start: float)`; `load_sprite(style: str) -> PIL.Image.Image` (RGBA; `"default"` generated programmatically; others from `assets/<style>.png`; raises `ValueError` listing available styles); `render_frame(sprite, ripples: list[Ripple], now: float, ripple_enabled: bool) -> PIL.Image.Image` (RGBA `FRAME_SIZE`²); `to_premultiplied_bgra(img) -> bytes`; `CursorOverlay(style="default", ripple=True, visible=True)` with `.start()`, `.set_position(x, y)`, `.set_visible(bool)`, `.click()`, `.stop()`, `.position -> Point`, `.visible -> bool`.

- [ ] **Step 1: Write failing tests**

`tests/test_sprites.py`:
```python
import pytest
from PIL import Image

from capturekarma.cursor.sprites import (
    FRAME_SIZE, HOTSPOT, RIPPLE_DURATION, Ripple, load_sprite, render_frame, to_premultiplied_bgra,
)


def test_default_sprite_is_rgba_and_small():
    s = load_sprite("default")
    assert s.mode == "RGBA" and s.width <= 48 and s.height <= 48
    assert s.getbbox() is not None


def test_unknown_style_lists_available():
    with pytest.raises(ValueError, match="default"):
        load_sprite("nope")


def test_render_frame_places_tip_at_hotspot():
    s = load_sprite("default")
    f = render_frame(s, [], now=0.0, ripple_enabled=True)
    assert f.size == (FRAME_SIZE, FRAME_SIZE) and f.mode == "RGBA"
    # the tip sits within a 3x3 neighbourhood of the hotspot; the far corner is transparent
    hx, hy = HOTSPOT
    assert any(f.getpixel((hx + dx, hy + dy))[3] > 0 for dx in range(3) for dy in range(3))
    assert f.getpixel((hx - 4, hy - 4))[3] == 0   # nothing above/left of the tip
    assert f.getpixel((0, 0))[3] == 0


def test_ripple_grows_and_fades():
    s = load_sprite("default")
    r = [Ripple(start=10.0)]
    early = render_frame(s, r, now=10.05, ripple_enabled=True)
    late = render_frame(s, r, now=10.35, ripple_enabled=True)
    done = render_frame(s, r, now=10.0 + RIPPLE_DURATION + 0.01, ripple_enabled=True)
    off = render_frame(s, r, now=10.05, ripple_enabled=False)

    def alpha_sum(img: Image.Image) -> int:
        return sum(img.getchannel("A").getdata())

    base = alpha_sum(render_frame(s, [], now=0.0, ripple_enabled=True))
    assert alpha_sum(early) > base and alpha_sum(late) > base
    assert alpha_sum(done) == base and alpha_sum(off) == base
    # late ring is wider: some alpha further from the hotspot than in the early frame
    def max_radius(img):
        a = img.getchannel("A").load()
        best = 0
        for y in range(FRAME_SIZE):
            for x in range(FRAME_SIZE):
                if a[x, y] > 0:
                    best = max(best, (x - HOTSPOT[0]) ** 2 + (y - HOTSPOT[1]) ** 2)
        return best
    assert max_radius(late) > max_radius(early)


def test_premultiplied_bgra_layout():
    img = Image.new("RGBA", (2, 1))
    img.putpixel((0, 0), (255, 0, 0, 128))   # red, half alpha
    img.putpixel((1, 0), (0, 0, 255, 255))   # blue, opaque
    b = to_premultiplied_bgra(img)
    assert len(b) == 8
    assert b[0:4] == bytes([0, 0, 128, 128])  # B,G,R,A premultiplied (255*128/255=128)
    assert b[4:8] == bytes([255, 0, 0, 255])
```

`tests/test_overlay_win32.py`:
```python
import time

import pytest
from PIL import ImageGrab

from capturekarma._win import set_dpi_awareness
from capturekarma.cursor.overlay import CursorOverlay
from capturekarma.cursor.sprites import FRAME_SIZE

pytestmark = pytest.mark.win32


def test_overlay_draws_and_hides():
    set_dpi_awareness()
    ov = CursorOverlay(style="default", ripple=True, visible=True)
    ov.start()
    try:
        x, y = 300, 300
        ov.set_position(x, y)
        time.sleep(0.3)
        box = (x - FRAME_SIZE // 2, y - FRAME_SIZE // 2, x + FRAME_SIZE // 2, y + FRAME_SIZE // 2)
        shown = ImageGrab.grab(bbox=box, all_screens=True)
        ov.set_visible(False)
        time.sleep(0.3)
        hidden = ImageGrab.grab(bbox=box, all_screens=True)
        assert list(shown.getdata()) != list(hidden.getdata())
        assert ov.position == (x, y) and ov.visible is False
    finally:
        ov.stop()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_sprites.py -q` → ImportError.

- [ ] **Step 3: Write `capturekarma/cursor/sprites.py`**

```python
"""Cursor sprite loading and frame rendering (pure Pillow/numpy, no Win32)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

FRAME_SIZE = 160
HOTSPOT = (FRAME_SIZE // 2, FRAME_SIZE // 2)
RIPPLE_DURATION = 0.4
RIPPLE_R0, RIPPLE_R1 = 6.0, 48.0
RIPPLE_COLOR = (59, 130, 246)  # blue-500
ASSETS_DIR = Path(__file__).parent / "assets"


@dataclass(frozen=True)
class Ripple:
    start: float  # clock time (seconds) when the click happened


def _draw_default_arrow() -> Image.Image:
    """Classic white arrow with a dark outline, tip at (0, 0), ~32 px tall, rendered 4x then downsampled."""
    s = 4
    img = Image.new("RGBA", (24 * s, 34 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(0, 0), (0, 26), (7, 20), (12, 32), (16, 30), (11, 18), (20, 18)]
    poly = [(x * s + 2 * s, y * s + 2 * s) for x, y in pts]
    d.polygon(poly, fill=(255, 255, 255, 255), outline=(20, 20, 20, 255))
    d.line(poly + [poly[0]], fill=(20, 20, 20, 255), width=2 * s)
    return img.resize((24, 34), Image.LANCZOS)


def available_styles() -> list[str]:
    styles = ["default"]
    if ASSETS_DIR.exists():
        styles += sorted(p.stem for p in ASSETS_DIR.glob("*.png"))
    return styles


def load_sprite(style: str) -> Image.Image:
    """RGBA sprite whose pixel (0, 0) is the cursor tip."""
    if style == "default":
        return _draw_default_arrow()
    p = ASSETS_DIR / f"{style}.png"
    if not p.exists():
        raise ValueError(f"unknown cursor style {style!r}; available: {', '.join(available_styles())}")
    return Image.open(p).convert("RGBA")


def render_frame(sprite: Image.Image, ripples: list[Ripple], now: float, ripple_enabled: bool) -> Image.Image:
    frame = Image.new("RGBA", (FRAME_SIZE, FRAME_SIZE), (0, 0, 0, 0))
    if ripple_enabled:
        d = ImageDraw.Draw(frame)
        for rp in ripples:
            t = (now - rp.start) / RIPPLE_DURATION
            if not 0.0 <= t < 1.0:
                continue
            radius = RIPPLE_R0 + (RIPPLE_R1 - RIPPLE_R0) * math.sqrt(t)
            alpha = int(180 * (1.0 - t))
            width = max(1, int(6 * (1.0 - t)) + 1)
            cx, cy = HOTSPOT
            d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                      outline=(*RIPPLE_COLOR, alpha), width=width)
    frame.alpha_composite(sprite, dest=HOTSPOT)
    return frame


def prune_ripples(ripples: list[Ripple], now: float) -> list[Ripple]:
    return [r for r in ripples if now - r.start < RIPPLE_DURATION]


def to_premultiplied_bgra(img: Image.Image) -> bytes:
    """Top-down premultiplied BGRA bytes as required by UpdateLayeredWindow with AC_SRC_ALPHA."""
    a = np.asarray(img.convert("RGBA"), dtype=np.uint16)
    alpha = a[..., 3:4]
    rgb = (a[..., :3] * alpha + 127) // 255
    bgra = np.concatenate([rgb[..., 2:3], rgb[..., 1:2], rgb[..., 0:1], alpha], axis=-1).astype(np.uint8)
    return bgra.tobytes()
```

- [ ] **Step 4: Run sprite tests**

Run: `uv run pytest tests/test_sprites.py -q` → pass. (The arrow is drawn with a 2 px inset so the outline isn't clipped; the test tolerates the tip landing anywhere in the 3×3 block at the hotspot.)

- [ ] **Step 5: Write `capturekarma/cursor/overlay.py`**

```python
"""Transparent, click-through, always-on-top cursor overlay window (Win32, own thread)."""
from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Literal

from capturekarma._win import IS_WINDOWS
from capturekarma.scene.model import Point

from .sprites import FRAME_SIZE, HOTSPOT, Ripple, load_sprite, prune_ripples, render_frame, to_premultiplied_bgra

log = logging.getLogger("capturekarma.cursor")

_Cmd = tuple[Literal["pos", "vis", "click", "stop"], object]


class CursorOverlay:
    def __init__(self, style: str = "default", ripple: bool = True, visible: bool = True):
        self._sprite = load_sprite(style)
        self._ripple_enabled = ripple
        self._visible = visible
        self._pos: Point = (0, 0)
        self._q: queue.Queue[_Cmd] = queue.Queue()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None

    # ---- public API (any thread) ----
    @property
    def position(self) -> Point:
        return self._pos

    @property
    def visible(self) -> bool:
        return self._visible

    def start(self) -> None:
        if not IS_WINDOWS:
            raise RuntimeError("CursorOverlay requires Windows")
        self._thread = threading.Thread(target=self._run, name="cursor-overlay", daemon=True)
        self._thread.start()
        if not self._ready.wait(5.0):
            raise RuntimeError("cursor overlay did not start")
        if self._error:
            raise RuntimeError(f"cursor overlay failed to start: {self._error!r}")

    def set_position(self, x: int, y: int) -> None:
        self._pos = (int(x), int(y))
        self._q.put(("pos", self._pos))

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self._q.put(("vis", self._visible))

    def click(self) -> None:
        self._q.put(("click", None))

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._q.put(("stop", None))
            self._thread.join(timeout=3.0)

    # ---- window thread ----
    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        WS_POPUP = 0x80000000
        WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x80000, 0x20, 0x8, 0x80
        WS_EX_NOACTIVATE = 0x08000000
        SW_SHOWNOACTIVATE, SW_HIDE = 4, 0
        ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 2, 0, 1
        PM_REMOVE = 1
        SWP_NOSIZE, SWP_NOACTIVATE, SWP_NOZORDER = 0x1, 0x10, 0x4
        HWND_TOPMOST = -1

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                        ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        def wndproc(hwnd, msg, wparam, lparam):
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        hwnd = None
        hdc_mem = None
        hbmp = None
        try:
            user32.SetProcessDPIAware  # noqa: B018 - presence check only; awareness set by caller
            proc = WNDPROC(wndproc)
            cls = WNDCLASSW()
            cls.lpfnWndProc = proc
            cls.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
            cls.lpszClassName = f"CaptureKarmaCursor{id(self)}"
            if not user32.RegisterClassW(ctypes.byref(cls)):
                raise ctypes.WinError()
            ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            hwnd = user32.CreateWindowExW(ex, cls.lpszClassName, "CaptureKarma Cursor", WS_POPUP,
                                          0, 0, FRAME_SIZE, FRAME_SIZE, None, None, cls.hInstance, None)
            if not hwnd:
                raise ctypes.WinError()

            # 32-bpp top-down DIB section reused for every frame
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = FRAME_SIZE
            bmi.bmiHeader.biHeight = -FRAME_SIZE
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bits = ctypes.c_void_p()
            hdc_screen = user32.GetDC(None)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbmp = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            user32.ReleaseDC(None, hdc_screen)
            if not hbmp:
                raise ctypes.WinError()
            gdi32.SelectObject(hdc_mem, hbmp)
            nbytes = FRAME_SIZE * FRAME_SIZE * 4

            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            size = wintypes.SIZE(FRAME_SIZE, FRAME_SIZE)
            pt_src = wintypes.POINT(0, 0)
            ripples: list[Ripple] = []
            visible = self._visible
            pos = self._pos

            def paint(now: float) -> None:
                frame = render_frame(self._sprite, ripples, now, self._ripple_enabled)
                ctypes.memmove(bits, to_premultiplied_bgra(frame), nbytes)
                dst = wintypes.POINT(pos[0] - HOTSPOT[0], pos[1] - HOTSPOT[1])
                if not user32.UpdateLayeredWindow(hwnd, None, ctypes.byref(dst), ctypes.byref(size), hdc_mem,
                                                  ctypes.byref(pt_src), 0, ctypes.byref(blend), ULW_ALPHA):
                    raise ctypes.WinError()

            paint(time.perf_counter())
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)
            self._ready.set()

            msg = wintypes.MSG()
            running = True
            while running:
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                dirty = False
                try:
                    while True:
                        kind, val = self._q.get_nowait()
                        if kind == "pos":
                            pos = val  # type: ignore[assignment]
                            dirty = True
                        elif kind == "vis":
                            visible = bool(val)
                            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)
                            dirty = True
                        elif kind == "click":
                            ripples.append(Ripple(time.perf_counter()))
                            dirty = True
                        elif kind == "stop":
                            running = False
                except queue.Empty:
                    pass
                now = time.perf_counter()
                if ripples:
                    ripples = prune_ripples(ripples, now)
                    dirty = True
                if dirty and running:
                    paint(now)
                    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER)
                time.sleep(1 / 240)
        except BaseException as exc:  # noqa: BLE001 - surfaced to start() / logged
            self._error = exc
            log.error("cursor overlay thread failed: %r", exc)
            self._ready.set()
        finally:
            if hwnd:
                user32.DestroyWindow(hwnd)
            if hbmp:
                gdi32.DeleteObject(hbmp)
            if hdc_mem:
                gdi32.DeleteDC(hdc_mem)
```

Notes for the implementer: `SetWindowPos(... SWP_NOZORDER)` with `HWND_TOPMOST` is intentionally a no-op on Z-order; it only exists so DWM re-commits the layered surface promptly; if flicker or lag is observed, remove that call. `UpdateLayeredWindow` moves the window (via `dst`) and updates its bitmap in one call, which is what keeps cursor and ripple in sync.

- [ ] **Step 6: Write `capturekarma/cursor/__init__.py`** and `capturekarma/cursor/assets/.gitkeep` (empty)

```python
from .overlay import CursorOverlay
from .sprites import FRAME_SIZE, HOTSPOT, RIPPLE_DURATION, Ripple, available_styles, load_sprite, render_frame

__all__ = ["CursorOverlay", "FRAME_SIZE", "HOTSPOT", "RIPPLE_DURATION", "Ripple", "available_styles",
           "load_sprite", "render_frame"]
```

- [ ] **Step 7: Run overlay test on Windows**

Run: `uv run pytest tests/test_sprites.py tests/test_overlay_win32.py -q` → pass. Also eyeball it: `uv run python -c "import time; from capturekarma._win import set_dpi_awareness; set_dpi_awareness(); from capturekarma.cursor import CursorOverlay; o=CursorOverlay(); o.start(); [ (o.set_position(400+i*3, 400+i), time.sleep(0.01)) for i in range(200)]; o.click(); time.sleep(0.6); o.stop()"` — you should see an arrow glide across the screen and a blue ring pulse.

- [ ] **Step 8: Commit**

```bash
git add capturekarma/cursor tests/test_sprites.py tests/test_overlay_win32.py
git commit -m "feat(cursor): sprite rendering with click ripple and Win32 layered overlay window"
```

---

### Task 6: Drivers — base protocol, Win32 input, DesktopDriver

**Files:**
- Create: `capturekarma/drivers/base.py`, `capturekarma/drivers/win_input.py`, `capturekarma/drivers/desktop.py`, `capturekarma/drivers/__init__.py`
- Test: `tests/test_win_input.py`, `tests/test_desktop_driver.py`

**Interfaces:**
- Consumes: `Scene`, `Region`, `Point`, `StepTarget`, `ScrollStep`; `Easing`; `Ticker`.
- Produces: `DriverError(Exception)`; `WindowNotFound(DriverError)`; `StepError(Exception)` with `.step_index: int | None`, `.screenshot: Path | None`; `Driver` Protocol (methods: `setup(scene) -> Region`, `resolve(target) -> Point`, `pointer_to(x, y)`, `mouse_down(button="left")`, `mouse_up(button="left")`, `smooth_scroll(step: ScrollStep, duration: float, easing: Easing)`, `type_text(text, delay)`, `press(key)`, `screenshot(path)`, `teardown()`); `win_input` functions: `set_cursor_pos(x, y)`, `mouse_button(button, down: bool)`, `wheel(delta: int)`, `type_text(text, delay, sleep=time.sleep)`, `press_key(name)`, `KEY_NAMES: dict[str, int]`, `parse_key(name) -> tuple[list[int], int]` (modifier VKs, main VK), `list_window_titles() -> list[str]`, `find_window(substring) -> tuple[int, str]`, `window_client_region(hwnd) -> Region`, `focus_window(hwnd)`; `DesktopDriver(ticker: Ticker | None = None, input_module=win_input)`.

- [ ] **Step 1: Write failing tests**

`tests/test_win_input.py`:
```python
import pytest

from capturekarma.drivers.win_input import KEY_NAMES, parse_key, wheel_steps


def test_parse_simple_and_combo_keys():
    assert parse_key("Enter") == ([], KEY_NAMES["Enter"])
    mods, vk = parse_key("Ctrl+Shift+a")
    assert mods == [KEY_NAMES["Control"], KEY_NAMES["Shift"]] and vk == ord("A")
    assert parse_key("F5")[1] == KEY_NAMES["F5"]


def test_parse_unknown_key():
    with pytest.raises(ValueError, match="Hyper"):
        parse_key("Hyper")


def test_wheel_steps_quantize_with_carry():
    # 250 px down over 4 ticks with linear easing -> deltas sum to exactly -250
    deltas = list(wheel_steps(total_px=250, n_ticks=4, easing=lambda t: t))
    assert len(deltas) == 4 and sum(deltas) == -250
    up = list(wheel_steps(total_px=-100, n_ticks=3, easing=lambda t: t))
    assert sum(up) == 100
```

`tests/test_desktop_driver.py`:
```python
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
    assert len(deltas) == 10 and sum(deltas) == -300


def test_click_type_press_forward_to_input():
    d, fi = _driver()
    d.setup(Scene(name="n", target=Target(kind="desktop", window="notepad"), steps=()))
    d.pointer_to(5, 6); d.mouse_down(); d.mouse_up(); d.type_text("hi", 0.01); d.press("Enter")
    assert ("pos", 5, 6) in fi.calls and ("btn", "left", True) in fi.calls and ("btn", "left", False) in fi.calls
    assert ("type", "hi", 0.01) in fi.calls and ("press", "Enter") in fi.calls
```

- [ ] **Step 2: Run to verify failure** → ImportError.

- [ ] **Step 3: Write `capturekarma/drivers/base.py`**

```python
"""Driver protocol and driver-level exceptions."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from capturekarma.motion.easing import Easing
from capturekarma.scene.model import Point, Region, Scene, ScrollStep, StepTarget


class DriverError(Exception):
    """Setup/teardown failures (browser didn't launch, window missing, ...)."""


class WindowNotFound(DriverError):
    pass


class StepError(Exception):
    """A step could not be executed. The player fills in step_index and screenshot."""

    def __init__(self, message: str, step_index: int | None = None, screenshot: Path | None = None):
        super().__init__(message)
        self.message = message
        self.step_index = step_index
        self.screenshot = screenshot

    def __str__(self) -> str:
        prefix = f"step {self.step_index + 1}: " if self.step_index is not None else ""
        suffix = f" (screenshot: {self.screenshot})" if self.screenshot else ""
        return prefix + self.message + suffix


class Driver(Protocol):
    def setup(self, scene: Scene) -> Region: ...
    def resolve(self, target: StepTarget) -> Point: ...
    def pointer_to(self, x: int, y: int) -> None: ...
    def mouse_down(self, button: str = "left") -> None: ...
    def mouse_up(self, button: str = "left") -> None: ...
    def smooth_scroll(self, step: ScrollStep, duration: float, easing: Easing) -> None: ...
    def type_text(self, text: str, delay: float) -> None: ...
    def press(self, key: str) -> None: ...
    def screenshot(self, path: Path) -> None: ...
    def teardown(self) -> None: ...
```

- [ ] **Step 4: Write `capturekarma/drivers/win_input.py`**

```python
"""Win32 input and window helpers via ctypes. Pure helpers (parse_key, wheel_steps) work anywhere."""
from __future__ import annotations

import time
from typing import Callable, Iterator

from capturekarma._win import IS_WINDOWS
from capturekarma.scene.model import Region

from .base import WindowNotFound

KEY_NAMES: dict[str, int] = {
    "Backspace": 0x08, "Tab": 0x09, "Enter": 0x0D, "Shift": 0x10, "Control": 0x11, "Alt": 0x12,
    "Escape": 0x1B, "Space": 0x20, "PageUp": 0x21, "PageDown": 0x22, "End": 0x23, "Home": 0x24,
    "ArrowLeft": 0x25, "ArrowUp": 0x26, "ArrowRight": 0x27, "ArrowDown": 0x28, "Delete": 0x2E,
    "Meta": 0x5B,
    **{f"F{i}": 0x6F + i for i in range(1, 13)},
}
_ALIASES = {"Ctrl": "Control", "Esc": "Escape", "Return": "Enter", "Win": "Meta", "Cmd": "Meta", "Del": "Delete",
            "Left": "ArrowLeft", "Right": "ArrowRight", "Up": "ArrowUp", "Down": "ArrowDown"}
_MODIFIERS = ("Control", "Shift", "Alt", "Meta")
WHEEL_DELTA = 120
PX_PER_NOTCH = 100  # approximate pixels one wheel notch scrolls in typical Windows apps


def parse_key(name: str) -> tuple[list[int], int]:
    """'Ctrl+Shift+a' -> ([VK_CONTROL, VK_SHIFT], VK 'A'). Single characters map to their VK via ord(upper)."""
    parts = [p.strip() for p in name.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"empty key name {name!r}")
    *mods, main = parts
    mod_vks: list[int] = []
    for m in mods:
        canon = _ALIASES.get(m, m)
        if canon not in _MODIFIERS:
            raise ValueError(f"unknown modifier {m!r} in {name!r}")
        mod_vks.append(KEY_NAMES[canon])
    main = _ALIASES.get(main, main)
    if main in KEY_NAMES:
        return mod_vks, KEY_NAMES[main]
    if len(main) == 1 and main.isascii() and main.isalnum():
        return mod_vks, ord(main.upper())
    raise ValueError(f"unknown key {main!r} in {name!r}")


def wheel_steps(total_px: int, n_ticks: int, easing: Callable[[float], float]) -> Iterator[int]:
    """Per-tick wheel deltas (Windows sign: positive = up) whose sum is exactly -total_px."""
    emitted = 0
    for i in range(1, n_ticks + 1):
        target = round(-total_px * easing(i / n_ticks))
        yield target - emitted
        emitted = target


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
    MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
    MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
    MOUSEEVENTF_WHEEL = 0x0800
    KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
    _BUTTON_FLAGS = {"left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
                     "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
                     "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP)}

    def _send(*inputs: INPUT) -> None:
        arr = (INPUT * len(inputs))(*inputs)
        sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise ctypes.WinError()

    def _mouse(flags: int, data: int = 0) -> INPUT:
        inp = INPUT(type=INPUT_MOUSE)
        inp.u.mi = MOUSEINPUT(0, 0, ctypes.c_uint32(data & 0xFFFFFFFF).value, flags, 0, 0)
        return inp

    def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        return inp

    def set_cursor_pos(x: int, y: int) -> None:
        if not user32.SetCursorPos(int(x), int(y)):
            raise ctypes.WinError()

    def mouse_button(button: str, down: bool) -> None:
        d, u = _BUTTON_FLAGS[button]
        _send(_mouse(d if down else u))

    def wheel(delta: int) -> None:
        if delta:
            _send(_mouse(MOUSEEVENTF_WHEEL, delta))

    def type_text(text: str, delay: float, sleep: Callable[[float], None] = time.sleep) -> None:
        for ch in text:
            code = ord(ch)
            if code > 0xFFFF:  # surrogate pair for astral characters
                code -= 0x10000
                units = [0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)]
            else:
                units = [code]
            for u in units:
                _send(_key(0, u, KEYEVENTF_UNICODE), _key(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            if delay > 0:
                sleep(delay)

    def press_key(name: str) -> None:
        mods, vk = parse_key(name)
        downs = [_key(m) for m in mods] + [_key(vk)]
        ups = [_key(vk, 0, KEYEVENTF_KEYUP)] + [_key(m, 0, KEYEVENTF_KEYUP) for m in reversed(mods)]
        _send(*downs, *ups)

    def list_window_titles() -> list[str]:
        titles: list[str] = []
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    titles.append(buf.value)
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        return titles

    def find_window(substring: str) -> tuple[int, str]:
        matches: list[tuple[int, str]] = []
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    if substring.lower() in buf.value.lower():
                        matches.append((hwnd, buf.value))
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        if not matches:
            visible = "\n  ".join(list_window_titles())
            raise WindowNotFound(f"no visible window title contains {substring!r}. Visible windows:\n  {visible}")
        return matches[0]

    def window_client_region(hwnd: int) -> Region:
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError()
        pt = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            raise ctypes.WinError()
        return Region(pt.x, pt.y, rect.right - rect.left, rect.bottom - rect.top)

    def focus_window(hwnd: int) -> None:
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        # Windows refuses SetForegroundWindow unless our process recently received input;
        # a synthetic ALT tap satisfies that rule.
        _send(_key(KEY_NAMES["Alt"]), _key(KEY_NAMES["Alt"], 0, KEYEVENTF_KEYUP))
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.15)
```

- [ ] **Step 5: Write `capturekarma/drivers/desktop.py`**

```python
"""Desktop driver: real OS cursor + SendInput. Scrolling is best-effort wheel emulation."""
from __future__ import annotations

import logging
from pathlib import Path
from types import ModuleType
from typing import Any

from capturekarma.motion.easing import Easing
from capturekarma.motion.ticker import Ticker
from capturekarma.scene.model import Point, Region, Scene, ScrollStep, StepTarget

from . import win_input
from .base import DriverError, StepError

log = logging.getLogger("capturekarma.drivers.desktop")


class DesktopDriver:
    def __init__(self, ticker: Ticker | None = None, input_module: ModuleType | Any = win_input):
        self._ticker = ticker or Ticker()
        self._in = input_module
        self._region: Region | None = None

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

    def mouse_up(self, button: str = "left") -> None:
        self._in.mouse_button(button, False)

    def smooth_scroll(self, step: ScrollStep, duration: float, easing: Easing) -> None:
        if step.by is None:
            raise StepError("desktop scroll needs 'by'")
        n = self._ticker.n_ticks(duration)
        deltas = list(win_input.wheel_steps(step.by, n, easing))
        for (i, _), delta in zip(self._ticker.ticks(duration), deltas):
            self._in.wheel(delta)

    def type_text(self, text: str, delay: float) -> None:
        self._in.type_text(text, delay)

    def press(self, key: str) -> None:
        self._in.press_key(key)

    def screenshot(self, path: Path) -> None:
        from PIL import ImageGrab
        r = self._r()
        ImageGrab.grab(bbox=(r.x, r.y, r.right, r.bottom), all_screens=True).save(path)

    def teardown(self) -> None:
        self._region = None
```

- [ ] **Step 6: Write `capturekarma/drivers/__init__.py`**

```python
from .base import Driver, DriverError, StepError, WindowNotFound
from .desktop import DesktopDriver

__all__ = ["Driver", "DriverError", "StepError", "WindowNotFound", "DesktopDriver"]
```
(`WebDriver` is added to this file in Task 7.)

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_win_input.py tests/test_desktop_driver.py -q` → pass.

- [ ] **Step 8: Commit**

```bash
git add capturekarma/drivers tests/test_win_input.py tests/test_desktop_driver.py
git commit -m "feat(drivers): driver protocol, Win32 SendInput helpers, DesktopDriver"
```

---

### Task 7: WebDriver (Playwright) with in-page smooth scroll

**Files:**
- Create: `capturekarma/drivers/web.py`, `capturekarma/drivers/web_scroll.js`
- Modify: `capturekarma/drivers/__init__.py` (export `WebDriver`)
- Test: `tests/test_web_driver.py` (marked `integration`)

**Interfaces:**
- Consumes: `Driver` protocol, `StepError`, `DriverError`, scene model.
- Produces: `WebDriver(headless: bool = False, window_pos: Point = (0, 0))` implementing `Driver`; attributes `page` (Playwright `Page`), `metrics: ViewportMetrics` (`origin_x, origin_y` physical px of viewport top-left, `dpr: float`, `css_w, css_h`); methods `to_css(x, y) -> tuple[float, float]`, `to_screen(cx, cy) -> Point`; `web_scroll.js` defines `window.__ckSmoothScroll(containerSelector|null, by|null, to|null, durationMs, easingName) -> Promise<number>` returning the final scroll offset.

- [ ] **Step 1: Ensure Chromium is installed**

Run: `uv run playwright install chromium`

- [ ] **Step 2: Write failing test `tests/test_web_driver.py`**

```python
import pytest

from capturekarma.drivers.base import StepError
from capturekarma.drivers.web import WebDriver
from capturekarma.motion.easing import get_easing
from capturekarma.scene.model import Scene, ScrollStep, StepTarget, Target

pytestmark = pytest.mark.integration


@pytest.fixture
def driver(fixture_url):
    d = WebDriver(headless=True)
    d.setup(Scene(name="t", target=Target(kind="web", url=fixture_url, viewport=(1000, 600)), steps=()))
    yield d
    d.teardown()


def test_setup_region_matches_viewport_times_dpr(driver):
    m = driver.metrics
    assert (m.css_w, m.css_h) == (1000, 600)
    r = driver.region
    assert r.width == round(1000 * m.dpr) and r.height == round(600 * m.dpr)


def test_resolve_selector_center_inside_region(driver):
    x, y = driver.resolve(StepTarget(selector="#btn-primary"))
    r = driver.region
    assert r.x <= x < r.right and r.y <= y < r.bottom
    box = driver.page.locator("#btn-primary").bounding_box()
    cx, cy = driver.to_css(x, y)
    assert abs(cx - (box["x"] + box["width"] / 2)) <= 1 and abs(cy - (box["y"] + box["height"] / 2)) <= 1


def test_resolve_at_and_roundtrip(driver):
    p = driver.resolve(StepTarget(at=(100, 50)))
    assert tuple(round(v) for v in driver.to_css(*p)) == (100, 50)


def test_resolve_offscreen_raises(driver):
    with pytest.raises(StepError, match="off-screen"):
        driver.resolve(StepTarget(selector="#deep"))


def test_resolve_missing_raises(driver):
    with pytest.raises(StepError, match="#nope"):
        driver.resolve(StepTarget(selector="#nope"))


def test_smooth_scroll_by_and_to(driver):
    e = get_easing("ease_in_out_cubic")
    driver.smooth_scroll(ScrollStep(by=500), duration=0.3, easing=e)
    assert driver.page.evaluate("window.scrollY") == 500
    driver.smooth_scroll(ScrollStep(to=100), duration=0.3, easing=e)
    assert driver.page.evaluate("window.scrollY") == 100
    driver.smooth_scroll(ScrollStep(by=400, container="#box"), duration=0.3, easing=e)
    assert driver.page.evaluate("document.querySelector('#box').scrollTop") == 400


def test_scroll_makes_deep_button_resolvable(driver):
    driver.smooth_scroll(ScrollStep(to=2800), duration=0.2, easing=get_easing("linear"))
    driver.resolve(StepTarget(selector="#deep"))  # no raise


def test_click_and_type(driver):
    x, y = driver.resolve(StepTarget(selector="#email"))
    driver.pointer_to(x, y); driver.mouse_down(); driver.mouse_up()
    driver.type_text("hi@x.io", 0.0)
    assert driver.page.evaluate("document.querySelector('#email').value") == "hi@x.io"
    driver.press("Control+a"); driver.press("Backspace")
    assert driver.page.evaluate("document.querySelector('#email').value") == ""


def test_screenshot(driver, tmp_path):
    driver.screenshot(tmp_path / "s.png")
    assert (tmp_path / "s.png").stat().st_size > 0
```

- [ ] **Step 3: Run to verify failure** → ImportError.

- [ ] **Step 4: Write `capturekarma/drivers/web_scroll.js`**

```javascript
// Installed via add_init_script. Animates scroll deterministically with requestAnimationFrame.
(() => {
  const EASE = {
    linear: t => t,
    ease_in_out_cubic: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
    ease_out_cubic: t => 1 - Math.pow(1 - t, 3),
    ease_in_out_quint: t => (t < 0.5 ? 16 * Math.pow(t, 5) : 1 - Math.pow(-2 * t + 2, 5) / 2),
  };
  window.__ckSmoothScroll = function (containerSelector, by, to, durationMs, easingName) {
    const ease = EASE[easingName] || EASE.ease_in_out_cubic;
    const el = containerSelector ? document.querySelector(containerSelector) : null;
    if (containerSelector && !el) return Promise.reject(new Error("scroll container not found: " + containerSelector));
    const target = el || document.scrollingElement || document.documentElement;
    const start = target.scrollTop;
    const max = target.scrollHeight - target.clientHeight;
    const goal = Math.max(0, Math.min(max, to !== null && to !== undefined ? to : start + by));
    if (goal === start || durationMs <= 0) { target.scrollTop = goal; return Promise.resolve(target.scrollTop); }
    return new Promise(resolve => {
      let t0 = null;
      const step = now => {
        if (t0 === null) t0 = now;
        const p = Math.min(1, (now - t0) / durationMs);
        target.scrollTop = start + (goal - start) * ease(p);
        if (p < 1) requestAnimationFrame(step);
        else { target.scrollTop = goal; resolve(target.scrollTop); }
      };
      requestAnimationFrame(step);
    });
  };
})();
```

- [ ] **Step 5: Write `capturekarma/drivers/web.py`**

```python
"""Web driver: Playwright Chromium, virtual mouse, in-page eased scrolling."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from capturekarma.motion.easing import EASINGS, Easing
from capturekarma.scene.model import Point, Region, Scene, ScrollStep, StepTarget

from .base import DriverError, StepError

log = logging.getLogger("capturekarma.drivers.web")
SCROLL_JS = (Path(__file__).parent / "web_scroll.js").read_text(encoding="utf-8")
_METRICS_JS = """() => ({
  sx: window.screenX, sy: window.screenY,
  ow: window.outerWidth, oh: window.outerHeight,
  iw: window.innerWidth, ih: window.innerHeight,
  dpr: window.devicePixelRatio,
})"""


@dataclass(frozen=True)
class ViewportMetrics:
    origin_x: int   # physical px of viewport top-left on screen
    origin_y: int
    dpr: float
    css_w: int
    css_h: int


class WebDriver:
    def __init__(self, headless: bool = False, window_pos: Point = (0, 0)):
        self._headless = headless
        self._window_pos = window_pos
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
                self._fit_window_to_viewport(w, h)
            self.page.goto(t.url, wait_until="load")
            self._measure()
        except PWError as exc:
            self.teardown()
            raise DriverError(f"could not launch browser or open {t.url}: {exc}") from exc
        assert self.region is not None
        return self.region

    def _fit_window_to_viewport(self, w: int, h: int) -> None:
        """Resize the OS window so the page's inner size equals the requested viewport exactly."""
        assert self.page is not None
        self.page.goto("about:blank")
        m = self.page.evaluate(_METRICS_JS)
        dw, dh = m["ow"] - m["iw"], m["oh"] - m["ih"]
        cdp = self._context.new_cdp_session(self.page)
        wid = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {
            "left": self._window_pos[0], "top": self._window_pos[1], "width": w + dw, "height": h + dh,
            "windowState": "normal"}})
        cdp.detach()
        self.page.wait_for_timeout(100)

    def _measure(self) -> None:
        assert self.page is not None
        m = self.page.evaluate(_METRICS_JS)
        dpr = float(m["dpr"])
        side = max(0.0, (m["ow"] - m["iw"]) / 2)   # headless reports outer == 0; clamp
        top = max(0.0, m["oh"] - m["ih"])
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
            loc = self.page.locator(target.selector).first
            box = loc.bounding_box() if loc.count() else None
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

    def type_text(self, text: str, delay: float) -> None:
        assert self.page is not None
        self.page.keyboard.type(text, delay=delay * 1000)

    def press(self, key: str) -> None:
        assert self.page is not None
        self.page.keyboard.press(key)

    def screenshot(self, path: Path) -> None:
        assert self.page is not None
        self.page.screenshot(path=str(path))
```

- [ ] **Step 6: Export in `capturekarma/drivers/__init__.py`**

```python
from .base import Driver, DriverError, StepError, WindowNotFound
from .desktop import DesktopDriver
from .web import WebDriver

__all__ = ["Driver", "DriverError", "StepError", "WindowNotFound", "DesktopDriver", "WebDriver"]
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_web_driver.py -q` → pass. Then a **headed sanity check** on Windows: `uv run python -c "from capturekarma._win import set_dpi_awareness; set_dpi_awareness(); from capturekarma.drivers.web import WebDriver; from capturekarma.scene.model import *; d=WebDriver(); print(d.setup(Scene('x', Target('web', url='https://example.com', viewport=(1280,720)), ()))); print(d.metrics); input('enter to close'); d.teardown()"` — the printed region's width/height must equal 1280×720 × your display scale, and the region must start below the browser's tab strip. Verify the top-left of `region` visually by moving the mouse there and reading its position (`uv run python -c "import ctypes; from ctypes import wintypes; p=wintypes.POINT(); ctypes.windll.user32.GetCursorPos(ctypes.byref(p)); print(p.x,p.y)"`). Report any offset in the task summary.

- [ ] **Step 8: Commit**

```bash
git add capturekarma/drivers tests/test_web_driver.py
git commit -m "feat(drivers): Playwright WebDriver with viewport mapping and in-page eased scrolling"
```

---

### Task 8: Recorder — RawEvent, smoothing pass, stop hotkey

**Files:**
- Create: `capturekarma/recorder/events.py`, `capturekarma/recorder/smooth.py`, `capturekarma/recorder/hotkey.py`, `capturekarma/recorder/__init__.py`
- Test: `tests/test_smooth.py`

**Interfaces:**
- Consumes: scene step dataclasses, `StepTarget`, `Point`.
- Produces: `RawEvent(t: float, kind: Literal["click","scroll","key","navigate"], selector=None, at=None, container=None, delta=0, key=None, url=None, button="left")`; `SmoothConfig(scroll_merge_window=0.3, max_wait=2.0, min_wait=0.3, type_gap=1.0, type_delay=0.05)`; `smooth(events: list[RawEvent], config=SmoothConfig()) -> list[Step]`; `PRINTABLE_KEY(key: str) -> bool`; `StopHotkey(keys=("f9", "esc"))` with `.start()`, `.stop()`, `.triggered: threading.Event`, `.is_set() -> bool`.

- [ ] **Step 1: Write failing test `tests/test_smooth.py`**

```python
from capturekarma.recorder.events import RawEvent
from capturekarma.recorder.smooth import SmoothConfig, smooth
from capturekarma.scene.model import ClickStep, MoveStep, PressStep, ScrollStep, StepTarget, TypeStep, WaitStep


def test_click_becomes_move_then_click():
    steps = smooth([RawEvent(t=0.1, kind="click", selector="#a", at=(10, 10))])
    assert steps == [MoveStep(to=StepTarget(selector="#a")), ClickStep()]


def test_click_without_selector_uses_at():
    steps = smooth([RawEvent(t=0.1, kind="click", at=(10, 10), button="right")])
    assert steps == [MoveStep(to=StepTarget(at=(10, 10))), ClickStep(button="right")]


def test_gaps_become_capped_waits():
    steps = smooth([RawEvent(t=5.0, kind="click", at=(1, 1)), RawEvent(t=5.5, kind="click", at=(2, 2)),
                    RawEvent(t=5.6, kind="click", at=(3, 3))])
    assert steps[0] == WaitStep(seconds=2.0)               # 5.0 s gap capped
    assert steps[3] == WaitStep(seconds=0.5)               # 0.5 s gap kept
    assert not isinstance(steps[6], WaitStep) and len(steps) == 8   # 0.1 s gap dropped (< min_wait)


def test_scroll_bursts_merge_by_container():
    ev = [RawEvent(t=0.10, kind="scroll", delta=100), RawEvent(t=0.20, kind="scroll", delta=120),
          RawEvent(t=0.35, kind="scroll", delta=80),
          RawEvent(t=0.40, kind="scroll", delta=50, container="#box"),
          RawEvent(t=3.00, kind="scroll", delta=-200)]
    steps = smooth(ev)
    assert steps[0] == ScrollStep(by=300)                     # three page scrolls within 0.3 s merge
    assert steps[1] == ScrollStep(by=50, container="#box")    # different container -> separate step
    assert steps[2] == WaitStep(seconds=2.0)                  # 2.6 s gap capped to max_wait
    assert steps[3] == ScrollStep(by=-200)


def test_keys_group_into_type_and_press():
    ev = [RawEvent(t=0.1, kind="key", key="h"), RawEvent(t=0.2, kind="key", key="i"),
          RawEvent(t=0.3, kind="key", key="Shift"), RawEvent(t=0.4, kind="key", key="!"),
          RawEvent(t=0.5, kind="key", key="Enter"), RawEvent(t=2.1, kind="key", key="x")]
    steps = smooth(ev)
    assert steps == [TypeStep(text="hi!", delay=0.05), PressStep(key="Enter"), WaitStep(seconds=1.6),
                     TypeStep(text="x", delay=0.05)]


def test_typing_pause_splits_type_steps():
    ev = [RawEvent(t=1.0, kind="key", key="a"), RawEvent(t=2.5, kind="key", key="b")]
    assert smooth(ev, SmoothConfig(min_wait=5.0)) == [TypeStep(text="a"), TypeStep(text="b")]


def test_navigate_events_are_ignored_and_input_sorted():
    ev = [RawEvent(t=2.0, kind="click", at=(1, 1)), RawEvent(t=0.5, kind="navigate", url="x")]
    steps = smooth(ev)
    assert steps == [WaitStep(seconds=2.0), MoveStep(to=StepTarget(at=(1, 1))), ClickStep()]
```

- [ ] **Step 2: Run to verify failure** → ImportError.

- [ ] **Step 3: Write `capturekarma/recorder/events.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from capturekarma.scene.model import Point


@dataclass(frozen=True)
class RawEvent:
    """One thing the user did while recording. `t` is seconds since recording start."""
    t: float
    kind: Literal["click", "scroll", "key", "navigate"]
    selector: str | None = None      # web click target
    at: Point | None = None          # web: viewport css px; desktop: region-relative px
    container: str | None = None     # web scroll container selector (None = page)
    delta: int = 0                   # scroll px, positive = down
    key: str | None = None           # key name (Playwright/W3C style: "a", "Enter", "Shift")
    url: str | None = None
    button: Literal["left", "right", "middle"] = "left"
```

- [ ] **Step 4: Write `capturekarma/recorder/smooth.py`**

```python
"""Turn raw recorded events into clean scene steps. Pure function; no timing side effects."""
from __future__ import annotations

from dataclasses import dataclass

from capturekarma.scene.model import ClickStep, MoveStep, PressStep, ScrollStep, Step, StepTarget, TypeStep, WaitStep

from .events import RawEvent

MODIFIER_KEYS = {"Shift", "Control", "Alt", "Meta", "CapsLock", "NumLock", "ScrollLock", "AltGraph"}


@dataclass(frozen=True)
class SmoothConfig:
    scroll_merge_window: float = 0.3   # scroll events closer than this merge into one step
    max_wait: float = 2.0              # long pauses collapse to this
    min_wait: float = 0.3              # shorter pauses are dropped entirely
    type_gap: float = 1.0              # a pause longer than this splits typing into two steps
    type_delay: float = 0.05           # per-character delay written into type steps


def PRINTABLE_KEY(key: str) -> bool:
    return len(key) == 1 and key.isprintable()


def _wait(gap: float, cfg: SmoothConfig) -> list[Step]:
    if gap < cfg.min_wait:
        return []
    return [WaitStep(seconds=round(min(gap, cfg.max_wait), 3))]


def smooth(events: list[RawEvent], config: SmoothConfig = SmoothConfig()) -> list[Step]:
    evs = sorted((e for e in events if e.kind != "navigate"), key=lambda e: e.t)
    steps: list[Step] = []
    last_t = 0.0
    i = 0
    while i < len(evs):
        e = evs[i]
        if e.kind == "click":
            steps += _wait(e.t - last_t, config)
            steps.append(MoveStep(to=StepTarget(selector=e.selector) if e.selector else StepTarget(at=e.at)))
            steps.append(ClickStep(button=e.button))
            last_t = e.t
            i += 1
        elif e.kind == "scroll":
            steps += _wait(e.t - last_t, config)
            total, j = e.delta, i + 1
            while (j < len(evs) and evs[j].kind == "scroll" and evs[j].container == e.container
                   and evs[j].t - evs[j - 1].t <= config.scroll_merge_window):
                total += evs[j].delta
                j += 1
            if total != 0:
                steps.append(ScrollStep(by=total, container=e.container))
            last_t = evs[j - 1].t
            i = j
        elif e.kind == "key":
            assert e.key is not None
            if e.key in MODIFIER_KEYS:
                i += 1
                continue
            steps += _wait(e.t - last_t, config)
            if PRINTABLE_KEY(e.key):
                text, j = e.key, i + 1
                while (j < len(evs) and evs[j].kind == "key" and evs[j].key is not None
                       and (PRINTABLE_KEY(evs[j].key) or evs[j].key in MODIFIER_KEYS)
                       and evs[j].t - evs[j - 1].t <= config.type_gap):
                    if PRINTABLE_KEY(evs[j].key):
                        text += evs[j].key
                    j += 1
                steps.append(TypeStep(text=text, delay=config.type_delay))
                last_t = evs[j - 1].t
                i = j
            else:
                steps.append(PressStep(key=e.key))
                last_t = e.t
                i += 1
        else:
            i += 1
    return steps
```

- [ ] **Step 5: Write `capturekarma/recorder/hotkey.py`**

```python
"""Global stop hotkey (F9 / Esc) via pynput. Works while another window has focus."""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("capturekarma.recorder")


class StopHotkey:
    def __init__(self, keys: tuple[str, ...] = ("f9", "esc")):
        self._names = set(keys)
        self.triggered = threading.Event()
        self._listener = None

    def start(self) -> None:
        from pynput import keyboard

        wanted = {getattr(keyboard.Key, n) for n in self._names if hasattr(keyboard.Key, n)}

        def on_press(key):
            if key in wanted:
                log.info("stop hotkey pressed")
                self.triggered.set()

        self._listener = keyboard.Listener(on_press=on_press)
        self._listener.daemon = True
        self._listener.start()

    def is_set(self) -> bool:
        return self.triggered.is_set()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
```

- [ ] **Step 6: Write `capturekarma/recorder/__init__.py`**

```python
from .events import RawEvent
from .hotkey import StopHotkey
from .smooth import SmoothConfig, smooth

__all__ = ["RawEvent", "StopHotkey", "SmoothConfig", "smooth"]
```
(`WebRecorder`/`DesktopRecorder` are exported in Tasks 9–10.)

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/test_smooth.py -q` → pass.

- [ ] **Step 8: Commit**

```bash
git add capturekarma/recorder tests/test_smooth.py
git commit -m "feat(recorder): raw events, smoothing pass, global stop hotkey"
```

---

### Task 9: WebRecorder (Playwright + injected listeners)

**Files:**
- Create: `capturekarma/recorder/web.py`, `capturekarma/recorder/web_recorder.js`
- Modify: `capturekarma/recorder/__init__.py`
- Test: `tests/test_web_recorder.py` (integration)

**Interfaces:**
- Consumes: `RawEvent`, `smooth`, `SmoothConfig`, `StopHotkey`, scene model, `dump_scene`.
- Produces: `WebRecorder(url, viewport=(1920,1080), headless=False, clock=time.perf_counter)` with `.start()` (launches browser, installs bindings, navigates), `.page`, `.events: list[RawEvent]`, `.wait(stop: threading.Event, poll=0.1)` (returns when stop is set or browser closes), `.stop() -> list[RawEvent]` (closes browser), `.to_scene(name) -> Scene`; `record_web(url, out_path, viewport, name=None) -> Path` (full CLI flow with `StopHotkey`, writes YAML with header).

- [ ] **Step 1: Write failing test `tests/test_web_recorder.py`**

```python
import threading

import pytest

from capturekarma.recorder.events import RawEvent
from capturekarma.recorder.web import WebRecorder
from capturekarma.scene.model import ClickStep, MoveStep, ScrollStep, StepTarget, TypeStep

pytestmark = pytest.mark.integration


@pytest.fixture
def rec(fixture_url):
    r = WebRecorder(fixture_url, viewport=(1000, 600), headless=True)
    r.start()
    yield r
    r.stop()


def _kinds(events: list[RawEvent]) -> list[str]:
    return [e.kind for e in events]


def test_click_records_stable_selector(rec):
    rec.page.click("#btn-primary")
    rec.page.click("#btn-secondary")
    rec.page.click("text=Plain")
    rec.page.wait_for_timeout(200)
    clicks = [e for e in rec.events if e.kind == "click"]
    assert [c.selector for c in clicks] == ['[data-testid="primary"]', "#btn-secondary", "button.plain"]
    assert all(c.at is not None for c in clicks)


def test_scroll_and_keys_recorded(rec):
    # Order matters: type first and scroll the inner box before scrolling the page, so that
    # Playwright never has to auto-scroll an off-screen element into view (which would add
    # extra page-scroll events and break the exact sums below).
    rec.page.click("#email")
    rec.page.keyboard.type("ab")
    rec.page.keyboard.press("Enter")
    rec.page.hover("#box")
    rec.page.mouse.wheel(0, 100)
    rec.page.wait_for_timeout(400)
    rec.page.mouse.move(900, 300)     # right of the box, over the page body
    rec.page.mouse.wheel(0, 400)
    rec.page.wait_for_timeout(400)
    kinds = _kinds(rec.events)
    assert "scroll" in kinds and "key" in kinds
    page_scroll = sum(e.delta for e in rec.events if e.kind == "scroll" and e.container is None)
    assert page_scroll == 400
    box_scroll = sum(e.delta for e in rec.events if e.kind == "scroll" and e.container == "#box")
    assert box_scroll == 100
    assert [e.key for e in rec.events if e.kind == "key"] == ["a", "b", "Enter"]


def test_to_scene_produces_valid_steps(rec):
    rec.page.click("#btn-primary")
    rec.page.click("#email")
    rec.page.keyboard.type("x")
    rec.page.mouse.move(900, 300)
    rec.page.mouse.wheel(0, 300)
    rec.page.wait_for_timeout(400)
    scene = rec.to_scene("t")
    assert scene.target.kind == "web" and scene.target.viewport == (1000, 600)
    kinds = [type(s) for s in scene.steps]
    assert kinds.count(MoveStep) == 2 and kinds.count(ClickStep) == 2 and ScrollStep in kinds and TypeStep in kinds
    assert MoveStep(to=StepTarget(selector='[data-testid="primary"]')) in scene.steps


def test_wait_returns_when_stop_set(rec):
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    rec.wait(stop)  # must return promptly
```

- [ ] **Step 2: Run to verify failure** → ImportError.

- [ ] **Step 3: Write `capturekarma/recorder/web_recorder.js`**

```javascript
// Init script: report user actions to Python via the exposed binding window.__ck_event(json).
(() => {
  if (window.__ckRecorderInstalled) return;
  window.__ckRecorderInstalled = true;

  const cssEscape = s => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/([^\w-])/g, "\\$1");
  const unique = sel => { try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; } };

  function cssPath(el) {
    const parts = [];
    while (el && el.nodeType === 1 && el !== document.body) {
      let part = el.tagName.toLowerCase();
      const parent = el.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(c => c.tagName === el.tagName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(el) + 1})`;
      }
      parts.unshift(part);
      el = parent;
    }
    return "body > " + parts.join(" > ");
  }

  function uniqueSelector(el) {
    // Clicks land on inner spans/icons; walk up to the nearest interactive element first.
    const interactive = el.closest("button, a, input, select, textarea, [role=button], [role=link], [data-testid], label");
    if (interactive) el = interactive;
    const tid = el.getAttribute("data-testid");
    if (tid) { const s = `[data-testid="${tid}"]`; if (unique(s)) return s; }
    if (el.id) { const s = "#" + cssEscape(el.id); if (unique(s)) return s; }
    const tag = el.tagName.toLowerCase();
    const label = el.getAttribute("aria-label");
    if (label) { const s = `${tag}[aria-label="${label}"]`; if (unique(s)) return s; }
    if (el.classList.length) {
      const s = tag + "." + Array.from(el.classList).map(cssEscape).join(".");
      if (unique(s)) return s;
    }
    const text = (el.innerText || "").trim();
    if (text && text.length <= 40 && ["button", "a", "label", "summary"].includes(tag)) {
      const s = `${tag}:has-text("${text.replace(/"/g, '\\"')}")`;
      const matches = Array.from(document.querySelectorAll(tag)).filter(n => (n.innerText || "").trim() === text);
      if (matches.length === 1) return s;
    }
    const path = cssPath(el);
    return unique(path) ? path : null;
  }

  const send = payload => { try { window.__ck_event(JSON.stringify(payload)); } catch (e) {} };

  document.addEventListener("click", e => {
    const button = ["left", "middle", "right"][e.button] || "left";
    send({ kind: "click", selector: uniqueSelector(e.target), at: [Math.round(e.clientX), Math.round(e.clientY)], button });
  }, true);

  const lastTop = new WeakMap();
  const pending = new Map();
  function scrollTargetOf(e) {
    return (e.target === document || e.target === document.documentElement || e.target === document.body)
      ? null : e.target;
  }
  document.addEventListener("scroll", e => {
    const el = scrollTargetOf(e);
    const scroller = el || document.scrollingElement || document.documentElement;
    const top = scroller.scrollTop;
    const prev = lastTop.has(scroller) ? lastTop.get(scroller) : 0;
    lastTop.set(scroller, top);
    const delta = Math.round(top - prev);
    if (!delta) return;
    const key = el || document;
    const acc = (pending.get(key) || 0) + delta;
    pending.set(key, acc);
    if (!key.__ckScrollTimer) {
      key.__ckScrollTimer = setTimeout(() => {
        key.__ckScrollTimer = null;
        const total = pending.get(key) || 0;
        pending.delete(key);
        if (total) send({ kind: "scroll", container: el ? uniqueSelector(el) : null, delta: total });
      }, 100);
    }
  }, true);

  document.addEventListener("keydown", e => {
    if (e.isComposing) return;
    send({ kind: "key", key: e.key });
  }, true);
})();
```

- [ ] **Step 4: Write `capturekarma/recorder/web.py`**

```python
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
from capturekarma.scene.model import Point

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
```

- [ ] **Step 5: Export** in `capturekarma/recorder/__init__.py`: add `from .web import WebRecorder, record_web` and to `__all__`.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_web_recorder.py -q` → pass. If `text=Plain` click yields a different selector than `button.plain`, adjust `uniqueSelector` ordering (class-based before text-based is intended) — the test asserts the intended order.

- [ ] **Step 7: Commit**

```bash
git add capturekarma/recorder tests/test_web_recorder.py
git commit -m "feat(recorder): WebRecorder with injected listeners and stable selector generation"
```

---

### Task 10: DesktopRecorder (pynput)

**Files:**
- Create: `capturekarma/recorder/desktop.py`
- Modify: `capturekarma/recorder/__init__.py`
- Test: `tests/test_desktop_recorder.py`

**Interfaces:**
- Consumes: `RawEvent`, `smooth`, `win_input.find_window/window_client_region`, `StopHotkey`, `dump_scene`.
- Produces: `DesktopRecorder(region: Region, clock=time.perf_counter)` with `.events`, pure handlers `on_click(x, y, button_name: str, pressed: bool)`, `on_scroll(x, y, dx, dy)`, `on_press(key_name: str | None, char: str | None)`, plus `.start()`/`.stop()` (pynput listeners), `.to_scene(name, window=None) -> Scene`; `PYNPUT_KEY_NAMES: dict[str, str]`; `record_desktop(window: str, out_path: Path, name=None) -> Path`.

- [ ] **Step 1: Write failing test `tests/test_desktop_recorder.py`**

```python
from capturekarma.recorder.desktop import DesktopRecorder
from capturekarma.scene.model import ClickStep, MoveStep, PressStep, Region, ScrollStep, StepTarget, TypeStep


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
```

(add `WaitStep` to the import line.)

- [ ] **Step 2: Run to verify failure** → ImportError.

- [ ] **Step 3: Write `capturekarma/recorder/desktop.py`**

```python
"""Record desktop interactions with pynput global hooks into RawEvents."""
from __future__ import annotations

import datetime as _dt
import logging
import time
from pathlib import Path
from typing import Callable

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


class DesktopRecorder:
    def __init__(self, region: Region, clock: Callable[[], float] = time.perf_counter):
        self.region = region
        self._clock = clock
        self._t0 = clock()
        self.events: list[RawEvent] = []
        self._mouse = None
        self._keys = None

    def _t(self) -> float:
        return self._clock() - self._t0

    # ---- pure handlers (unit-tested) ----
    def on_click(self, x: int, y: int, button_name: str, pressed: bool) -> None:
        if not pressed:
            return
        r = self.region
        if not (r.x <= x < r.right and r.y <= y < r.bottom):
            return
        button = button_name if button_name in ("left", "right", "middle") else "left"
        self.events.append(RawEvent(t=self._t(), kind="click", at=(x - r.x, y - r.y), button=button))  # type: ignore[arg-type]

    def on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        if dy:
            self.events.append(RawEvent(t=self._t(), kind="scroll", delta=int(-dy * PX_PER_NOTCH)))

    def on_press(self, key_name: str | None, char: str | None) -> None:
        if key_name in STOP_KEYS:
            return
        if char is not None:
            self.events.append(RawEvent(t=self._t(), kind="key", key=char))
        elif key_name is not None:
            self.events.append(RawEvent(t=self._t(), kind="key", key=PYNPUT_KEY_NAMES.get(key_name, key_name)))

    # ---- pynput wiring ----
    def start(self) -> None:
        from pynput import keyboard, mouse

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
    hwnd, title = win_input.find_window(window)
    win_input.focus_window(hwnd)
    region = win_input.window_client_region(hwnd)
    rec = DesktopRecorder(region)
    hotkey = StopHotkey()
    rec.start()
    hotkey.start()
    try:
        hotkey.triggered.wait()
    finally:
        hotkey.stop()
        rec.stop()
    scene = rec.to_scene(name or Path(out_path).stem, window=window)
    header = f"recorded from window {title!r} on {_dt.date.today().isoformat()} — coordinates are relative to the window client area"
    dump_scene(scene, out_path, header=header)
    log.info("wrote %s (%d steps)", out_path, len(scene.steps))
    return Path(out_path)
```

- [ ] **Step 4: Export** `DesktopRecorder`, `record_desktop` from `capturekarma/recorder/__init__.py`.

- [ ] **Step 5: Run tests** → `uv run pytest tests/test_desktop_recorder.py -q` passes.

- [ ] **Step 6: Commit**

```bash
git add capturekarma/recorder tests/test_desktop_recorder.py
git commit -m "feat(recorder): DesktopRecorder with pynput hooks"
```

---

### Task 11: Player — cursor timeline and run orchestration

**Files:**
- Create: `capturekarma/player/timeline.py`, `capturekarma/player/player.py`, `capturekarma/player/__init__.py`
- Test: `tests/test_player.py`

**Interfaces:**
- Consumes: everything above. Injectable: `driver: Driver`, `capture_factory(region, fps, out_path) -> capture` (object with `.stop() -> Path`, `.frames`), `overlay_factory(style, ripple, visible) -> overlay` (with `set_position/set_visible/click/start/stop`), `ticker: Ticker`, `stop_event: threading.Event`, `now: Callable[[], datetime]`.
- Produces: `CursorTimeline()` with `.add(t, x, y, visible, click=False)`, `.samples`, `.dump(path, region, hz)`; `PlayOptions(out_dir=None, cursor_visible=None, cursor_style=None, hz=120, prefer_ddagrab=True)`; `RunResult(video: Path, timeline: Path, partial: bool, duration: float, frames: int)`; `Player(scene, options=PlayOptions(), *, driver=None, capture_factory=None, overlay_factory=None, ticker=None, stop_event=None, now=None)` with `.run() -> RunResult`; `make_driver(scene) -> Driver`; `default_capture_factory(prefer_ddagrab) -> capture_factory`.

- [ ] **Step 1: Write failing test `tests/test_player.py`**

```python
import datetime as dt
import json
import threading
from pathlib import Path

import pytest

from capturekarma.drivers.base import StepError
from capturekarma.motion.ticker import Ticker
from capturekarma.player.player import Player, PlayOptions
from capturekarma.scene import parse_scene
from capturekarma.scene.model import Region


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeDriver:
    def __init__(self, clock: FakeClock, region=Region(100, 100, 800, 600)):
        self.clock = clock
        self.region = region
        self.calls: list[tuple] = []
        self.fail_on_selector: str | None = None

    def setup(self, scene):
        self.calls.append(("setup",)); return self.region

    def resolve(self, target):
        if target.selector == self.fail_on_selector:
            raise StepError(f"element not found: {target.selector}")
        if target.at:
            return (self.region.x + target.at[0], self.region.y + target.at[1])
        return (self.region.x + 400, self.region.y + 300)

    def pointer_to(self, x, y): self.calls.append(("pos", x, y))
    def mouse_down(self, button="left"): self.calls.append(("down", button))
    def mouse_up(self, button="left"): self.calls.append(("up", button))
    def smooth_scroll(self, step, duration, easing):
        self.calls.append(("scroll", step.by, step.to, round(duration, 3)))
        self.clock.sleep(duration)   # a real driver blocks for the scroll's duration
    def type_text(self, text, delay): self.calls.append(("type", text, delay))
    def press(self, key): self.calls.append(("press", key))
    def screenshot(self, path): Path(path).write_bytes(b"png"); self.calls.append(("shot", Path(path).name))
    def teardown(self): self.calls.append(("teardown",))


class FakeCapture:
    def __init__(self, region, fps, out_path):
        self.region, self.fps, self.out_path = region, fps, Path(out_path)
        self.frames = 0
        self.stopped = False

    def stop(self):
        self.stopped = True
        self.out_path.write_bytes(b"mp4")
        self.frames = 123
        return self.out_path


class FakeOverlay:
    def __init__(self, style, ripple, visible):
        self.style, self.ripple, self.visible = style, ripple, visible
        self.positions: list[tuple] = []
        self.vis: list[bool] = []
        self.clicks = 0
        self.started = self.stopped = False

    def start(self): self.started = True
    def stop(self): self.stopped = True
    def set_position(self, x, y): self.positions.append((x, y))
    def set_visible(self, v): self.vis.append(v)
    def click(self): self.clicks += 1


SCENE = {
    "version": 1, "name": "demo",
    "target": {"kind": "web", "url": "http://x", "viewport": [800, 600]},
    "output": {"fps": 60, "lead_in": 0.5, "lead_out": 0.5},
    "cursor": {"speed": 1000},
    "defaults": {"hold": 0.2},
    "steps": [
        {"move": {"to": [100, 100]}},
        {"click": {}},
        {"scroll": {"by": 900}},
        {"type": {"text": "hi", "delay": 0.01}},
        {"press": "Enter"},
        {"cursor": "hidden"},
        {"wait": 0.3},
        {"cursor": "visible"},
    ],
}


def _player(tmp_path, scene_dict=SCENE, **kw):
    clock = FakeClock()
    ticker = Ticker(hz=10, clock=clock.now, sleep=clock.sleep)
    drv = FakeDriver(clock)
    caps: list[FakeCapture] = []
    ovs: list[FakeOverlay] = []

    def cap_factory(region, fps, out_path):
        c = FakeCapture(region, fps, out_path); caps.append(c); return c

    def ov_factory(style, ripple, visible):
        o = FakeOverlay(style, ripple, visible); ovs.append(o); return o

    scene = parse_scene(scene_dict)
    p = Player(scene, PlayOptions(out_dir=tmp_path, hz=10, **kw), driver=drv, capture_factory=cap_factory,
               overlay_factory=ov_factory, ticker=ticker, now=lambda: dt.datetime(2026, 8, 27, 12, 0, 0))
    return p, drv, caps, ovs, clock


def test_run_produces_video_and_timeline(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path)
    res = p.run()
    assert res.video == tmp_path / "demo_20260827_120000.mp4" and res.video.exists()
    assert res.timeline == tmp_path / "demo_20260827_120000.cursor.json" and res.partial is False
    assert res.frames == 123
    data = json.loads(res.timeline.read_text())
    assert data["region"] == [100, 100, 800, 600] and data["hz"] == 10 and len(data["samples"]) > 5
    assert caps[0].stopped and ovs[0].started and ovs[0].stopped
    assert drv.calls[0] == ("setup",) and drv.calls[-1] == ("teardown",)


def test_step_sequence(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path)
    p.run()
    kinds = [c[0] for c in drv.calls]
    # move: distance from region center (500,400) to (200,200) = 424 px at 1000 px/s -> 0.42 s -> 4 ticks at 10 Hz
    assert kinds.count("pos") == 1 + 4          # initial center + move ticks
    assert drv.calls[kinds.index("down") - 1][0] == "pos"       # click happens after the move
    assert ("down", "left") in drv.calls and ("up", "left") in drv.calls
    assert ("scroll", 900, None, 1.0) in drv.calls              # 900px / 900 px/s = 1.0 s
    assert ("type", "hi", 0.01) in drv.calls and ("press", "Enter") in drv.calls
    assert ovs[0].vis == [False, True] and ovs[0].clicks == 1
    assert ovs[0].positions[-1] == (200, 200)


def test_timing_includes_lead_in_holds_and_lead_out(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path)
    res = p.run()
    # lead_in 0.5 + move 0.4 (4 ticks) + hold 0.2 + click (0.08 press + hold 0.2) + scroll 1.0 + hold 0.2
    # + type hold 0.2 + press hold 0.2 + cursor (no hold) + wait 0.3 + hold 0.2 + cursor + lead_out 0.5 = 4.18
    assert res.duration == pytest.approx(4.18, abs=0.15)


def test_cursor_visible_override_and_style(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path, cursor_visible=False, cursor_style="default")
    p.run()
    assert ovs[0].visible is False and ovs[0].style == "default"


def test_abort_keeps_partial_video(tmp_path):
    p, drv, caps, ovs, clock = _player(tmp_path)
    p.stop_event.set()
    res = p.run()
    assert res.partial is True and res.video.name == "demo_20260827_120000.partial.mp4" and res.video.exists()
    assert not (tmp_path / "demo_20260827_120000.mp4").exists()
    assert caps[0].stopped and drv.calls[-1] == ("teardown",)


def test_step_error_adds_index_and_screenshot_and_cleans_up(tmp_path):
    scene = {**SCENE, "steps": [{"wait": 0.1}, {"move": {"to": "#missing"}}]}
    p, drv, caps, ovs, clock = _player(tmp_path, scene_dict=scene)
    drv.fail_on_selector = "#missing"
    with pytest.raises(StepError) as ei:
        p.run()
    assert ei.value.step_index == 1 and "step 2" in str(ei.value)
    assert ei.value.screenshot == tmp_path / "demo_20260827_120000.error.png" and ei.value.screenshot.exists()
    assert caps[0].stopped and ovs[0].stopped and drv.calls[-1] == ("teardown",)
    assert (tmp_path / "demo_20260827_120000.partial.mp4").exists()


def test_desktop_scene_uses_region_relative_click_target(tmp_path):
    scene = {"version": 1, "name": "d", "target": {"kind": "desktop", "window": "N"},
             "steps": [{"click": {"to": [10, 20]}}]}
    p, drv, caps, ovs, clock = _player(tmp_path, scene_dict=scene)
    p.run()
    assert ovs[0].positions[-1] == (110, 120)
```

- [ ] **Step 2: Run to verify failure** → ImportError.

- [ ] **Step 3: Write `capturekarma/player/timeline.py`**

```python
from __future__ import annotations

import json
from pathlib import Path

from capturekarma.scene.model import Region


class CursorTimeline:
    """Per-tick cursor samples: [t, x, y, visible, click]. Enables post-compositing later."""

    def __init__(self) -> None:
        self.samples: list[list] = []

    def add(self, t: float, x: int, y: int, visible: bool, click: bool = False) -> None:
        self.samples.append([round(t, 4), int(x), int(y), bool(visible), bool(click)])

    def dump(self, path: Path, region: Region, hz: int) -> Path:
        data = {"version": 1, "hz": hz, "region": [region.x, region.y, region.width, region.height],
                "fields": ["t", "x", "y", "visible", "click"], "samples": self.samples}
        Path(path).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        return Path(path)
```

- [ ] **Step 4: Write `capturekarma/player/player.py`**

```python
"""Plays a Scene: drives the target, draws the cursor overlay, captures video."""
from __future__ import annotations

import datetime as _dt
import logging
import math
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from capturekarma._win import high_res_timer, set_dpi_awareness
from capturekarma.drivers.base import Driver, StepError
from capturekarma.motion import Ticker, bezier_path, get_easing, move_duration, scroll_duration
from capturekarma.scene.model import (
    ClickStep, CursorStep, MoveStep, Point, PressStep, Region, Scene, ScrollStep, Step, TypeStep, WaitStep,
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
        self._t0 = 0.0
        self._clock = self.ticker.now  # same clock as the ticker so timeline timestamps line up
        self._pointer: Point = (0, 0)
        self._visible = scene.cursor.visible if options.cursor_visible is None else options.cursor_visible
        self._overlay = None
        self._move_index = 0

    # ---- helpers ----
    def _elapsed(self) -> float:
        return self._clock() - self._t0

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

    def _run_step(self, idx: int, step: Step) -> None:
        if isinstance(step, WaitStep):
            self._hold(step.seconds)
        elif isinstance(step, MoveStep):
            self._move(self.driver.resolve(step.to), step)
        elif isinstance(step, ClickStep):
            if step.to is not None:
                self._move(self.driver.resolve(step.to), step)
            self._click(step)
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
        out = lambda ext: Path(f"{base}{ext}")  # noqa: E731 - str concat, not with_suffix (scene names may contain dots)
        video = out(".mp4")
        style = self.options.cursor_style or self.scene.cursor.style

        region = self.driver.setup(self.scene)
        capture = None
        partial = False
        error: BaseException | None = None
        try:
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
            duration = self._elapsed() if self._t0 else 0.0
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
            if self._overlay is not None:
                self._overlay.stop()
            self.driver.teardown()
        if error is not None:
            raise error
        timeline = self.timeline.dump(out(".cursor.json"), region, self.ticker.hz)
        log.info("saved %s (%.1fs, %d frames)", video, duration, frames)
        return RunResult(video=video, timeline=timeline, partial=partial, duration=duration, frames=frames)
```

Note: output names are built by string concatenation (`out(ext)`), never `Path.with_suffix`, because a scene name like `v1.2-demo` contains a dot and `with_suffix` would eat `.2-demo`.

- [ ] **Step 5: Write `capturekarma/player/__init__.py`**

```python
from .player import Player, PlayOptions, RunResult, make_driver
from .timeline import CursorTimeline

__all__ = ["Player", "PlayOptions", "RunResult", "make_driver", "CursorTimeline"]
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_player.py -q` → pass. If `test_timing_...` is off, print the per-step elapsed and reconcile with the comment in the test; the tolerance is 0.15 s.

- [ ] **Step 7: Commit**

```bash
git add capturekarma/player tests/test_player.py
git commit -m "feat(player): scene playback with cursor overlay, capture lifecycle, abort and error handling"
```

---

### Task 12: Doctor, CLI, examples, end-to-end test

**Files:**
- Create: `capturekarma/doctor.py`, `capturekarma/cli.py`, `examples/web-demo.yaml`, `examples/desktop-notepad.yaml`
- Test: `tests/test_cli.py`, `tests/test_e2e_win32.py`

**Interfaces:**
- Consumes: `load_scene`, `Player`, `PlayOptions`, `record_web`, `record_desktop`, `find_ffmpeg`, `probe`, `list_monitors`, `set_dpi_awareness`, `StopHotkey`.
- Produces: `Check(name, ok, detail, fix: str | None)`; `run_doctor() -> list[Check]`; typer app `capturekarma.cli:app` and `main()`; commands `record web URL [-o PATH] [--viewport WxH] [--name NAME]`, `record desktop --window TITLE [-o PATH] [--name NAME]`, `play SCENE [--out-dir DIR] [--no-cursor] [--cursor-style STYLE] [--gdigrab]`, `doctor`. Exit code 1 with a one-line `error: ...` on `SceneError`/`StepError`/`DriverError`/`CaptureError`.

- [ ] **Step 1: Write failing tests**

`tests/test_cli.py`:
```python
from pathlib import Path
from unittest import mock

from typer.testing import CliRunner

from capturekarma.cli import app
from capturekarma.player.player import RunResult

runner = CliRunner()


def test_play_reports_scene_error(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nname: x\ntarget: {kind: web}\nsteps: []\n", encoding="utf-8")
    r = runner.invoke(app, ["play", str(bad)])
    assert r.exit_code == 1 and "error:" in r.output and "url" in r.output


def test_play_invokes_player_with_options(tmp_path: Path):
    scene = tmp_path / "s.yaml"
    scene.write_text("version: 1\nname: x\ntarget: {kind: web, url: 'http://x'}\nsteps: []\n", encoding="utf-8")
    fake = RunResult(video=tmp_path / "x.mp4", timeline=tmp_path / "x.cursor.json", partial=False, duration=1.0, frames=60)
    with mock.patch("capturekarma.cli.Player") as P:
        P.return_value.run.return_value = fake
        r = runner.invoke(app, ["play", str(scene), "--out-dir", str(tmp_path), "--no-cursor", "--gdigrab"])
    assert r.exit_code == 0, r.output
    opts = P.call_args.args[1]
    assert opts.out_dir == tmp_path and opts.cursor_visible is False and opts.prefer_ddagrab is False
    assert "x.mp4" in r.output


def test_record_web_parses_viewport(tmp_path: Path):
    with mock.patch("capturekarma.cli.record_web", return_value=tmp_path / "o.yaml") as rw:
        r = runner.invoke(app, ["record", "web", "http://x", "-o", str(tmp_path / "o.yaml"), "--viewport", "1280x720"])
    assert r.exit_code == 0, r.output
    assert rw.call_args.kwargs["viewport"] == (1280, 720)


def test_record_web_bad_viewport():
    r = runner.invoke(app, ["record", "web", "http://x", "--viewport", "big"])
    assert r.exit_code != 0 and "WxH" in r.output


def test_doctor_runs(tmp_path: Path):
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code in (0, 1) and "ffmpeg" in r.output
```

`tests/test_e2e_win32.py`:
```python
"""Full pipeline on a real desktop: play the bundled web fixture scene and probe the MP4."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from capturekarma.player import Player, PlayOptions
from capturekarma.scene import parse_scene

pytestmark = [pytest.mark.win32, pytest.mark.integration]


def test_play_web_fixture_end_to_end(tmp_path: Path, fixture_url: str):
    scene = parse_scene({
        "version": 1, "name": "e2e",
        "target": {"kind": "web", "url": fixture_url, "viewport": [1000, 600]},
        "output": {"fps": 60, "lead_in": 0.3, "lead_out": 0.3},
        "defaults": {"hold": 0.2},
        "steps": [
            {"move": {"to": "#btn-primary"}}, {"click": {}},
            {"scroll": {"by": 600, "duration": 1.0}},
            {"cursor": "hidden"}, {"wait": 0.3}, {"cursor": "visible"},
            {"move": {"to": "#email"}}, {"click": {}}, {"type": {"text": "hi", "delay": 0.02}},
        ],
    })
    res = Player(scene, PlayOptions(out_dir=tmp_path)).run()
    assert res.video.exists() and res.partial is False and res.timeline.exists()
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        pytest.skip("ffprobe not on PATH; video produced but not probed")
    info = json.loads(subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=r_frame_rate,width,height:format=duration", "-of", "json", str(res.video)],
        capture_output=True, text=True, check=True).stdout)
    assert info["streams"][0]["r_frame_rate"] == "60/1"
    assert abs(float(info["format"]["duration"]) - res.duration) <= 0.5
    assert info["streams"][0]["width"] % 2 == 0 and info["streams"][0]["height"] % 2 == 0
```

- [ ] **Step 2: Run to verify failure** → ImportError on `capturekarma.cli`.

- [ ] **Step 3: Write `capturekarma/doctor.py`**

```python
"""Environment checks with actionable fixes."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from capturekarma._win import IS_WINDOWS, set_dpi_awareness


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    fix: str | None = None


def run_doctor() -> list[Check]:
    from capturekarma.capture import CaptureError, find_ffmpeg, list_monitors, probe

    checks: list[Check] = []
    checks.append(Check("windows", IS_WINDOWS, "Windows desktop session" if IS_WINDOWS else "not Windows",
                        None if IS_WINDOWS else "CaptureKarma v2 captures only on Windows 10/11"))
    checks.append(Check("dpi awareness", set_dpi_awareness(), "per-monitor v2 requested",
                        None if IS_WINDOWS else "n/a off Windows"))

    exe = find_ffmpeg()
    if not exe:
        checks.append(Check("ffmpeg", False, "not found", "install ffmpeg (winget install Gyan.FFmpeg) or `uv sync` for the bundled imageio-ffmpeg binary"))
    else:
        caps = probe(exe)
        checks.append(Check("ffmpeg", True, f"{caps.version} at {exe}"))
        checks.append(Check("ddagrab", caps.ddagrab, "GPU desktop duplication capture available" if caps.ddagrab else "missing",
                            None if caps.ddagrab else "install a full ffmpeg build (Gyan.FFmpeg); gdigrab fallback will be used"))
        checks.append(Check("h264_nvenc", caps.nvenc, "NVIDIA hardware encoder available" if caps.nvenc else "not available",
                            None if caps.nvenc else "libx264 software encoding will be used (fine up to 1440p60)"))
        checks.append(Check("libx264", caps.libx264, "software encoder available" if caps.libx264 else "missing",
                            None if caps.libx264 else "install a full ffmpeg build"))

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            path = Path(p.chromium.executable_path)
            ok = path.exists()
        checks.append(Check("playwright chromium", ok, str(path) if ok else "browser not installed",
                            None if ok else "run: uv run playwright install chromium"))
    except Exception as exc:  # noqa: BLE001 - reported as a failed check
        checks.append(Check("playwright chromium", False, str(exc), "run: uv sync && uv run playwright install chromium"))

    if IS_WINDOWS:
        try:
            mons = list_monitors()
            checks.append(Check("monitors", True, "; ".join(
                f"{m.index}: {m.region.width}x{m.region.height} @({m.region.x},{m.region.y}){' primary' if m.primary else ''}"
                for m in mons)))
        except CaptureError as exc:
            checks.append(Check("monitors", False, str(exc), None))
    return checks
```

- [ ] **Step 4: Write `capturekarma/cli.py`**

```python
"""`ck` command line."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import typer

from capturekarma.capture import CaptureError
from capturekarma.drivers.base import DriverError, StepError
from capturekarma.player import Player, PlayOptions
from capturekarma.recorder.desktop import record_desktop
from capturekarma.recorder.hotkey import StopHotkey
from capturekarma.recorder.web import record_web
from capturekarma.scene import SceneError, load_scene

app = typer.Typer(help="CaptureKarma: record a demo once, replay it cinematically, capture to MP4.",
                  no_args_is_help=True)
record_app = typer.Typer(help="Record a scene file by performing the demo once.", no_args_is_help=True)
app.add_typer(record_app, name="record")

_ERRORS = (SceneError, StepError, DriverError, CaptureError)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _fail(exc: BaseException) -> None:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=False)
    raise typer.Exit(code=1)


def _parse_viewport(value: str) -> tuple[int, int]:
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise typer.BadParameter("expected WxH, e.g. 1920x1080") from None


@record_app.command("web")
def record_web_cmd(
    url: str = typer.Argument(..., help="Page to open"),
    out: Path = typer.Option(Path("scene.yaml"), "-o", "--out", help="Scene file to write"),
    viewport: str = typer.Option("1920x1080", help="Viewport WxH in CSS px"),
    name: Optional[str] = typer.Option(None, help="Scene name (default: file stem)"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Open URL in Chromium, record your clicks/scrolls/typing; press F9 or close the browser to stop."""
    _setup_logging(verbose)
    vp = _parse_viewport(viewport)
    try:
        path = record_web(url, out, viewport=vp, name=name)
    except _ERRORS as exc:
        _fail(exc)
    typer.echo(f"wrote {path}")


@record_app.command("desktop")
def record_desktop_cmd(
    window: str = typer.Option(..., "--window", "-w", help="Substring of the target window title"),
    out: Path = typer.Option(Path("scene.yaml"), "-o", "--out"),
    name: Optional[str] = typer.Option(None),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Record clicks/scrolls/typing in a desktop window; press F9 to stop."""
    _setup_logging(verbose)
    try:
        path = record_desktop(window, out, name=name)
    except _ERRORS as exc:
        _fail(exc)
    typer.echo(f"wrote {path}")


@app.command()
def play(
    scene: Path = typer.Argument(..., exists=True, dir_okay=False, help="Scene YAML file"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir", help="Override output directory"),
    no_cursor: bool = typer.Option(False, "--no-cursor", help="Hide the rendered cursor for this run"),
    cursor_style: Optional[str] = typer.Option(None, "--cursor-style"),
    gdigrab: bool = typer.Option(False, "--gdigrab", help="Force the gdigrab capture backend"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Replay a scene and record it to MP4. Press F9 or Esc to abort (partial video is kept)."""
    _setup_logging(verbose)
    try:
        sc = load_scene(scene)
        opts = PlayOptions(out_dir=out_dir, cursor_visible=False if no_cursor else None,
                           cursor_style=cursor_style, prefer_ddagrab=not gdigrab)
        hotkey = StopHotkey()
        hotkey.start()
        try:
            result = Player(sc, opts, stop_event=hotkey.triggered).run()
        except KeyboardInterrupt:
            hotkey.triggered.set()
            raise
        finally:
            hotkey.stop()
    except _ERRORS as exc:
        _fail(exc)
    status = "PARTIAL " if result.partial else ""
    typer.echo(f"{status}saved {result.video} ({result.duration:.1f}s, {result.frames} frames)")
    typer.echo(f"cursor timeline: {result.timeline}")


@app.command()
def doctor() -> None:
    """Check ffmpeg, capture backends, encoders, Playwright, monitors."""
    from capturekarma.doctor import run_doctor

    checks = run_doctor()
    for c in checks:
        mark = typer.style("OK  ", fg=typer.colors.GREEN) if c.ok else typer.style("FAIL", fg=typer.colors.RED)
        typer.echo(f"{mark} {c.name:<20} {c.detail}")
        if not c.ok and c.fix:
            typer.echo(f"     fix: {c.fix}")
    if not all(c.ok for c in checks if c.name in ("ffmpeg", "playwright chromium", "windows")):
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Write examples**

`examples/web-demo.yaml`:
```yaml
# Plays against the bundled fixture page. Run:  uv run ck play examples/web-demo.yaml
# Replace target.url with your product URL and re-record with:  uv run ck record web <url> -o my-scene.yaml
version: 1
name: web-demo
target:
  kind: web
  url: file:///REPLACE/WITH/ABSOLUTE/PATH/tests/fixtures/page.html
  viewport: [1280, 720]
output:
  fps: 60
  dir: ~/Videos/CaptureKarma
cursor:
  visible: true
  style: default
  ripple: true
  speed: 1400
defaults:
  easing: ease_in_out_cubic
  hold: 0.6
steps:
  - wait: 0.5
  - move: {to: "#btn-primary"}
  - click: {}
  - scroll: {by: 900, duration: 2.5}
  - scroll: {by: -900, duration: 2.0}
  - move: {to: "#email"}
  - click: {}
  - type: {text: "hello@example.com", delay: 0.06}
  - cursor: hidden
  - wait: 1.0
  - cursor: visible
  - move: {to: [640, 360], duration: 1.2}
```
In the implementer's step, replace `REPLACE/WITH/ABSOLUTE/PATH` with the real absolute path of the repo on this machine (`D:/Repos/CaptureKarma`) — file URLs need it.

`examples/desktop-notepad.yaml`:
```yaml
# Open Notepad first, then:  uv run ck play examples/desktop-notepad.yaml
# Desktop coordinates are relative to the window's client area (top-left = 0,0).
version: 1
name: desktop-notepad
target:
  kind: desktop
  window: "Notepad"
output:
  fps: 60
cursor:
  speed: 1200
defaults:
  hold: 0.5
steps:
  - wait: 0.5
  - click: {to: [200, 150]}
  - type: {text: "CaptureKarma desktop demo", delay: 0.05}
  - press: Enter
  - type: {text: "Smooth cursor, scripted typing, reliable takes.", delay: 0.04}
  - move: {to: [400, 300], duration: 1.0}
  - scroll: {by: 300, duration: 1.5}
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_cli.py -q` → pass. Then on Windows: `uv run pytest tests/test_e2e_win32.py -q -s` → pass (a Chromium window opens for ~5 s; a cursor arrow glides; MP4 lands in the tmp dir). Then `uv run ck doctor` and `uv run ck play examples/web-demo.yaml`; **open the resulting MP4** and confirm: cursor visible with a ripple on click, no browser chrome, smooth scroll, cursor disappears/reappears around the `cursor: hidden` step. Report what you saw.

- [ ] **Step 7: Commit**

```bash
git add capturekarma/doctor.py capturekarma/cli.py examples tests/test_cli.py tests/test_e2e_win32.py
git commit -m "feat(cli): ck record/play/doctor, example scenes, end-to-end test"
```

---

### Task 13: README and CLAUDE.md

**Files:**
- Modify: `README.md` (rewrite), `CLAUDE.md` (finalize)

- [ ] **Step 1: Rewrite `README.md`**

Keep the existing "The Story Behind CaptureKarma" section verbatim, then replace everything else with:

```markdown
# CaptureKarma

Record a product demo once. Replay it with cinematic cursor and scroll motion. Capture to MP4. Every take identical.

## The Story Behind CaptureKarma
<keep the existing paragraphs>

## What changed in v2

v1 recorded the screen while sending mouse-wheel events. v2 separates **what** happens from **how it looks**:

1. `ck record` watches you perform the flow once and writes a small YAML **scene file**.
2. `ck play` replays that scene with eased cursor paths, pixel-deterministic scrolling and a rendered cursor
   (with click ripples), while ffmpeg captures the region at 60 fps to H.264 MP4.

Web targets (Chromium via Playwright) are first-class; desktop windows are supported with best-effort scrolling.

## Install (Windows 10/11)

    uv sync
    uv run playwright install chromium
    uv run ck doctor

ffmpeg is bundled through `imageio-ffmpeg` (includes `ddagrab` GPU capture and NVENC). `ck doctor` tells you if anything is missing.

## Usage

    uv run ck record web https://your.app/pricing -o pricing.yaml      # perform the demo, press F9 to stop
    uv run ck play pricing.yaml                                           # MP4 lands in ~/Videos/CaptureKarma
    uv run ck record desktop --window "Notepad" -o notepad.yaml
    uv run ck play notepad.yaml --no-cursor

Press **F9** or **Esc** during playback to abort; the partial video is kept.

## Scene files

<paste the YAML example from the spec §3.7 and the step-type table: wait, move, click, scroll, type, press, cursor;
explain: web targets are selectors or `[x, y]` viewport px; desktop targets are `[x, y]` relative to the window;
omitted `duration` is derived from distance (`cursor.speed`) or scroll length; `hold` is the pause after a step.>

## Output

`<name>_<timestamp>.mp4` (H.264, native region resolution, 60 fps) plus `<name>_<timestamp>.cursor.json`, a per-tick
cursor timeline for future post-processing (auto-zoom, restyling). Errors save `<name>_<timestamp>.error.png`.

## Limitations

- Windows only. Desktop scrolling depends on how the target app handles wheel events.
- Web element targets must be on screen when used; add a `scroll` step first (the recorder does this for you).

## Development

    uv run pytest -q                                  # pure tests
    uv run pytest -q -m "win32 or integration"        # everything, needs a desktop + Chromium

## License

MIT — see LICENSE.
```

- [ ] **Step 2: Finalize `CLAUDE.md`** — keep the Task 1 version and add a "Gotchas" section:

```markdown
## Gotchas

- Call `set_dpi_awareness()` before creating any window or enumerating monitors, or coordinates will be logical px.
- ddagrab `output_idx` is assumed to equal `EnumDisplayMonitors` order (single GPU). `--gdigrab` is the escape hatch.
- Playwright's virtual mouse never moves the OS cursor; the overlay is the only cursor in web recordings.
- `WebDriver.setup` resizes the browser window so `innerWidth/Height` equals the scene viewport; the capture region is
  the viewport only (no browser chrome).
- Overlay window is `WS_EX_TRANSPARENT` (click-through) and updated with `UpdateLayeredWindow`; it must stay in the
  capture (ddagrab composites it), while `draw_mouse=0` keeps the real cursor out.
- `smooth()` is pure — test recorder behaviour there, not through pynput/Playwright.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: rewrite README for v2, finalize CLAUDE.md"
```

---

### Task 14: Thin PySide6 GUI

**Files:**
- Create: `capturekarma/gui/worker.py`, `capturekarma/gui/main_window.py`, `capturekarma/gui/app.py`
- Modify: `pyproject.toml` (add `ck-gui = "capturekarma.gui.app:main"` under `[project.scripts]`)
- Test: `tests/test_gui.py`

**Interfaces:**
- Consumes: `load_scene`, `Player`, `PlayOptions`, `record_web`, `record_desktop`, `win_input.list_window_titles`, `available_styles`, `StopHotkey`.
- Produces: `Worker(fn: Callable[[], object])` QThread with signals `log(str)`, `done(object)`, `failed(str)`; `MainWindow(scenes_dir: Path)` with widgets named `scene_list`, `url_edit`, `record_web_btn`, `window_combo`, `record_desktop_btn`, `play_btn`, `open_btn`, `show_cursor_cb`, `style_combo`, `log_view`; method `refresh_scenes()`; `main()`.

- [ ] **Step 1: Write failing test `tests/test_gui.py`**

```python
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from capturekarma.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_scene_list_and_play_enabled_state(qapp, tmp_path: Path):
    (tmp_path / "a.yaml").write_text("version: 1\nname: a\ntarget: {kind: web, url: 'http://x'}\nsteps: []\n")
    (tmp_path / "notes.txt").write_text("x")
    w = MainWindow(scenes_dir=tmp_path)
    assert [w.scene_list.item(i).text() for i in range(w.scene_list.count())] == ["a.yaml"]
    assert not w.play_btn.isEnabled()
    w.scene_list.setCurrentRow(0)
    assert w.play_btn.isEnabled()
    assert w.show_cursor_cb.isChecked() and w.style_combo.currentText() == "default"


def test_log_appends(qapp, tmp_path: Path):
    w = MainWindow(scenes_dir=tmp_path)
    w.append_log("hello")
    assert "hello" in w.log_view.toPlainText()
```

- [ ] **Step 2: Run to verify failure** → ImportError.

- [ ] **Step 3: Write `capturekarma/gui/worker.py`**

```python
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QThread, Signal


class _QtLogHandler(logging.Handler):
    def __init__(self, emit: Callable[[str], None]):
        super().__init__(level=logging.INFO)
        self._emit = emit

    def emit(self, record: logging.LogRecord) -> None:
        self._emit(self.format(record))


class Worker(QThread):
    """Runs a blocking callable off the UI thread; relays library logs and the result via signals."""
    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        handler = _QtLogHandler(self.log.emit)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger("capturekarma")
        root.addHandler(handler)
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 - every failure must reach the UI log
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            root.removeHandler(handler)
```

- [ ] **Step 4: Write `capturekarma/gui/main_window.py`**

```python
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from capturekarma._win import IS_WINDOWS
from capturekarma.cursor.sprites import available_styles
from capturekarma.player import Player, PlayOptions
from capturekarma.recorder.desktop import record_desktop
from capturekarma.recorder.web import record_web
from capturekarma.scene import load_scene

from .worker import Worker


class MainWindow(QMainWindow):
    def __init__(self, scenes_dir: Path):
        super().__init__()
        self.setWindowTitle("CaptureKarma")
        self.resize(820, 600)
        self.scenes_dir = Path(scenes_dir)
        self.scenes_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = Path("~/Videos/CaptureKarma").expanduser()
        self._worker: Worker | None = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)

        # left: scenes
        left = QVBoxLayout()
        left.addWidget(QLabel(f"Scenes in {self.scenes_dir}"))
        self.scene_list = QListWidget()
        self.scene_list.currentRowChanged.connect(lambda _r: self._update_buttons())
        left.addWidget(self.scene_list, 1)
        row = QHBoxLayout()
        self.choose_dir_btn = QPushButton("Scenes folder…")
        self.choose_dir_btn.clicked.connect(self._choose_scenes_dir)
        self.play_btn = QPushButton("Play selected")
        self.play_btn.clicked.connect(self._play)
        row.addWidget(self.choose_dir_btn)
        row.addWidget(self.play_btn)
        left.addLayout(row)
        layout.addLayout(left, 1)

        # right: record + options + log
        right = QVBoxLayout()
        rec = QGroupBox("Record")
        rec_l = QVBoxLayout(rec)
        web_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://your.app/page")
        self.record_web_btn = QPushButton("Record web")
        self.record_web_btn.clicked.connect(self._record_web)
        web_row.addWidget(self.url_edit, 1)
        web_row.addWidget(self.record_web_btn)
        rec_l.addLayout(web_row)
        desk_row = QHBoxLayout()
        self.window_combo = QComboBox()
        self.window_combo.setEditable(True)
        self.refresh_windows_btn = QPushButton("↻")
        self.refresh_windows_btn.setFixedWidth(32)
        self.refresh_windows_btn.clicked.connect(self.refresh_windows)
        self.record_desktop_btn = QPushButton("Record desktop")
        self.record_desktop_btn.clicked.connect(self._record_desktop)
        desk_row.addWidget(self.window_combo, 1)
        desk_row.addWidget(self.refresh_windows_btn)
        desk_row.addWidget(self.record_desktop_btn)
        rec_l.addLayout(desk_row)
        rec_l.addWidget(QLabel("Press F9 in any window to stop recording or abort playback."))
        right.addWidget(rec)

        opts = QGroupBox("Playback options (override the scene for this run)")
        opts_l = QHBoxLayout(opts)
        self.show_cursor_cb = QCheckBox("Show cursor")
        self.show_cursor_cb.setChecked(True)
        self.style_combo = QComboBox()
        self.style_combo.addItems(available_styles())
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.clicked.connect(self._open_output)
        opts_l.addWidget(self.show_cursor_cb)
        opts_l.addWidget(QLabel("Cursor style"))
        opts_l.addWidget(self.style_combo)
        opts_l.addStretch(1)
        opts_l.addWidget(self.open_btn)
        right.addWidget(opts)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        right.addWidget(self.log_view, 1)
        layout.addLayout(right, 2)

        self.refresh_scenes()
        self.refresh_windows()
        self._update_buttons()

    # ---- state ----
    def refresh_scenes(self) -> None:
        self.scene_list.clear()
        for p in sorted(self.scenes_dir.glob("*.y*ml")):
            self.scene_list.addItem(p.name)
        self._update_buttons()

    def refresh_windows(self) -> None:
        self.window_combo.clear()
        if IS_WINDOWS:
            from capturekarma.drivers.win_input import list_window_titles
            self.window_combo.addItems(sorted(set(list_window_titles())))

    def append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _update_buttons(self) -> None:
        busy = self._busy()
        self.play_btn.setEnabled(self.scene_list.currentRow() >= 0 and not busy)
        self.record_web_btn.setEnabled(not busy)
        self.record_desktop_btn.setEnabled(not busy)

    def _run(self, fn) -> None:
        self._worker = Worker(fn)
        self._worker.log.connect(self.append_log)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._update_buttons)
        self._worker.start()
        self._update_buttons()

    def _on_done(self, result) -> None:
        self.append_log(f"done: {result}")
        self.refresh_scenes()

    def _on_failed(self, message: str) -> None:
        self.append_log(f"ERROR: {message}")

    # ---- actions ----
    def _choose_scenes_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Scenes folder", str(self.scenes_dir))
        if d:
            self.scenes_dir = Path(d)
            self.refresh_scenes()

    def _selected_scene(self) -> Path | None:
        item = self.scene_list.currentItem()
        return self.scenes_dir / item.text() if item else None

    def _play(self) -> None:
        path = self._selected_scene()
        if not path:
            return
        visible = self.show_cursor_cb.isChecked()
        style = self.style_combo.currentText()
        from capturekarma.recorder.hotkey import StopHotkey

        def job():
            scene = load_scene(path)
            hotkey = StopHotkey()
            hotkey.start()
            try:
                return Player(scene, PlayOptions(cursor_visible=visible, cursor_style=style),
                              stop_event=hotkey.triggered).run()
            finally:
                hotkey.stop()

        self.append_log(f"playing {path.name} …")
        self._run(job)

    def _record_web(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self.append_log("enter a URL first")
            return
        out = self.scenes_dir / f"web-{len(list(self.scenes_dir.glob('*.yaml'))) + 1}.yaml"
        self.append_log(f"recording {url} → {out.name}; press F9 or close the browser to stop")
        self._run(lambda: record_web(url, out))

    def _record_desktop(self) -> None:
        title = self.window_combo.currentText().strip()
        if not title:
            self.append_log("pick a window first")
            return
        out = self.scenes_dir / f"desktop-{len(list(self.scenes_dir.glob('*.yaml'))) + 1}.yaml"
        self.append_log(f"recording window {title!r} → {out.name}; press F9 to stop")
        self._run(lambda: record_desktop(title, out))

    def _open_output(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if IS_WINDOWS:
            os.startfile(self.output_dir)  # type: ignore[attr-defined]
        else:
            self.append_log(str(self.output_dir))
```

- [ ] **Step 5: Write `capturekarma/gui/app.py`**

```python
from __future__ import annotations

import sys
from pathlib import Path

from capturekarma._win import set_dpi_awareness


def main() -> None:
    set_dpi_awareness()
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    scenes_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("~/Videos/CaptureKarma/scenes").expanduser()
    win = MainWindow(scenes_dir=scenes_dir)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Add script entry** in `pyproject.toml` `[project.scripts]`: `ck-gui = "capturekarma.gui.app:main"`, then `uv sync`.

- [ ] **Step 7: Run tests and smoke the GUI**

Run: `uv run pytest tests/test_gui.py -q` → pass. `uv run ck-gui examples` → window opens listing the two example scenes; select `web-demo.yaml`, Play → log shows steps, MP4 saved; buttons disabled while busy, re-enabled after.

- [ ] **Step 8: Commit**

```bash
git add capturekarma/gui pyproject.toml uv.lock tests/test_gui.py
git commit -m "feat(gui): thin PySide6 window over the library"
```

---

## Self-review notes (orchestrator)

- Spec coverage: §3.1 run flow → Task 11; §3.2 coordinates → Tasks 1, 6, 7; §3.3 protocol → Task 6; §3.4 motion → Task 3; §3.5 overlay → Task 5; §3.6 capture → Task 4; §3.7 scene → Task 2; §3.8 recorder → Tasks 8–10; §3.9 errors/abort → Tasks 11, 12; §3.10 CLI → Task 12; §3.11 GUI → Task 14; §4 testing → per task + Task 12 E2E; §5 migration → Tasks 1, 13.
- Known deviation to watch: NVENC direct from `ddagrab` d3d11 frames (Task 4 step 7 has the fallback instruction).
- Type consistency: `Driver.smooth_scroll(step, duration, easing)` is used identically in Tasks 6, 7, 11; `StepTarget(selector, at)` throughout; `Region(x, y, width, height)` throughout; `RunResult` fields match the CLI in Task 12 and the test in Task 11.
