# Drag and canvas-wheel support — implementation report

2026-08-27 · branch `main` · six commits, `2082651`..`fba3988`

## Why

CaptureKarma could record clicks, page scrolls and keys. A 3D product viewer is driven by
*dragging* on a canvas and *wheel-zooming* over it, and neither survived a recording: a drag
arrived as the browser's synthetic `click`, and a canvas wheel arrived as nothing at all (a viewer
that zooms calls `preventDefault`, so no `scroll` event ever fires). The user's real scene,
`C:\Users\Kamal Khanal\Downloads\test capture\web-1.yaml`, shows both symptoms — every
`click` on `[data-testid="stage"]` was really an orbit — and it also crashed on playback with a
selector containing newlines.

## What changed

### 1. Scene format: two new step types (`2082651`)

| Step | Shape |
| --- | --- |
| `drag` | `{path: [[x, y], ...], duration?, button?, easing?, hold?}` — at least 2 points. Web: viewport CSS px. Desktop: region-relative px. |
| `wheel` | `{by: int, at?: [x, y] or selector, duration?, easing?, hold?}` — wheel input **without** page scrolling. `by` non-zero, positive = wheel down. |

`DragStep` / `WheelStep` are frozen kw-only dataclasses, the `Step` union and
`scene/__init__.__all__` are updated, validation is strict and quotes the step index, and both
round-trip through `dump_scene` / `load_scene`. On desktop scenes `wheel at:` must be coordinates
(the existing selector rejection covers it). README's step table, YAML example and the timing
paragraph document them.

New in `motion.path`:

- `drag_duration(length, speed) = clamp(length / speed * 1.5, 0.6, 6.0)`.
- `polyline_path(points, n_ticks, easing)` — arc-length parametrised, so the cursor keeps a
  constant speed along the polyline while the *overall* progress follows the easing. Exactly
  `n_ticks` points, last one exactly `points[-1]`; a two-point path degenerates to a straight
  eased line; a zero-length path returns the endpoint repeated.

### 2. Driver protocol and playback (`4804283`)

`Driver` gains `smooth_wheel(step, duration, easing)`.

- **WebDriver** paces `page.mouse.wheel(0, delta)` at ~30 Hz over `duration`, quantising with
  carry-over so the deltas sum to exactly `by` under every easing (same technique as
  `win_input.wheel_steps`, but in pixels with no unit conversion). Playwright dispatches the wheel
  at the current virtual mouse position; the player has already moved there.
- **DesktopDriver** reuses the `wheel_steps` path — Windows cannot tell a canvas zoom from a page
  scroll, so `smooth_wheel` and `smooth_scroll` share `_wheel_over`.

The player handles `DragStep` (eased move to `path[0]`, `mouse_down` + `overlay.click()` ripple +
a `click=True` timeline sample, arc-length traversal with `_check_abort()` **per tick**, `mouse_up`,
then the usual hold) and `WheelStep` (optional eased move to `at`, then `smooth_wheel`; default
duration `scroll_duration(by)`).

### 3. Recording (`38fc3ea`)

`RawEvent` gains `drag` (`path`, `button`, `duration`) and `wheel` (`delta`, `at`).

**Web** (`web_recorder.js`): `pointerdown` opens a candidate; `pointermove` keeps a point every
40 ms or every 8 px; `pointerup` emits `drag` when the path is at least 6 px long **or** the press
lasted at least 300 ms and moved at all, and sets `suppressClick` so the synthetic `click` that
follows the same gesture is dropped (the click handler clears the flag either way). `pointercancel`
and window `blur` discard a half-recorded gesture rather than guess where it ended.

Canvas wheel: a capture-phase passive `wheel` listener accumulates `deltaY` per burst
(`deltaMode` normalised — lines x16, pages x viewport height) with the first event's `clientX/Y`,
refreshing a 150 ms timer. If any `scroll` fires while the burst is open the page really moved and
the existing scroll path already reported it, so nothing is sent; otherwise a `wheel` event is.

**Desktop** (`recorder/desktop.py`): the same thresholds over pynput's `on_move`. One deliberate
behaviour change — a click is now recorded **on release** (stamped and positioned at the press
point), because the release is what decides click vs drag. `on_scroll` stays a `scroll`.

**Smoothing**: `drag` becomes `MoveStep(to=path[0])` + `DragStep(path, duration=clamp(recorded,
0.6, 6.0), button)`. Consecutive `wheel` events within `scroll_merge_window` and within 40 px of
each other merge into one `WheelStep`; a burst summing to zero is dropped; wheels never merge into
scrolls.

### 4. Selector text and the real viewport (`9ee5af1`, `fba3988`)

**The crash.** `uniqueSelector` wrote the element's raw `innerText`. A badge stacked over a label
gave `button:has-text("1\n\nRadiator")`, which Playwright rejects outright:
`Unsupported token "BADSTRING" while parsing css selector`. Investigating the fix turned up a
second, quieter bug: Playwright's `:has-text()` matches the whitespace-normalised **`textContent`**,
not `innerText` — so even a newline-free `button:has-text("1 Radiator")` matches *nothing*
(`textContent` is `"1Radiator"`; `<br>` and block boundaries contribute no whitespace). The
recorder now normalises `textContent`, and checks uniqueness the way Playwright will actually
match — substring, case-insensitive — so a "Save" beside a "Save all" falls back to a structural
selector instead of silently resolving to the wrong button.

**The viewport.** Chromium silently clamps a window it cannot fit on screen, so a 1920x1080 request
on a 1080p display yields a shorter viewport while the scene still claims 1920x1080 — putting every
recorded coordinate out by the difference. `WebRecorder` now measures `innerWidth`/`innerHeight`
after `start()` and writes *that* into the scene, and both `WebRecorder.start` and
`WebDriver.setup` shrink an oversized request up front via `fit_viewport_to_monitor()` with a
`log.warning`.

`fba3988` fixes a bug found while verifying this: `fit_viewport_to_monitor` enumerates monitors, and
`record_web` never declared DPI awareness, so Win32 reported *logical* px — a 1920x1080 monitor at
125% scaling measures 1536x864 and every viewport would be shrunk to fit a screen that was never too
small. Same gotcha `record_desktop` already guards against.

### 5. GUI diagnostics (`f838eee`)

`gui/app.install_file_log()` tees the `capturekarma` logger at INFO to a
`RotatingFileHandler` at `~/Videos/CaptureKarma/capturekarma.log` (1 MB x 3, `delay=True`),
idempotently; an unwritable folder logs a warning and never stops the app from starting.
`Worker.failed` already carried the exception type and, for `StepError`, the step number and
message (`StepError: step 5: element not found: '#missing'`) — now covered by a test rather than
assumed. README gains a Troubleshooting section.

## Tests

TDD throughout: every unit landed with a failing test first.

    uv run pytest -q
    246 passed, 39 deselected in 2.31s          (213 before this work)

    uv run pytest -q -m "win32 or integration"
    35 passed, 1 skipped, 3 failed, 249 deselected in 35.98s

The three failures are **pre-existing and environmental**, not regressions:

| Test | Failure |
| --- | --- |
| `test_capture_win32.py::test_record_one_second` | `ffmpeg exited before producing frames` |
| `test_e2e_win32.py::test_play_web_fixture_end_to_end` | same |
| `test_overlay_win32.py::test_overlay_draws_and_hides` | `OSError: screen grab failed` |

`OpenInputDesktop()` returns `ERROR_ACCESS_DENIED` on this session — the desktop is locked, so
neither ddagrab/gdigrab nor PIL's `ImageGrab` can capture anything. Verified by checking out the
base commit `220d50e` into a worktree and running the same three tests against the same venv:
identical three failures, before any of this work. Deselecting exactly those three:

    35 passed, 1 skipped, 249 deselected in 33.27s

New coverage: `polyline_path` / `drag_duration` (6), scene parse + round-trip + rejection (5 plus
11 parametrised), player drag/wheel (8), `smooth_wheel` on both drivers (4), smoothing goldens (6),
desktop drag handlers (8), web recorder drag + canvas wheel + selector normalisation (7), viewport
fitting (7), GUI log file and failure message (3). Plus one end-to-end integration test:
`test_canvas_drag_and_wheel_replay_through_the_driver` records a drag and a wheel over a new
`#stage` canvas in `tests/fixtures/page.html`, turns the events into a scene, replays that scene
through a fresh headless `WebDriver`, and asserts `window.__stage` ends with identical
`{dx, dy, wheel}` totals — recorder to scene to driver, closed loop.

## Playing the user's old scene

`uv run ck play "C:\Users\Kamal Khanal\Downloads\test capture\web-1.yaml" --out-dir <tmp>`

**Run 1 — fails at step 2**, `element not found or not visible: '[data-testid="stage"]'`. The error
screenshot shows the viewer still loading at *51%*: the scene's opening `wait: 2.0` is far shorter
than the model download. A scene-content problem, not a code one.

**Run 2 — a copy with a 30 s wait prepended** reaches step 33 and fails there:

    error: step 33: invalid or failing selector 'button:has-text("1\nRadiator")':
    Locator.count: Unsupported token "BADSTRING" while parsing css selector ...
    (screenshot: ...web-1-longwait_....error.png)

That is the user's original crash, reproduced exactly — and it is expected: **the fix is in the
recorder, and the old scene file still holds the broken selector on disk.** It now fails as a clean
`StepError` with a step number and a screenshot rather than an unhandled Playwright error. Steps
1-32 replayed fine.

**Proof the fix works on that site.** Since the viewer needs a real GPU (headless Chromium never
renders it), I ran the *new* recorder headed against
`https://inspect3d.paracosma.workers.dev/viewer/cascadia`, opened Annotate and clicked the first
annotation:

    BUTTON LABELS:      ['1Radiator', '2Lights', '7Tires']
    RECORDED SELECTOR:  'button:has-text("1Radiator")'
      newline in it?    False
      resolves to       1

The same button that produced the crashing selector now produces one that resolves to exactly one
element. The viewport fix is visible in the same run: `requested viewport 1600x900 ... using
1584x780` followed by `viewport is 1584x780, not the requested 1600x900; recording against the real
one` — and the scene is written with `viewport: [1584, 780]`.

A real re-record of the full demo needs a human to drag the model, so drag/wheel capture is covered
by the fixture integration test described above instead.

## Concerns

1. **The old scene needs re-recording, not repairing.** Its ~40 `click` steps on
   `[data-testid="stage"]` were orbits, and no code change can recover paths that were never
   recorded. It also needs a longer opening `wait` (the model takes well over 2 s to download) —
   worth considering a `wait_for` step type, or making the recorder emit the real opening gap
   instead of capping it at `max_wait: 2.0`.
2. **`:has-text()` on `textContent` reads oddly.** `button:has-text("1Radiator")` is correct and
   resolves, but the missing space looks like a typo to anyone editing the YAML. It is what
   Playwright matches; a `:text-is()` variant or an explicit `has_text` regex would read better but
   changes the selector grammar the scene format promises.
3. **`fit_viewport_to_monitor` compares CSS px against physical px.** Exact only at
   `devicePixelRatio` 1. On a scaled display it under-shrinks — the driver's `_measure()` records
   the truth afterwards either way, and the docstring says so, but it is a real limitation.
4. **Web `drag` deliberately has no selector form.** A drag is a gesture over a region, not a click
   on an element, so `path` is always coordinates. That means drag steps break if the viewer moves
   on the page — unlike `click`, they cannot be re-anchored to an element.
5. **Desktop cannot distinguish wheel-zoom from scroll.** Desktop recording always writes `scroll`;
   a desktop 3D viewer needs the step hand-edited to `wheel`. Documented in Limitations.
6. **A click is now recorded on release, not press** (desktop). It is still stamped and positioned
   at the press point, so timing is unchanged, but a press with no release (recording stopped
   mid-gesture) is now discarded rather than recorded as a click.
7. **The desktop session is locked**, so nothing in this session exercised real capture, the
   overlay, or a real end-to-end MP4. Those three win32 tests should be re-run on an unlocked
   desktop before release. The display also changed mode from 1920x1080 to 1600x900 partway through
   the session (the GPU still reports 1920x1080), which is what the ddagrab
   `Failed duplicating output` fallbacks were tracking.
