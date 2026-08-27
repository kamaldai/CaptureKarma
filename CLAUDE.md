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

## Gotchas

- Call `set_dpi_awareness()` before creating any window or enumerating monitors, or coordinates will be logical px.
- ddagrab `output_idx` is assumed to equal `EnumDisplayMonitors` order (single GPU). `--gdigrab` is the escape hatch;
  rotated/portrait monitors fall back to gdigrab automatically because ddagrab cannot capture them.
- Playwright's virtual mouse never moves the OS cursor; the overlay is the only cursor in web recordings.
- `WebDriver.setup` resizes the browser window so `innerWidth/Height` equals the scene viewport; the capture region is
  the viewport only (no browser chrome).
- Overlay window is `WS_EX_TRANSPARENT` (click-through) and updated with `UpdateLayeredWindow`; it must stay in the
  capture (ddagrab composites it), while `draw_mouse=0` keeps the real cursor out.
- `smooth()` is pure — test recorder behaviour there, not through pynput/Playwright.
- The bundled `imageio-ffmpeg` binary has `ddagrab`, `h264_nvenc` and `libx264` but **no `ffprobe`**; only the
  Windows end-to-end test needs ffprobe, so it must skip when it is absent.
- Both recorders log Ctrl/Alt/Win + key as plain typing; shortcuts have to be hand-edited into `press: Control+a`
  steps. Say so in docs rather than pretending it works.

## Working agreement

The main Claude session orchestrates (design, plan, review, integrate). Implementation tasks are dispatched to
Opus subagents (`model: "opus"`), one task at a time, each reviewed before the next.
