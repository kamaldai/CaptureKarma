# CaptureKarma v2 — final pre-merge fix wave

Branch `v2-scripted-demo-recorder`, base `a24d4fd`. All eight fixes (A–H) landed in one commit, TDD:
each fix got its test(s) first, then the implementation, then a focused run.

Baseline before the wave: `uv run pytest -q` → **149 passed, 2 skipped** (it ran *everything*, including
the desktop and browser tests, because `addopts` did not gate them).

Final: **183 passed, 28 deselected** (pure) and **26 passed, 2 skipped, 183 deselected** (win32 +
integration). 60 tests added.

---

## A. CRITICAL — DPI awareness in desktop recording

**Problem.** `record_desktop()` never declared DPI awareness, so on a scaled display Win32 handed it
*logical* pixels while the player and the GUI (which do call `set_dpi_awareness()`) work in physical
pixels. The CLI and the GUI therefore recorded different coordinates for the same window.

**Change.** `capturekarma/recorder/desktop.py`
- `from capturekarma._win import set_dpi_awareness`
- `record_desktop()` calls `set_dpi_awareness()` as its first statement, before `find_window`,
  `focus_window`, `window_client_region` and before the pynput hooks start.

**Tests** (`tests/test_desktop_recorder.py`, pure):
- `test_record_desktop_sets_dpi_awareness_before_looking_up_the_window` — monkeypatches
  `desktop_mod.set_dpi_awareness`, `win_input.find_window/focus_window/window_client_region`,
  `DesktopRecorder.start/stop` and `desktop_mod.StopHotkey` (a fake whose `triggered` event is
  pre-set) so `record_desktop` runs headlessly, appending to a shared `calls` list. Asserts
  `calls.index("set_dpi_awareness") < calls.index("find_window")` and the same for
  `window_client_region` and `start`. It also asserts the scene file was actually written.

---

## B. IMPORTANT — no raw tracebacks from `ck`

### B1 — CLI catch-all + stderr

`capturekarma/cli.py`
- `_fail()` now prints with `err=True` (was `err=False`, i.e. stdout).
- Added `log = logging.getLogger("capturekarma.cli")`.
- Each of `record web`, `record desktop` and `play` gained, after its `except _ERRORS` clause:

```python
except Exception as exc:  # noqa: BLE001 - a CLI must not spray tracebacks; -v shows the full one
    log.debug("unexpected error", exc_info=True)
    _fail(exc)
```

`_fail` raises `typer.Exit(1)` from inside an `except` block, so the sibling `except Exception`
cannot re-catch it. `KeyboardInterrupt` is a `BaseException` and still propagates from `play`.

**Verified:** typer 0.27.1 vendors click as `typer._click`; its `CliRunner` uses a `StreamMixer`, so
`result.output` contains stdout+stderr interleaved *and* `result.stdout` / `result.stderr` are
separately available. Both forms are asserted, so the existing `"error:" in r.output` tests keep
passing while `test_errors_go_to_stderr` proves the message no longer goes to stdout.

**Tests** (`tests/test_cli.py`, pure): `test_unexpected_error_is_reported_without_a_traceback`
(`record_web` raises `RuntimeError`), `test_unexpected_error_in_record_desktop_is_reported`
(`OSError`), `test_unexpected_error_in_play_is_reported` (`Player.run` raises `RuntimeError`),
`test_errors_go_to_stderr` (`"error:" in r.stderr` and `"error:" not in r.stdout`).

### B2 — driver failures become `StepError` at the raise site

`capturekarma/drivers/web.py::WebDriver.resolve` — the `locator(...).count()` / `bounding_box()`
pair is wrapped; a `playwright.sync_api.Error` becomes
`StepError(f"invalid or failing selector {sel!r}: {exc}")`.

`capturekarma/drivers/desktop.py::DesktopDriver.press` — a `ValueError` out of `parse_key` becomes
`StepError(f"cannot press {key!r}: {exc}")`.

**Tests:** `tests/test_web_driver.py::test_malformed_selector_raises_step_error_not_a_playwright_error`
(integration, selector `"#btn-primary >>> :::"`);
`tests/test_desktop_driver.py::test_press_reports_an_unknown_key_as_a_step_error` (pure — a
`FakeInput` subclass whose `press_key` runs the *real* `parse_key` without touching `SendInput`,
so the ValueError is genuine; also checks a good key still goes through).

### B3 — loader: scalar sections and unsafe names

`capturekarma/scene/loader.py`
- New `_section(data, key)` helper replaces the three `data.get(key, {}) or {}` expressions. A
  missing key or an explicit `null` still means "defaults"; anything that is not a mapping raises
  `SceneError("<section> must be a mapping")`. Previously `output: 5` reached `_require_keys`, where
  `set(5)` raised a raw `TypeError`.
- `name` is validated against `_ILLEGAL_NAME_CHARS = '/\\:*?"<>|'` plus a leading/trailing `.` or
  space → `SceneError("name contains characters not allowed in file names")`. The scene name becomes
  the video's filename stem, so this must fail at parse time and not after a long capture.

**Tests** (`tests/test_scene.py`, pure): parametrized scalar-section and list-section rejection for
all three sections, a null-section-falls-back-to-defaults case, 13 rejected names and 4 accepted
ones (`"my scene 2"`, `"v1.2 demo"` — interior dots and spaces stay legal).

---

## C. IMPORTANT — test gating

`pyproject.toml`:

```toml
# Default run is pure: no desktop, no browser. Override on the command line with
#   uv run pytest -q -m "win32 or integration"
addopts = "-ra -m 'not win32 and not integration'"
```

**Override verified** — `-m` is a single-value option, so a command-line `-m` wins over `addopts`:

```
$ uv run pytest -q --collect-only              → 183/211 tests collected (28 deselected)
$ uv run pytest -q --collect-only -m "win32 or integration"
                                               → 28/211 tests collected (183 deselected)
```

183 + 28 = 211 = the whole suite, so the two commands partition it exactly.

Docs updated in `README.md` (Development) and `CLAUDE.md` (Commands): `uv run pytest -q` is described
as the pure tests, `uv run pytest -q -m "win32 or integration"` as the desktop/browser tests, with an
explicit "run both commands for the full set" instead of claiming either is "everything". `-m ""` is
deliberately not documented.

---

## D. IMPORTANT — portable example

`capturekarma/scene/loader.py::load_scene` — when `target.kind == "web"` and the url has no scheme
(`"://" not in url` and it does not start with `about:`), it is resolved as a filesystem path
relative to the scene file's directory, required to exist (`SceneError` naming the resolved path
otherwise), and converted with `Path.resolve().as_uri()`. `parse_scene` (dict input, no file
context) leaves such urls untouched — documented in the new `load_scene` docstring.

`examples/web-demo.yaml` — `url: ../tests/fixtures/page.html` (was a hard-coded
`file:///D:/Repos/CaptureKarma/...`), header comment now explains the scene-relative rule.

**Tests** (`tests/test_scene.py`, pure): relative path resolves to the file's `file:///` URI; a
relative path may climb out of the scene directory (`../page.html`); a missing file raises
`SceneError`; `https://`, `http://`, `file:///` and `about:blank` are all untouched; `parse_scene`
leaves a relative url alone; a parametrized `test_shipped_examples_load` over every `examples/*.yaml`;
and `test_web_example_points_at_the_bundled_fixture_page`.

---

## E. IMPORTANT — privacy of key capture

### E1 — `get_foreground_window`

`capturekarma/drivers/win_input.py`, inside the `if IS_WINDOWS:` block:

```python
def get_foreground_window() -> int:
    """Handle of the window with keyboard focus; 0 when no window has it."""
    return int(user32.GetForegroundWindow() or 0)
```

Test: `tests/test_win_input.py::test_get_foreground_window_returns_a_handle` (marked `win32`).

### E2 — desktop recorder only records keys for the target window

`capturekarma/recorder/desktop.py`
- `DesktopRecorder(region, clock=..., target_hwnd: int | None = None, foreground: Callable[[], int] = _foreground_window)`,
  where the module-level `_foreground_window()` delegates to `win_input.get_foreground_window` (kept
  out of the class so non-Windows imports never touch it).
- `_target_has_focus()` returns True unconditionally when `target_hwnd is None`; `on_press` returns
  early (logging at DEBUG, never the key itself) when it is False.
- `record_desktop` passes `target_hwnd=hwnd` from `find_window`.

Clicks and scrolls are deliberately *not* gated — they are already filtered by the capture region.

**Tests** (pure, injected `foreground` callable): keys recorded while foreground == target, dropped
while it is another window, recorded again when focus returns; keys always recorded (and the
foreground callable never even called) when `target_hwnd is None`; clicks/scrolls unaffected;
`test_record_desktop_passes_the_target_window_to_the_recorder` spies on `__init__`.

### E3 — web recorder skips passwords and stop keys

`capturekarma/recorder/web_recorder.js` keydown handler:

```js
const STOP_KEYS = new Set(["F9", "Escape"]);
const isPasswordField = el =>
  !!el && el.nodeType === 1 && el.tagName === "INPUT" && String(el.type).toLowerCase() === "password";

document.addEventListener("keydown", e => {
  if (e.isComposing) return;
  if (STOP_KEYS.has(e.key)) return;          // the stop hotkeys are never part of the demo
  if (isPasswordField(e.target)) return;     // privacy: passwords never reach the scene file
  send({ kind: "key", key: e.key });
}, true);
```

`tests/fixtures/page.html` gained `<input id="pw" type="password" placeholder="password">` (and `#pw`
joined `#email` in the stylesheet rule).

**Tests** (`tests/test_web_recorder.py`, integration, headless):
`test_password_input_keystrokes_are_never_recorded` (clicks `#pw`, types `hunter2`, presses Enter —
zero key events, while the click itself is still recorded) and `test_stop_keys_are_never_recorded`
(F9 and Escape produce nothing; a following `a` still does).

### E4 — README Limitations

Two new bullets before the MP4 one:
- **Recording watches your keyboard** — the desktop hook is system-wide while active, keystrokes are
  only recorded while the target window is in the foreground, web recording skips
  `input[type=password]`, and scene files are plaintext YAML containing everything you typed: read
  one before sharing it.
- **An inner scroll container with no unique selector is recorded as a page scroll** — add an `id` or
  hand-edit the step's `in:` selector.

---

## F. IMPORTANT — `-pix_fmt yuv420p` on the ddagrab + NVENC branch

**The plain `-pix_fmt` form does not work — `-vf hwdownload,format=bgra` was required.**

First attempt (spec §3.6 read literally: append `-pix_fmt yuv420p` to the existing nvenc args) made
ddagrab fail outright. Real run on this desktop (RTX, ffmpeg 7.1 from `imageio-ffmpeg`):

```
-f lavfi -i ddagrab=... -c:v h264_nvenc -preset p4 -cq 19 -rc vbr -pix_fmt yuv420p ...

Impossible to convert between the formats supported by the filter 'Parsed_null_0'
and the filter 'auto_scale_0'
[vf#0:0] Error reinitializing filters!
[vost#0:0/h264_nvenc] Could not open encoder before EOF
→ capturekarma logged "ddagrab capture failed, falling back to gdigrab (slower)"
→ cap.use_ddagrab == False
```

`tests/test_capture_win32.py` still *passed* in that state, because the recorder silently falls back
to gdigrab — a real regression the unit test could not see. So the second form was used:

```python
args += ["-f", "lavfi", "-i", spec]
# ddagrab hands out D3D11 hardware frames. Both encoders need them downloaded first: an
# explicit -pix_fmt on hardware frames makes NVENC fail with "Impossible to convert between
# the formats supported by the filter 'Parsed_null_0' and the filter 'auto_scale_0'", and
# spec 3.6 requires yuv420p on every branch so any player can decode the result.
args += ["-vf", "hwdownload,format=bgra"]
if caps.nvenc:
    args += ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19", "-rc", "vbr"]
else:
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18"]
args += ["-pix_fmt", "yuv420p"]
```

Verified on real hardware, twice:

```
$ uv run pytest tests/test_capture_win32.py -q -m win32
1 passed, 1 skipped in 4.17s          (the skip is "ffprobe unavailable", expected)

$ <manual start_capture on the primary monitor>
use_ddagrab: True   frames: 124   bytes: 50465      # no gdigrab fallback

$ ffmpeg -i .pytest_tmp/formA.mp4
Stream #0:0: Video: h264 (Main), yuv420p(tv, ...), 640x360, 60 fps
```

`tests/test_ffmpeg_args.py::test_ddagrab_nvenc_args` now asserts `-pix_fmt yuv420p` is present and
that `-vf hwdownload,format=bgra` precedes `-c:v h264_nvenc`; the stale
`assert "hwdownload" not in joined` was removed. `test_ddagrab_libx264_downloads_frames` is unchanged
and still passes.

`tests/test_e2e_win32.py` gained `pix_fmt` to its `-show_entries` list and
`assert info["streams"][0]["pix_fmt"] == "yuv420p"`. That block still skips on this machine
(the bundled imageio-ffmpeg has no `ffprobe`), as expected.

A gotcha was added to `CLAUDE.md` so the next person does not re-derive this.

---

## G. IMPORTANT — recorder → dump → load round trip

`capturekarma/scene/loader.py::_target_out` raises
`SceneError("step target needs a selector or coordinates")` instead of dying on `list(None)` with a
`TypeError` when a `StepTarget` has neither field.

**Tests:**
- `tests/test_desktop_recorder.py::test_recorder_scene_survives_a_dump_load_round_trip` (pure) —
  clicks, a scroll, typing and an Enter through a fake clock →
  `to_scene(..., window="Notepad")` → `dump_scene` → `load_scene(tmp) == scene`.
- `...::test_recorder_scene_with_a_region_target_survives_a_round_trip` (pure) — the `window=None`
  path, which writes a `region:` target instead.
- `tests/test_web_recorder.py::test_recorded_scene_survives_a_dump_load_round_trip` (integration) —
  the recorded url is the `fixture_url` fixture, already a `file:///` URI, so the D fix leaves it
  alone and the comparison is exact.
- `tests/test_scene.py::test_step_target_without_selector_or_coordinates_raises_scene_error` and
  `::test_dump_scene_reports_an_empty_step_target_as_a_scene_error` (through the public
  `dump_scene`).

---

## H. Minor

1. `tests/test_cli.py::test_play_invokes_player_with_options` now also mocks
   `capturekarma.cli.StopHotkey`, so the unit test installs no real global keyboard hook.
2. `capturekarma/_win.py::set_dpi_awareness` — the dead `ctypes.get_last_error()` operand is gone
   (it only works with `use_last_error=True`, which `windll` does not set), leaving
   `ctypes.GetLastError() == ERROR_ACCESS_DENIED`. The shcore fallback now checks its `HRESULT`:
   `S_OK` (0) and `E_ACCESSDENIED` (`0x80070005`, "already set") → `True`; anything else is logged as
   `HRESULT 0x%08X` and returns `False`. The raw return is masked with `& 0xFFFFFFFF` because ctypes
   gives back a signed `c_int`. Sanity-checked live: returns `True` on first and second call.
3. `web_recorder.js` `send()` — one-line comment explaining that the binding disappears when the
   recorder detaches, so losing an event there is expected and throwing would break the user's page.
4. `capturekarma/scene/__init__.py` — `__all__` is now an explicit list of the 23 exported names; the
   old `[n for n in dir() if not n.startswith("_")]` leaked the `loader` and `model` submodules.
   Covered by `tests/test_scaffold.py::test_scene_package_exports_names_not_submodules`, which also
   asserts every listed name actually resolves.
5. `capturekarma/gui/main_window.py` — new `_output_dir_for_selection()` returns the selected scene's
   `output.dir` (expanded), falling back to `self.output_dir` when nothing is selected or the scene
   will not load (logging `could not read <name>: <err>; opening <dir>`). `_open_output()` uses it.
   `SceneError` added to the imports. Three tests in `tests/test_gui.py`: the selected scene's dir is
   opened and created, a `~` in it is expanded, and both fallbacks work.

---

## Commands and output

```
$ uv run pytest -q                                     # pure
183 passed, 28 deselected in 2.08s

$ uv run pytest -q -m "win32 or integration"           # real desktop + Chromium
26 passed, 2 skipped, 183 deselected in 36.01s
SKIPPED [1] tests/test_capture_win32.py:24: ffprobe unavailable
SKIPPED [1] tests/test_e2e_win32.py:35: ffprobe not on PATH; video produced but not probed
```

Both skips are the documented `ffprobe` absence in the bundled `imageio-ffmpeg` build; the videos are
produced and asserted on, just not probed.

Focused runs along the way, all green: `tests/test_desktop_recorder.py` (14), `tests/test_cli.py` (9),
`tests/test_scene.py` (65), `tests/test_desktop_driver.py` (7), `tests/test_gui.py` +
`tests/test_scaffold.py` (14), `tests/test_ffmpeg_args.py` (5),
`tests/test_capture_win32.py -m win32` (1 passed, 1 skipped),
`tests/test_win_input.py -m "win32 or integration"` (1).

## Concerns

- **The ddagrab + NVENC branch now round-trips frames through system memory.** That is the only form
  that satisfies "yuv420p unconditionally" with this ffmpeg build, and it is what the libx264 ddagrab
  branch already did, but it does give up the GPU-resident path. It still hit 124 frames in 1.5 s at
  60 fps on a 640x360 region, so it keeps up; a large region on a slower machine is worth a look. The
  alternative — dropping `-pix_fmt` on that branch only — would leave NVENC choosing its own format
  and violates spec §3.6.
- `set_dpi_awareness`'s new shcore HRESULT branch is not unit-tested: it only runs on pre-1703
  Windows, and forcing it would mean monkeypatching `ctypes.windll`. The primary
  `SetProcessDpiAwarenessContext` path is exercised by every `win32` test and was checked by hand.
- The name validation rejects leading/trailing spaces, which `parse_scene` used to silently `.strip()`
  away. That is the requested behaviour (it is a filename stem) but it is a strictening: a scene file
  with `name: " demo "` that loaded before now fails with a clear message.

---

# Follow-up: F revisited — NVENC consumes ddagrab frames directly

Second commit on `v2-scripted-demo-recorder`, after the coordinator probed both forms on this
machine and found the direct path already produces `yuv420p`.

## What I got wrong the first time

I established that `ddagrab → h264_nvenc -pix_fmt yuv420p` fails, and concluded that
`-vf hwdownload,format=bgra` was therefore needed to satisfy spec §3.6. I never tested the third
option — dropping `-pix_fmt` *and* the filter — so I did not notice that NVENC converts the d3d11
bgra surface internally and emits `yuv420p` on its own. Re-probed and confirmed:

```
-f lavfi -i ddagrab=... -c:v h264_nvenc -preset p4 -cq 19 -rc vbr -r 60 -movflags +faststart
→ Stream #0:0: Video: h264 (Main), yuv420p(tv, bt470bg/bt709/iec61966-2-1, progressive),
                640x360 [SAR 1:1 DAR 16:9], 414 kb/s, 60 fps, 60 tbr
```

So the hwdownload form was a GPU→CPU copy of every frame for a conversion NVENC was already doing.
Reverted.

## 1. `capturekarma/capture/ffmpeg.py`

The ddagrab + NVENC branch is back to the direct form, with the reasoning recorded in place:

```python
if caps.nvenc:
    # NVENC consumes the d3d11 bgra surface directly and emits yuv420p; -pix_fmt is rejected
    # for hw frames and hwdownload would copy every frame through system memory.
    args += ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "19", "-rc", "vbr"]
else:
    args += ["-vf", "hwdownload,format=bgra", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-pix_fmt", "yuv420p"]
```

The other three branches keep `-pix_fmt yuv420p`: ddagrab+libx264 (which still needs the
hwdownload), gdigrab+nvenc and gdigrab+libx264.

`tests/test_ffmpeg_args.py::test_ddagrab_nvenc_args` now asserts `"hwdownload" not in joined` and
`"-pix_fmt" not in joined` on that branch, with the hardware finding as the comment.
`test_ddagrab_libx264_downloads_frames` is untouched and still green.

The `CLAUDE.md` gotcha was rewritten to state the real rule — NVENC direct, no `-pix_fmt`, no
hwdownload; libx264 needs hwdownload; gdigrab takes `-pix_fmt` normally — and to say outright that
real capture tests must assert `cap.use_ddagrab`, or a fallback hides an ffmpeg-args regression.

## 2. Container checks without ffprobe — `tests/_video.py`

New helper `video_stream_info(path) -> dict` returning
`{pix_fmt, width, height, fps, tbr, duration, source}`.

- **With ffprobe** (PATH, or the sibling of whichever ffmpeg `find_ffmpeg()` picked): the usual
  `-show_entries stream=r_frame_rate,avg_frame_rate,width,height,pix_fmt:format=duration`.
- **Without it** (this machine — the bundled `imageio-ffmpeg` build has no `ffprobe`): run
  `ffmpeg -hide_banner -i <file>`, which prints the stream layout to stderr and exits non-zero, and
  parse the `Stream #0:0 ... Video: h264 ..., yuv420p(...), 640x360 ..., 60 fps, 60 tbr` line.

Details that matter:
- `tbr` is the **declared** rate and is what the tests assert; `fps` is the average, which sags
  below it whenever the capture dropped frames. Both are returned. `1k tbr` style suffixes are
  handled (`×1000`).
- The codec tag `(avc1 / 0x31637661)` is stripped before the `WxH` search so its hex cannot be
  mistaken for a frame size.
- `duration` is `None` on the ffmpeg path (`ffmpeg -i` only reports centisecond precision), so
  duration comparisons stay ffprobe-only.
- `source` records which path was taken.

Verified directly: `{'pix_fmt': 'yuv420p', 'width': 640, 'height': 360, 'fps': 60.0, 'tbr': 60.0,
'duration': None, 'source': 'ffmpeg'}`.

## 3. The two win32 tests

`tests/test_capture_win32.py::test_record_one_second` — the old local `_ffprobe` helper (and its
`pytest.skip("ffprobe unavailable")`) is gone. It now asserts 640x360, `tbr == 60`,
`pix_fmt == "yuv420p"`, and:

```python
if caps.ddagrab and not mon.rotated:
    # A silent gdigrab fallback still produces a valid MP4, so without this an ffmpeg-args
    # regression on the ddagrab branch would pass unnoticed (it did once - see the pix_fmt fix).
    assert cap.use_ddagrab is True, "ddagrab fell back to gdigrab; the GPU capture path is broken"
```

The guard keeps it honest on a machine with no ddagrab or a rotated primary, where a fallback is
correct rather than a bug.

`tests/test_e2e_win32.py` — uses the same helper; asserts `pix_fmt == "yuv420p"`, `tbr == 60` and
even dimensions unconditionally, and compares the container duration only when `duration is not
None`. That check is a plain `if`, not a `pytest.skip`, so the test no longer reports as skipped
when it has in fact verified everything else.

Both "ffprobe unavailable" skips are gone; the marked suite is now **28 passed, 0 skipped**.

## Confirmation on this desktop

```
$ uv run pytest tests/test_capture_win32.py -q -m win32
2 passed in 4.20s            # was "1 passed, 1 skipped"; the use_ddagrab assertion is live

$ <manual start_capture on the primary monitor>
ARGS: ... -f lavfi -i ddagrab=output_idx=0:...:draw_mouse=0
      -c:v h264_nvenc -preset p4 -cq 19 -rc vbr -r 60 -movflags +faststart
use_ddagrab: True   frames: 124
stream: {'pix_fmt': 'yuv420p', 'width': 640, 'height': 360, 'fps': 60.0, 'tbr': 60.0,
         'duration': None, 'source': 'ffmpeg'}
```

`cap.use_ddagrab is True` and `pix_fmt == "yuv420p"` — no `hwdownload`, no `-pix_fmt`, no fallback.

## Full runs

```
$ uv run pytest -q
183 passed, 28 deselected in 2.17s

$ uv run pytest -q -m "win32 or integration"
28 passed, 183 deselected in 34.30s
```

Both pristine, no skips anywhere.

## Concerns

The earlier concern about the ddagrab branch giving up its GPU-resident path is **withdrawn** — the
frames never leave the GPU now. The remaining two concerns from the first wave (the untested
pre-1703 shcore HRESULT branch, and name validation rejecting leading/trailing spaces) still stand.

One new, small one: the ffmpeg-stderr parser in `tests/_video.py` is regex-based and only tested
against this ffmpeg 7.1 build's output format. If a future ffmpeg reworks that line the helper will
fail loudly (its asserts name the line they could not parse) rather than silently return wrong
values, and the ffprobe path is preferred whenever it is available.

---

# Micro follow-up: five minors (third commit)

## 1. Stale ffprobe docs

Both paragraphs were made false by the second commit and are rewritten.

`CLAUDE.md` — the bundled binary still has no `ffprobe`, but nothing *requires* it any more; the
gotcha now points at `tests/_video.py::video_stream_info` and tells the next person to probe through
that helper instead of shelling out to `ffprobe` in a test.

`README.md` (Development) — no longer tells users to install a full ffmpeg on `PATH`. It now says the
container checks read the stream layout from `ffmpeg -i`, nothing needs installing, and a real
`ffprobe` on `PATH` is used in preference — which additionally enables the end-to-end test's
container-duration comparison.

## 2. `tests/_video.py` — duration on both paths, `N/A` tolerated

- New `_DURATION` regex + `_seconds()` parse `Duration: HH:MM:SS.cc` from `ffmpeg -i` stderr, so the
  ffmpeg path now returns a real `duration` (centisecond precision, ample for the comparison)
  instead of `None`.
- New `_float_or_none()` makes the ffprobe path return `None` for ffprobe's literal `"N/A"` (and for
  a missing `format.duration`) rather than raising `ValueError`. `_fraction()` already returned
  `None` for `0/0` and `N/A`.
- `duration` is now `None` only when the container genuinely carries no duration, so the
  `if info["duration"] is not None` guard stays meaningful.
- Docstring updated to match.

Spot-checked: `Duration: 00:01:09.28` → `69.28`; `Duration: N/A` → `None`; `_float_or_none("N/A")` →
`None`; `_fraction("0/0")` → `None`.

## 3. `capturekarma/cli.py` — `typer.Exit` / `typer.Abort` pass through

Added to all three commands, immediately before the catch-all:

```python
except (typer.Exit, typer.Abort):
    raise                 # control flow, not failure: both subclass RuntimeError
```

Confirmed on this typer (0.27.1): `typer.Exit.__mro__` is `Exit → RuntimeError → Exception`, so the
catch-all would otherwise have turned a future `raise typer.Exit(0)` into `error: 0` and exit 1.

Test `tests/test_cli.py::test_typer_exit_passes_through_the_catch_all`: `Player.run` raises
`typer.Exit(3)`; asserts `r.exit_code == 3` and no `error:` in the output. It discriminates —
without the passthrough the catch-all would give exit 1.

## 4. `test_gdigrab_args_use_screen_coords` parametrized

Now runs over `(CAPS_NV, "h264_nvenc")` and `(CAPS_SW, "libx264")`, asserting the expected encoder,
`-pix_fmt yuv420p` present (gdigrab frames are software, so `-pix_fmt` applies normally) and
`hwdownload` absent. All four ffmpeg branches now have their `-pix_fmt` behaviour pinned by a test.

## 5. `capturekarma/scene/loader.py` line wrap

The 155-char ternary (a line-continuation that an earlier heredoc had flattened) is now three
readable lines under 120:

```python
relative = Path(url).expanduser()
local = (relative if relative.is_absolute() else p.parent / relative).resolve()
```

No behaviour change; `awk 'length > 120'` is clean across the touched files.

## The e2e duration assertion: it executed, and it FAILED — findings

Making the check live immediately surfaced a real failure:

```
FAILED tests/test_e2e_win32.py::test_play_web_fixture_end_to_end
  AssertionError: assert 0.9961324999155474 <= 0.5
```

Rather than widen the tolerance to green, I measured what the two numbers actually are:

```
res.duration : 6.522      # player clock
res.frames   : 436
container    : 7.27       # frames/60 = 7.267  ← exact
delta        : +0.748
```

**Not a capture bug.** The container duration equals `frames / fps` to three decimals, so every frame
ffmpeg captured is in the file — nothing is dropped or truncated. The container is *longer* than
`res.duration` because the player's clock (`_elapsed()`, read in the `finally` block) stops before
`capture.stop()` writes `q` and ffmpeg flushes and muxes; that gap is ffmpeg's shutdown latency
(0.75 s measured here, 0.996 s in the failing pytest run). The old symmetric `abs(...) <= 0.5`
described a relationship that does not hold, which is exactly why it survived — it had never once
run on this machine.

Replaced with the invariant that is actually true, which is also a stronger check:

```python
if info["duration"] is not None:      # None only when the container carries no duration at all
    # The container holds every frame ffmpeg captured, so its duration is exactly frames/fps.
    assert abs(info["duration"] - res.frames / scene.output.fps) <= 0.1
    # It is *longer* than the player's own clock, which stops before capture.stop() does: the
    # gap is ffmpeg's shutdown latency (~0.7-1.0s here), not lost footage. Bound it both ways
    # so a truncated video or a runaway capture still fails.
    assert -0.5 <= info["duration"] - res.duration <= 2.0
```

The `frames/fps` equality is the sharp one (±0.1 s); the `res.duration` band is a loose sanity bound
that still catches a truncated video (lower bound) or a capture that failed to stop (upper bound).

## Runs

```
$ uv run pytest -q
185 passed, 28 deselected in 2.28s          # 183 + the typer.Exit test + the gdigrab parametrization

$ uv run pytest tests/test_e2e_win32.py -q -m "win32 or integration"
1 passed in 10.33s      (re-run: 1 passed in 9.81s — stable across two runs)

$ uv run pytest -q -m "win32 or integration"
28 passed, 185 deselected in 100.48s        # ran in full because tests/_video.py changed
```

No skips anywhere.

## Concerns

- The `2.0 s` upper bound on ffmpeg's shutdown latency is empirical (0.75 s and 0.996 s observed on
  this machine). A much slower machine could exceed it; it would then fail loudly with both numbers
  visible rather than hide a problem, and the sharp `frames/fps` assertion is unaffected.
- Worth noting for whoever tunes the player: `res.duration` under-reports the finished video's length
  by ffmpeg's stop latency. That is correct as a measure of *playback*, but it is not the video's
  duration, and the log line `saved %s (%.1fs, %d frames)` prints the playback figure. Not changed
  here — out of scope for a minors pass — but flagged.
- Earlier concerns still standing: the untested pre-1703 shcore HRESULT branch, name validation
  rejecting leading/trailing spaces, and the regex-based ffmpeg-stderr parser being pinned to this
  build's output format.
