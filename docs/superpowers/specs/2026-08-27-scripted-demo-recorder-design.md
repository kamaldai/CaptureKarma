# CaptureKarma v2 — Scripted Demo Recorder: Design

Date: 2026-08-27
Status: Approved (design walked through in chat, sections 1–6 accepted)

## 1. Problem and goal

The marketing team needs product demo videos with perfectly smooth scrolling and
cursor movement. CaptureKarma v1 tried to do this by sending mouse-wheel events
during a screen recording. That approach is fundamentally unreliable: wheel
deltas are quantized (120 units per notch), every application applies its own
scroll animation, timing drifts, and the recording contains no cursor at all.

v2 replaces "record while a human scrolls" with **record what the human does,
then replay it cinematically**:

1. A **recorder** watches marketing perform the flow once (clicks, scrolls,
   typing) and writes a **scene file** (YAML).
2. A **player** replays the scene with deterministic, eased motion, drawing a
   rendered cursor, while ffmpeg captures the region to H.264 MP4.

Every take is identical and the scene file is hand-editable.

## 2. Scope

### In scope (v1 of the new tool)

- Web targets (Chromium via Playwright) — primary.
- Desktop targets (arbitrary Windows window/region via Win32 input) — secondary,
  best-effort scrolling.
- Recorder for both target kinds, with a smoothing pass.
- Player with eased cursor paths, eased scrolling, rendered cursor overlay with
  click ripple, per-step cursor show/hide.
- Capture to MP4 (H.264), native resolution of the capture region, 60 fps, to a
  folder.
- CLI (`ck`) and a thin PySide6 GUI wrapping the same library.
- `ck doctor` environment check.
- Windows 10/11 only.

### Out of scope (deferred, design keeps the door open)

- Auto-zoom, device frames/padding, captions — post-processing effects. The
  player writes a cursor timeline side-file so these can be added later as a
  post pass without re-recording.
- WebM/GIF output, resize presets.
- macOS/Linux.
- Packaging (PyInstaller) — updated later.
- Visual scene editor.

## 3. Architecture

Plain Python library + CLI; GUI is a thin shell.

```
capturekarma/
  scene/      dataclasses + YAML load/save/validate
  drivers/    Driver protocol; WebDriver (Playwright/Chromium), DesktopDriver (Win32)
  motion/     easing curves, Bezier cursor paths, drift-corrected 120 Hz ticker
  cursor/     overlay window (Win32 layered, click-through, topmost) + sprite/ripple
  capture/    ffmpeg process mgmt (ddagrab -> H.264), region -> args, handshake
  recorder/   WebRecorder, DesktopRecorder, smoothing pass (events -> steps)
  player/     orchestrates a run: setup -> capture -> drive steps -> finalize
  cli.py      ck record | play | doctor
  gui/        PySide6 window (built last)
```

### 3.1 A `play` run

1. Load and validate the scene (fail before anything launches).
2. `driver.setup(scene)`:
   - web: launch headed Chromium at a fixed window position/size, navigate to
     `target.url`, wait for load. Returns the **viewport rectangle in physical
     screen pixels** — the video contains no browser chrome.
   - desktop: find the window by title substring (or use `target.region`),
     bring it to the foreground. Returns its client rectangle in physical px.
3. Start the cursor overlay thread and the ffmpeg capture process. Wait until
   ffmpeg reports its first encoded frame.
4. Hold `lead_in` seconds. Execute steps in order. Hold `lead_out` seconds.
5. Send `q` to ffmpeg for a clean finalize; wait for exit. Write
   `<name>_<timestamp>.mp4` and `<name>_<timestamp>.cursor.json`. Teardown the
   driver and overlay.

### 3.2 Coordinates

- All coordinates handled by the player, overlay, capture, and desktop driver
  are **physical screen pixels**.
- The process declares per-monitor-v2 DPI awareness at startup
  (`SetProcessDpiAwarenessContext`) so Win32 APIs return physical px.
- The web driver maps viewport CSS px -> physical screen px using
  `window.screenX/screenY`, chrome height (`outerHeight - innerHeight`), and
  `devicePixelRatio`, measured once after setup and re-measured after
  navigation.
- Scene desktop targets are **relative to the capture region's top-left**, so a
  recording survives the window being moved (same size).
- Scene web targets are Playwright selectors, with optional `at: [x, y]`
  viewport CSS px fallback.

### 3.3 Driver protocol

Drivers are deliberately dumb. The player owns motion.

```python
class Driver(Protocol):
    def setup(self, scene: Scene) -> Region: ...          # physical px
    def resolve(self, target: Target) -> Point: ...       # physical px
    def pointer_to(self, x: int, y: int) -> None: ...     # called per tick
    def mouse_down(self) -> None: ...
    def mouse_up(self) -> None: ...
    def smooth_scroll(self, step: ScrollStep, easing: Easing) -> None: ...
    def type_text(self, text: str, delay: float) -> None: ...
    def press(self, key: str) -> None: ...
    def screenshot(self, path: Path) -> None: ...         # for error reports
    def teardown(self) -> None: ...
```

- **WebDriver**: `pointer_to` -> `page.mouse.move` (viewport CSS px, converted
  back from physical). `smooth_scroll` injects a single JS function that
  animates `scrollTop` of the target container (default: document scrolling
  element) with `requestAnimationFrame` and the chosen easing over `duration`,
  and awaits its completion promise — pixel-deterministic. `resolve` uses
  `locator.bounding_box()` center (or `at`).
- **DesktopDriver**: `pointer_to` -> `SetCursorPos`; clicks/keys via
  `SendInput`; `smooth_scroll` emits wheel deltas each tick following the
  easing derivative, quantized to integers with fractional carry-over.
  Documented as best-effort (target app decides how to animate).

### 3.4 Motion

- Easing functions: `linear`, `ease_in_out_cubic` (default), `ease_out_cubic`,
  `ease_in_out_quint`. Pure functions `[0,1] -> [0,1]`.
- Cursor path: cubic Bezier from current to target. Control points are offset
  perpendicular to the chord by a fraction of its length; the sign alternates
  by step index. **No runtime randomness** — a scene renders identically every
  run.
- Move duration when unspecified: `clamp(distance / cursor.speed, 0.35, 2.0)`
  seconds.
- Ticker: 120 Hz, `time.perf_counter`, `sleep_until(next)`, with
  `timeBeginPeriod(1)` while running. A late tick catches up (next deadline is
  computed from the start time, not from "now").
- Each tick the player calls `driver.pointer_to(x, y)` and
  `overlay.set_position(x, y)` together so the drawn cursor and real hover
  state stay in lockstep. Every tick is appended to the cursor timeline.

### 3.5 Cursor overlay

- Win32 layered window: `WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST |
  WS_EX_TOOLWINDOW`, no taskbar entry, click-through. Updated with
  `UpdateLayeredWindow` and a premultiplied BGRA bitmap.
- Runs on its own thread with a Win32 message loop; the player posts position /
  visibility / click events via a thread-safe queue.
- Bitmap is ~160x160 px: cursor sprite (PNG, `style` selects the file) plus
  ripple ring(s). A ripple is an expanding, fading circle over 400 ms spawned
  on `mouse_down`.
- Visibility: `ShowWindow(SW_SHOW/SW_HIDE)`. Scene `cursor.visible` sets the
  initial state; `cursor: hidden|visible` steps toggle it.
- ffmpeg captures with `draw_mouse=0`, so the real OS cursor is never in the
  video regardless of driver kind.

### 3.6 Capture

- ffmpeg located on `PATH`, else `imageio_ffmpeg.get_ffmpeg_exe()`.
- Preferred input: `-f lavfi -i ddagrab=output_idx=<monitor>:offset_x=..:offset_y=..:video_size=WxH:framerate=<fps>:draw_mouse=0`.
  Encoder: `h264_nvenc` when available (`-preset p4 -cq 19`), else
  `hwdownload,format=bgra` + `libx264 -preset veryfast -crf 18`. Pixel format
  `yuv420p`, `-movflags +faststart`. Even dimensions enforced by trimming 1 px.
- Fallback input when ddagrab is unavailable: `-f gdigrab -draw_mouse 0
  -offset_x .. -offset_y .. -video_size WxH -framerate <fps> -i desktop`, with a
  warning.
- Readiness: parse stderr for the first `frame=` progress line.
- Stop: write `q` to stdin, wait up to 10 s, then terminate.
- Region must lie within a single monitor; validation error otherwise.

### 3.7 Scene format

YAML, one file per demo. Each step is a single-key mapping; the key is the
step type. `duration`, `easing`, `hold` may override defaults per step.

```yaml
version: 1
name: pricing-page-demo
target:
  kind: web                      # web | desktop
  url: https://app.example.com/pricing
  viewport: [1920, 1080]
  # desktop alternative:
  # window: "PowerView"          # substring match on title
  # region: [x, y, w, h]         # or explicit physical px
output:
  fps: 60
  dir: ~/Videos/CaptureKarma
  lead_in: 0.5
  lead_out: 0.5
cursor:
  visible: true
  style: default
  ripple: true
  speed: 1400                    # px/s nominal
defaults:
  easing: ease_in_out_cubic
  hold: 0.6                      # pause after each step
steps:
  - wait: 1.0
  - move: {to: "text=Pricing"}   # web: selector; desktop: [x, y] region-relative
  - click: {}                    # at current pointer, or {to: ...} to move+click
  - scroll: {by: 900, duration: 2.5}          # web: optional {in: "#main"}
  - type: {text: "hello@example.com", delay: 0.06}
  - press: Enter
  - cursor: hidden
  - move: {to: [640, 400], duration: 1.2}
  - cursor: visible
  - wait: 1.5
```

Step types: `wait`, `move`, `click`, `scroll`, `type`, `press`, `cursor`.
Scroll accepts `by: <px>` (positive = down) or `to: <px offset>`.

Validation is strict: unknown keys, missing/ambiguous targets, `scroll in:` on
a desktop scene, negative durations, or a region outside one monitor all fail
with the step index before anything launches.

### 3.8 Recorder

Both recorders emit raw timestamped events into a common `RawEvent` list; a
pure function `smooth(events, config) -> list[Step]` produces scene steps.

**WebRecorder** (`ck record web <url> -o scene.yaml`): headed Chromium via
Playwright with an init script installing capture-phase listeners for `click`,
`scroll` (throttled; reports which element scrolled), `input`, `keydown`, and
an exposed binding `__ck_event(payload)`. Navigation from `framenavigated`.
Selector generation order: `data-testid` -> `id` -> ARIA role+name -> visible
text -> CSS path; uniqueness verified with `querySelectorAll(sel).length === 1`,
otherwise `at: [x, y]` is emitted. Stop with F9 or closing the browser.

**DesktopRecorder** (`ck record desktop --window "Title" -o scene.yaml`):
`pynput` global listeners for clicks (region-relative), scroll deltas, keys.
Stop with F9.

**Smoothing pass:**
- scroll events within 300 ms merge into one `scroll` step;
- printable keystrokes group into one `type` step, special keys -> `press`;
- a `move` is inserted before every click, targeting the click target, with no
  duration (player derives from distance);
- gaps become `wait` steps capped at `max_wait` (default 2.0 s);
- cursor position samples are never recorded — motion is regenerated.

The written scene file has a `# recorded from <url|window> on <date>` header.

### 3.9 Player: timing, abort, errors

- Abort on ESC or F9 (global hotkey) or Ctrl+C: stop ffmpeg cleanly, keep the
  partial video as `<name>_<timestamp>.partial.mp4`.
- Selector not found -> `StepError(step_index, message)` plus
  `<name>_<timestamp>.error.png` screenshot.
- Window not found -> error listing visible window titles.
- ffmpeg exits early -> error with stderr tail.
- No exception is swallowed; the CLI prints a one-line error and exits 1, the
  GUI shows it in the log panel.
- Outputs are timestamped; nothing is overwritten.

### 3.10 CLI

```
ck record web <url> [-o scene.yaml] [--viewport WxH]
ck record desktop --window <title> [-o scene.yaml]
ck play scene.yaml [--out-dir DIR] [--no-cursor]
ck doctor
```

`ck doctor` checks: ffmpeg found and version; ddagrab available; NVENC
available; Playwright Chromium installed; DPI awareness set; prints fixes.

### 3.11 GUI

PySide6, one window, thin. Scenes list from a chosen folder; **Record Web**
(URL field), **Record Desktop** (window picker); **Play** selected scene;
**Open Output Folder**; global **Show cursor** checkbox and cursor style
dropdown (override scene defaults for this run); log panel. Long-running work
runs on a worker thread and reports via Qt signals — no widget is touched from
a worker thread. Every action calls the same library functions as the CLI.

## 4. Testing

- **Unit (pytest, all platforms):** scene parse/validate incl. invalid
  fixtures; easing endpoints/monotonicity; Bezier path start/end/tick count;
  move-duration clamp; smoothing pass golden tests; ffmpeg argument builder;
  coordinate mapping math.
- **Web integration (headless Playwright, local fixture HTML under
  `tests/fixtures/`):** selector generator uniqueness; recorder captures a
  scripted click/scroll/type; in-page scroll animation ends exactly at target.
- **Windows-only integration (marked `win32`, skipped elsewhere):** overlay
  renders a non-transparent pixel at the set position (verified with a screen
  grab); end-to-end `ck play` on the fixture page served by `http.server` ->
  MP4 exists, `ffprobe` duration within ±0.3 s, fps = 60.
- TDD per task; orchestrator reviews each task before the next starts.

## 5. Repo migration

- New package `capturekarma/` replaces `CaptureKarma/`. Delete
  `marketing_screen_capture.py`, the PyQt5 UI, and the pyautogui/OpenCV/mss
  stack.
- `pyproject.toml` (uv, Python 3.12). Runtime deps: `playwright`, `pynput`,
  `pywin32`, `Pillow`, `numpy`, `PyYAML`, `typer`, `PySide6`, `imageio-ffmpeg`.
  Dev: `pytest`, `pytest-playwright`. Script entry point `ck`.
- `examples/`: a web scene against the bundled fixture page and a desktop
  scene against Notepad.
- `CLAUDE.md`: layout, commands, conventions (physical px everywhere, drivers
  stay dumb, no swallowed exceptions), orchestration rule (Opus implementers).
- README rewritten; keep the "story" section.
