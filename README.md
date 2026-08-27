# CaptureKarma

Record a product demo once. Replay it with cinematic cursor and scroll motion. Capture to MP4.
Every take identical.

## The Story Behind CaptureKarma

I developed CaptureKarma as a hobby project while working at Paracosma. Our marketing team frequently needed to create product videos and demonstrations, but achieving perfectly smooth scrolling manually was challenging and often produced inconsistent results.

As a perfectionist, I found myself frustrated with the small imperfections in these marketing materials. The jerky movements and inconsistent speeds when scrolling manually through product pages or demonstrations didn't reflect the quality of our work. This tool was born from my desire to solve this problem once and for all - creating a utility that could produce pixel-perfect scrolling captures every time.

## What changed in v2

v1 recorded the screen while sending mouse-wheel events. v2 separates **what** happens from **how it looks**:

1. `ck record` watches you perform the flow once and writes a small YAML **scene file**.
2. `ck play` replays that scene with eased cursor paths, pixel-deterministic scrolling and a rendered cursor
   (with click ripples), while ffmpeg captures the region at 60 fps to H.264 MP4.

Because the scene file is plain YAML, you can fix a typo, retime a scroll or drop a step and re-render — no
re-recording, and the result is repeatable (there is no runtime randomness in the motion).

Web targets (Chromium via Playwright) are first-class; desktop windows are supported with best-effort scrolling.

## For the marketing team (no install)

There is nothing to install — no Python, no ffmpeg, no browser download.

1. Download `CaptureKarma-<version>-win64.zip` from the [Releases page](https://github.com/kamaldai/CaptureKarma/releases).
2. Unzip it anywhere (Desktop is fine). Keep `CaptureKarma.exe` and the `_internal` folder together.
3. Double-click **CaptureKarma.exe**.
4. **Record web** → paste your URL → perform the demo in the browser that opens → press **F9** to stop.
   Then select the scene in the list → **Play selected**, and the MP4 lands in `Videos\CaptureKarma`.
   **F9** aborts a take.

`examples\web-demo.yaml` in the unzipped folder is a ready-made scene to try first. `ck.exe` beside it is the
same tool on the command line. See `START-HERE.txt` for the short version.

## For developers

    uv sync
    uv run playwright install chromium
    uv run ck doctor

ffmpeg is bundled through `imageio-ffmpeg` — that build includes `ddagrab` (GPU desktop capture), `h264_nvenc`
and `libx264`, so there is nothing to install by hand. A real `ffmpeg` on your `PATH` is used in preference to
the bundled one. `ck doctor` reports what it found and how to fix anything that is missing.

## Usage

    uv run ck record web https://your.app/pricing -o pricing.yaml    # perform the demo, press F9 to stop
    uv run ck play pricing.yaml                                      # MP4 lands in ~/Videos/CaptureKarma

    uv run ck record desktop --window "Notepad" -o notepad.yaml      # window title, substring match
    uv run ck play notepad.yaml --no-cursor

`ck record web` also takes `--viewport WxH` (browser viewport, default `1920x1080`) and `--name NAME` (the scene
name, and so the video's filename stem); `ck record desktop` takes `--name NAME`.

`ck play` options:

| Option | Effect |
| --- | --- |
| `--out-dir DIR` | Write the video somewhere other than the scene's `output.dir`. |
| `--no-cursor` | Do not draw the cursor overlay for this run (the scene file is not modified). |
| `--cursor-style STYLE` | Override `cursor.style`. `default` is the built-in arrow; any PNG dropped in `capturekarma/cursor/assets/` becomes a style of the same name. |
| `--gdigrab` | Force the `gdigrab` capture path instead of `ddagrab`. |

Press **F9** or **Esc** during playback to abort. ffmpeg is still finalized cleanly and the footage recorded so
far is kept as `<name>_<timestamp>.partial.mp4`.

## GUI

    uv run ck-gui [scenes-folder]

Opens a window listing the scene files in that folder (default `~/Videos/CaptureKarma/scenes`), with
**Record web** / **Record desktop** / **Play selected** / **Open output folder** buttons and a log panel.
A *Hide cursor* checkbox and a cursor-style dropdown override the selected scene for that run only; both
leave the scene's own settings alone unless you change them.
**F9** stops a recording or aborts playback, exactly as it does on the command line.

## Scene files

A scene is one YAML file per demo. `target` says what to drive, `output` / `cursor` / `defaults` say how it
should look, and `steps` is the script. Each step is a mapping with exactly one key — the step type.

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
  - drag: {path: [[900, 500], [1100, 560], [1250, 500]]}   # orbit a 3D viewer: press, follow, release
  - wheel: {by: -240, at: [1080, 540]}        # mouse wheel without scrolling the page (canvas zoom)
  - scroll: {by: 900, duration: 2.5}          # web: optional {in: "#main"}
  - type: {text: "hello@example.com", delay: 0.06}
  - press: Enter
  - cursor: hidden
  - move: {to: [640, 400], duration: 1.2}
  - cursor: visible
  - wait: 1.5
```

### Step types

| Step | Value | Web target | Desktop target | Overrides |
| --- | --- | --- | --- | --- |
| `wait` | `wait: 1.5` — seconds to hold still. Long form `{seconds: 1.5}`. | — | — | `hold` (`duration` / `easing` do not apply) |
| `move` | `{to: <target>}` — glide the cursor there along an eased Bezier path. | `to` is a Playwright selector (`"text=Pricing"`, `"#buy"`, `"[data-testid=cta]"`) or `[x, y]` in **viewport CSS px**. | `to` must be `[x, y]` **relative to the capture region's top-left**. Selectors are rejected. | `duration`, `easing`, `hold` |
| `click` | `{}` clicks where the cursor already is; `{to: <target>}` moves there first, then clicks. `{button: left / right / middle}`, default `left`. | same as `move` | same as `move` | `duration`, `easing`, `hold` (`duration` / `easing` shape the implied move) |
| `drag` | `{path: [[x, y], [x, y], ...]}` — press at `path[0]`, follow the polyline, release at `path[-1]`. At least two points. `{button: left / right / middle}`, default `left`. | points are **viewport CSS px** (no selectors — a drag is a gesture, not an element). | points are **relative to the capture region's top-left**. | `duration`, `easing`, `hold` |
| `scroll` | `{by: 900}` — pixels, positive = down. Web only: `{to: 0}` scrolls to an absolute offset and `{in: "#main"}` scrolls that container instead of the page. Exactly one of `by` / `to`. | Animated in-page (`scrollTop` under `requestAnimationFrame`) — lands exactly on the target pixel. | Wheel deltas emitted per tick along the easing curve, with fractional carry-over. `to:` and `in:` are rejected. | `duration`, `easing`, `hold` |
| `wheel` | `{by: -240}` — mouse-wheel pixels, positive = wheel down. Optional `{at: <target>}` moves the cursor there first. Unlike `scroll` this only emits wheel input: use it to zoom a canvas / 3D viewer, which does not scroll the page. | `at` is a selector or `[x, y]`; the wheel is dispatched at the cursor. | `at` must be `[x, y]`. Wheel notches via `SendInput` at the cursor. | `duration`, `easing`, `hold` |
| `type` | `{text: "hello@example.com", delay: 0.06}` — types into whatever has focus. `delay` is the per-key pause, default `0.05`. | keyboard events via Playwright | `SendInput` keystrokes | `hold` (`delay` sets the typing speed) |
| `press` | `press: Enter` — one key by name. Long form `{key: Tab}`. Combinations use `+`: `press: Control+a`. | Playwright key names | Win32 virtual keys | `hold` |
| `cursor` | `cursor: hidden` or `cursor: visible` — toggle the drawn cursor mid-scene. Instant. | — | — | none — no mapping form, no `hold` |

**Timing.** `duration` is how long the motion itself takes; `hold` is the pause *after* the step and defaults to
`defaults.hold`. Omit `duration` and it is derived: a `move` from the distance and `cursor.speed`
(`clamp(distance / speed, 0.35, 2.0)` seconds), a `drag` from its total path length
(`clamp(length / speed * 1.5, 0.6, 6.0)`), a `scroll` or a `wheel` from its length. `easing` is one of `linear`,
`ease_in_out_cubic` (the default), `ease_out_cubic`, `ease_in_out_quint`.

**Validation is strict and happens before anything launches**: unknown keys, a selector in a desktop scene,
`scroll in:` in a desktop scene, a negative duration or a capture region spanning two monitors all fail
immediately, quoting the step number.

## Output

Everything lands in `output.dir` (default `~/Videos/CaptureKarma`, override with `--out-dir`) and nothing is
ever overwritten — names are timestamped.

| File | What it is |
| --- | --- |
| `<name>_<timestamp>.mp4` | The video: H.264, native resolution of the capture region, 60 fps, `+faststart`. NVENC when available, `libx264` otherwise. |
| `<name>_<timestamp>.cursor.json` | Per-tick cursor timeline (position, visibility, clicks) for later post-processing. |
| `<name>_<timestamp>.partial.mp4` | Written instead of the `.mp4` when you abort with F9 / Esc. |
| `<name>_<timestamp>.error.png` | Screenshot taken when a step fails — selector not found, and so on. |
| `capturekarma.log` | Rolling log of every GUI session (1 MB × 3). Written by `ck-gui` only; the CLI logs to the console. |

For web scenes the video contains the viewport only: no browser chrome, and no OS cursor (the real cursor is
excluded with `draw_mouse=0` — the one you see is the rendered overlay).

## Limitations

- **Windows 10/11 only.** Capture uses `ddagrab` / `gdigrab` and input uses Win32.
- **Keyboard shortcuts are not recorded as shortcuts.** Both recorders currently log Ctrl / Alt / Win + key as
  plain typing. Edit the scene afterwards and replace those steps with `press: Control+a` style steps.
- **Desktop scrolling is best-effort.** It is wheel-event emulation, so how smooth it looks is up to the target
  app's own scroll animation. Web scrolling is exact — prefer a web scene when you have the choice.
- **Web element targets must be on screen** when they are used; add a `scroll` step first (the recorder does
  this for you). A `move` / `click` waits up to 15 s for its element to become visible, so a
  single-page app that paints late still works; after that the step fails with
  `element not found or not visible within 15s`.
- **Long pauses are shortened to 2 s, except the first one.** The gap between recording start and
  your first action is the app's load time, so it is kept (up to 30 s) — a 3D viewer can still be
  downloading its model ten seconds in. Every later pause collapses to 2 s; stretch one back out by
  editing its `wait` step.
- **Rotated / portrait monitors fall back to `gdigrab`** automatically, because `ddagrab` cannot capture them.
  `--gdigrab` forces the same path anywhere else.
- **Recording watches your keyboard.** Desktop recording installs a system-wide keyboard hook while it is
  active; keystrokes are only recorded while the target window is in the foreground, but the hook itself sees
  everything until you press F9. Web recording skips `input[type=password]` fields entirely. Scene files are
  plain-text YAML with every keystroke you typed in them — read one before you share it.
- **A press is a drag only once it travels.** Both recorders call a press a `drag` when the pointer
  travelled at least 6 px along its path, or when the press lasted 300 ms *and* ended at least 3 px
  from where it started; anything less stays a `click`. A very slow, very small orbit of a 3D viewer
  can therefore land on the wrong side of that line — check the recorded step and widen the path by
  hand if it did.
- **`wheel` vs `scroll` is decided by whether the page moved.** The web recorder writes a `wheel`
  step when a burst of wheel events produced no `scroll` event anywhere (a canvas that zooms and
  calls `preventDefault`), and a `scroll` step otherwise. Desktop recording cannot tell the two
  apart at all and always writes a `scroll`; hand-edit it to `wheel` for a desktop 3D viewer.
- **Text selectors are recorded only when they are unambiguous.** `button:has-text("Save")` is a
  case-insensitive *substring* match on normalised text, so a "Save" next to a "Save all" gets a
  structural `body > ... > button:nth-of-type(2)` selector instead. Those break when the page
  changes; give the element an `id` or a `data-testid` if you plan to keep the scene.
- **An inner scroll container with no unique selector is recorded as a page scroll.** If the recorder cannot
  name the element you scrolled, the step is written as a page scroll; add an `id` to the container or
  hand-edit the step's `in:` selector.
- **MP4 (H.264) is the only output.** No WebM or GIF, and no auto-zoom, device frames or captions — the
  `.cursor.json` timeline exists so those can be added later as a post-pass.
- **The command-line entry point is `ck`.**

## Troubleshooting

The GUI writes everything it logs to `~/Videos/CaptureKarma/capturekarma.log` (1 MB, three
generations), so a run that failed yesterday can still be diagnosed today: it has the step numbers,
the selector that could not be found, the capture command line and the measured viewport. When a
take fails, the log panel shows `StepError: step 12: element not found: ...` — the same line is in
the file. Open the scene file, count to that step, and fix or delete it.

## Development

    uv run pytest -q                                  # pure tests: no desktop, no browser
    uv run pytest -q -m "win32 or integration"        # the desktop/browser tests, needs a desktop + Chromium

Run both commands for the full set: the default run deselects everything marked `win32` or `integration`,
and the second command selects exactly those.

The Windows-only tests check the finished MP4's resolution, frame rate and pixel format. `ffprobe` is *not*
part of the bundled `imageio-ffmpeg` build, so those checks read the stream layout from `ffmpeg -i` instead;
nothing needs to be installed. If a real `ffprobe` is on your `PATH` it is used in preference, which also
enables the end-to-end test's container-duration comparison.

To build the self-contained bundle the marketing team downloads:

    pwsh -File packaging/build_windows.ps1

That installs Chromium *into* the `playwright` package (`PLAYWRIGHT_BROWSERS_PATH=0`), runs PyInstaller over
`packaging/CaptureKarma.spec`, and writes `dist/CaptureKarma/` plus `dist/CaptureKarma-<version>-win64.zip`.
Expect ~700 MB unpacked: Chromium and Qt dominate. `capturekarma/_frozen.py` is what makes the frozen app find
the bundled Chromium and ffmpeg; `ck doctor` prints a `bundle` line saying which build it is running from.

See `CLAUDE.md` for the package layout and the conventions that keep the code honest: physical pixels
everywhere, dumb drivers, no swallowed exceptions.

## License

["Don't Be A Dick" Public License](LICENSE) — do whatever you want with the code, just don't be a dick about it.
