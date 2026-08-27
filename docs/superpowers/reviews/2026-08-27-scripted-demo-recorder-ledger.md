# CaptureKarma v2 — orchestration ledger (2026-08-27)

Copied from the SDD workspace at completion. Rulings and parked follow-ups are authoritative here.

# SDD ledger — plan: docs/superpowers/plans/2026-08-27-scripted-demo-recorder.md

Spec: docs/superpowers/specs/2026-08-27-scripted-demo-recorder-design.md (reachable, binding authority)
Branch: v2-scripted-demo-recorder (from main @ 256e449)

Ruling: implement in place on a new feature branch instead of a git worktree — the session is configured to work in place (harness instruction) and the user approved implementation; a branch still protects main — cost if wrong: none beyond a branch switch.
Ruling: implementers run on Opus (`model: "opus"`) per the user's explicit instruction ("use opus 5 for implementation"), overriding the cheap-tier default for transcription tasks — cost if wrong: token spend only.

## Pre-flight conflict scan

| Tasks | Interface | Producer → Consumer | Finding |
|---|---|---|---|
| 1→all | `_win.set_dpi_awareness/high_res_timer/IS_WINDOWS` | T1 produces; T3 (ticker note), T4, T5, T6, T11, T12, T14 consume | consistent names |
| 2→3 | `EASING_NAMES` in scene.model | T2 defines 4 names; T3 `EASINGS` keys tested equal | consistent |
| 2→6,7,11 | `StepTarget(selector, at)`, `ScrollStep(by,to,container)`, `Region(x,y,width,height)` | same field names used in T6/T7/T11 code and tests | consistent |
| 3→6,7,11 | `Ticker(hz, clock, sleep)`, `.now()`, `.n_ticks`, `.ticks`, `.wait`; `Easing`; `bezier_path(start,end,n,easing,index)`; `move_duration`, `scroll_duration` | T6 uses n_ticks/ticks; T11 uses all; `.now()` added in self-review | consistent |
| 4→11,12 | `CaptureError`, `find_ffmpeg`, `probe`, `list_monitors`, `monitor_for_region`, `start_capture(caps, region, monitor, fps, out, prefer_ddagrab)`; capture object `.stop()->Path`, `.frames` | T11 default_capture_factory + FakeCapture match | consistent; `CaptureError` defined in monitors.py and re-exported by recorder.py and capture/__init__ |
| 5→11 | `CursorOverlay(style, ripple, visible)` `.start/.stop/.set_position/.set_visible/.click` | T11 overlay_factory + FakeOverlay match | consistent |
| 6→7,11 | `Driver` protocol incl. `smooth_scroll(step, duration, easing)`, `StepError(message, step_index, screenshot)` | T7 WebDriver, T11 Player use same signature | consistent |
| 6→10 | `win_input.find_window/focus_window/window_client_region`, `PX_PER_NOTCH` | T10 imports them | consistent |
| 8→9,10 | `RawEvent` fields, `smooth(events, config)`, `StopHotkey.triggered` | T9/T10 construct RawEvent with same kwargs | consistent |
| 2→9,10 | `dump_scene(scene, path, header)`, `Scene(name, target, steps: tuple)` | T9/T10 pass `tuple(smooth(...))` | consistent |
| 11→12,14 | `Player(scene, options, *, stop_event=...)`, `PlayOptions(out_dir, cursor_visible, cursor_style, hz, prefer_ddagrab)`, `RunResult(video, timeline, partial, duration, frames)` | CLI test inspects `call_args.args[1]`; GUI passes kwargs | consistent |
| 12 | `record_web(url, out, viewport=, name=)` / `record_desktop(window, out, name=)` | CLI test asserts `kwargs["viewport"]` → CLI must pass viewport as keyword | plan CLI code does |
| Self-consistency | each task's tests vs code | checked in plan self-review; fixed: ticker late-tick test, smoothing wait values, recorder event order, sprite tip check, player timing (4.18 s), output naming w/o with_suffix | resolved before execution |

Rubric conflicts mandated by plan: none found (no assert-less tests, no verbatim duplicated logic blocks).

Known risk (not a conflict): NVENC directly from ddagrab d3d11 frames — T4 step 7 carries the fallback instruction; T4 implementer must report which path worked.

## Progress
Ruling: run independent tasks in parallel git worktrees (branches task-N cut from v2-scripted-demo-recorder, merged back after each task's review clears) — user asked for parallelism; tasks touch disjoint files so the SDD "no parallel implementers" rule's conflict risk does not apply — cost if wrong: a merge conflict to resolve by hand. Waves: T1→T2 sequential; A = {T3,T4,T5,T8}; B = {T6,T9} then {T7,T10}; T11 sequential; C = {T12,T13,T14}.
Task 1: minor (deferred): _win.py dead `ctypes.get_last_error()` operand (windll doesn't populate it); broad except in shcore fallback returns False+log; `ck` entry point resolves only after Task 12.
Task 1: complete (commits 256e449..da77974, review clean)
Task 2: BASE da77974, in place on v2-scripted-demo-recorder
Ruling: controller committed a 6-line conftest change pinning PYTEST_DEBUG_TEMPROOT to <repo>/.pytest_tmp (+ .gitignore) — %LOCALAPPDATA%\Temp\pytest-of-Kamal Khanal has an ACL that denies takeown/rename even outside the sandbox (needs admin); without this every tmp_path test fails in every worktree. Environment fix, not a task finding — cost if wrong: an extra ignored directory in the repo. User should delete that Temp dir as admin.
Task 2: Ruling: "CursorStep overrides unreachable from YAML" (plan-mandated) — code stands. Spec §3.7 defines the cursor step as the scalar `cursor: visible|hidden`; it is an instant toggle and the player (§3.9/T11) applies no hold after it, so duration/easing/hold have no meaning there. Cost if wrong: a 4-line loader change later.
Task 2: minor (deferred): non-mapping `output`/`cursor`/`defaults` values give a confusing "unknown key(s) o, p, s" SceneError; `_point()` and `cursor.speed` accept bool; `scene/__init__.__all__` leaks `loader`/`model`; Region helpers untested.
Task 2: fix round 1/5 dispatched — open: empty-string `scroll in:` / desktop `window:` accepted at parse but dropped by scene_to_dict (round-trip loss). FIX_BASE f26dbbd.
Task 2: fix round 1/5 (1 addressed, 0 open — empty container/window rejected at parse, dump uses `is not None`; commits f26dbbd..f764ddf)
Task 2: complete (commits da77974..f764ddf, review clean after 1 fix round)
Wave A dispatched: Tasks 3,4,5,8 — BASE f764ddf each; worktrees D:/Repos/CaptureKarma-wt/task-N on branches task-N
Task 3: implementer concern (high_res_timer ownership) — resolved: Player.run wraps execution in high_res_timer() per T11 brief; no action.
Task 3: Ruling: "move_duration unguarded for speed==0" (plan-mandated) — code stands; scene loader rejects cursor.speed <= 0 at parse time so the player never passes 0; a raw ZeroDivisionError for a programmatic misuse is acceptable at this layer. Cost if wrong: one `if speed <= 0: raise ValueError` later.
Task 3: minor (deferred): bezier_path n_ticks=0 → 1 point; sleep_until has no iteration cap; n_ticks banker's rounding; pts[-1]=end snap masks non-terminating easings.
Task 3: complete (commits f764ddf..bf4b37a, review clean; merged into v2-scripted-demo-recorder)
Task 4: implementer DONE_WITH_CONCERNS — nvenc direct from ddagrab d3d11 frames WORKS (no hwdownload); EnumDisplayMonitors order == ddagrab output_idx verified pixel-identical on both landscape monitors.
Task 4: Ruling: ddagrab ignores display rotation (portrait monitor here: enum says 2160x3840, ddagrab surface is 3840x2160 → silent wrong region). Correctness concern → addressed before review: add `Monitor.rotated` (EnumDisplaySettingsW dmDisplayOrientation != 0) and have start_capture force gdigrab with a warning for rotated monitors. Spec §3.6 allows gdigrab fallback with warning. Cost if wrong: slower CPU capture on rotated displays only.
Task 8: Ruling: "StopHotkey has no automated tests" (plan-mandated gap) — fix now: add invariant tests with pynput.keyboard.Listener monkeypatched (is_set False before start; stop no-op before start; start sets daemon and registers f9/esc; simulated on_press of Key.f9 sets triggered). Cheap, protects Tasks 9/10/12. Cost if wrong: a few test lines.
Task 8: minor (deferred): `assert e.key is not None` stripped under -O; net-zero scroll burst consumes time without a wait step (untested); trailing-modifier key group untested; PRINTABLE_KEY naming.
Task 8: fix round 1/5 dispatched — open: StopHotkey tests. FIX_BASE aa629b1.
Task 8: fix round 1/5 (1 addressed, 0 open — 9 StopHotkey tests with fake Listener; commits aa629b1..71d1172)
Task 8: complete (commits f764ddf..71d1172, review clean after 1 fix round; merged)
Wave B (early start): Tasks 6, 9 dispatched — BASE = merge head after task-8; worktrees task-6, task-9
Task 5: implementer DONE_WITH_CONCERNS — three plan-bug fixes accepted as rulings: (a) SetWindowPos needs SWP_NOMOVE or it drags the overlay to 0,0 each frame; (b) ctypes argtypes/restype required on 64-bit for HWND/HANDLE (OverflowError otherwise); (c) Image.getdata() deprecated in installed Pillow → tests use .tobytes(). Cost if wrong: none — verified by pixel checks.
Task 4/5: reviews dispatched (BASE f764ddf; heads e5bd7e9 / 16290d4)
Task 4: Ruling: "kill() without wait() in ScreenCapture.stop()" (plan-mandated) — real, fix now (one line: wait after kill so returncode is set and the file is settled). Cost if wrong: none.
Task 4: minor (deferred): EnumDisplaySettingsW failure branch untested; duplicate logger declarations; redundant `-r fps` with ddagrab framerate; asymmetric -pix_fmt on nvenc branches.
Task 4: fix round 1/5 dispatched — open: wait after kill. FIX_BASE e5bd7e9.
Task 5: minor (deferred): dead `user32.SetProcessDPIAware` attribute access in overlay thread; BITMAPINFO.bmiColors DWORD*3 over-allocation (harmless).
Task 5: complete (commits f764ddf..16290d4, review clean; merged)
Task 9: Ruling: accepted deviation — WebRecorder.wait() pumps Playwright via page.wait_for_timeout instead of Event.wait (sync API dispatches bindings on the calling greenlet; otherwise no events arrive and timestamps collapse). Plan bug. Cost if wrong: none.
Task 9: deferred (cross-task, for final review): record_web runs headed with no_viewport=True so target.viewport is a hint; T7's WebDriver fits the window to the viewport — consider sharing that helper with the recorder so recorded `at:` coordinates match playback.
Task 4: fix round 1/5 (1 addressed, 0 open — wait after kill + 3 tests; commits e5bd7e9..2014e7c)
Task 4: complete (commits f764ddf..2014e7c, review clean after 1 fix round; merged)
Task 6: implementer DONE_WITH_CONCERNS. Accepted: Ticker.sleep_until spin fix (remaining ~= spin+epsilon → sleeps 1e-18 forever with a fake clock) committed on task-6 as 995fcd8 — reviewed with the task.
Task 6: Ruling: wheel_steps must convert pixels → wheel units using WHEEL_DELTA/PX_PER_NOTCH (1.2 units/px), matching the recorder's PX_PER_NOTCH=100 assumption; the plan's 1 unit/px undershoots by ~17%. Plan bug; fixed pre-review. Cost if wrong: desktop scroll distance off by the same factor in the other direction (best-effort path per spec).
Task 6: Ruling: focus_window logs a warning when SetForegroundWindow returns 0 (do not raise — positional SendInput still hits the visible target). Cost if wrong: a noisy log line.
Task 9: Ruling: "headed viewport mismatch" (plan-mandated, Important) — load-bearing for `at:` fidelity; smallest fix: Task 7 extracts `fit_window_to_viewport(page, context, w, h, window_pos)` in drivers/web.py and WebRecorder.start() calls it in headed mode (carried into the T7 dispatch). Cost if wrong: recorder window sized differently from playback (status quo).
Task 9: minor (deferred): unidentifiable inner scroll container reported as page scroll (container null); uncommented catch in JS unique(); `and`-side-effect lambda for framenavigated; broad PlaywrightError catch in wait().
Task 9: complete (commits af04190..eae667b, review clean; merged)
Task 6: Ruling: "`assert t.window is not None` in DesktopDriver.setup" (plan-mandated) — real but not load-bearing: the scene loader guarantees window-or-region for desktop targets, so the assert is type narrowing; deferred to the final fix wave as `raise DriverError(...)`. Cost if wrong: unclear TypeError under -O for an unreachable input.
Task 6: minor (deferred): ambiguous find_window substring picks first match silently; unused SimpleNamespace import in test; unused loop var in smooth_scroll; focus warning untested; sleep_until final window widened to 2*spin (4 ms).
Task 6: complete (commits af04190..792ddac, review clean after pre-review fixes; merged)
Wave B2: Tasks 7, 10 dispatched — BASE = merge head after task-6; worktrees task-7, task-10
Task 10: Ruling: keyboard shortcuts (Ctrl/Alt/Meta + key) are recorded as plain typing by both recorders because RawEvent carries no modifier state and smooth() drops modifiers — known v1 limitation, deferred (needs RawEvent.modifiers + smooth emitting `press: Control+a`); carry into README limitations (T13). Cost if wrong: shortcut-driven demos need hand-editing the scene.
Task 10: minor (deferred): record_desktop raises AttributeError off-Windows (win_input Win32 funcs undefined) — acceptable, Windows-only tool; header f-string wrapped; unused PressStep test import.
Task 10: Ruling: "on_scroll not region-filtered" and "start() not idempotent" (both plan-mandated) — fix now (filter scroll by region like clicks; start() stops existing listeners first). Cost if wrong: none.
Task 10: minor (deferred): unknown mouse buttons clamp to left silently; unmapped pynput key names fail at replay not record; on_press doesn't guard printability itself; unused PressStep import.
Task 10: fix round 1/5 dispatched — FIX_BASE 50d0e68.
Task 7: Ruling: "setup() catches only PWError; other exceptions leak the browser" (plan-mandated) — fix now: catch Exception → teardown() → re-raise (PWError wrapped as DriverError, others re-raised as-is). Cost if wrong: none.
Task 7: minor (deferred): easing identity lookup silently falls back; malformed selector → raw Playwright error; count()+bounding_box() double round-trip; rAF throttling when backgrounded; headed recorder branch untested.
Task 7: fix round 1/5 dispatched — FIX_BASE 708abb9.
Task 11: dispatched early (BASE e40182c; player depends only on merged interfaces; WebDriver imported lazily) — worktree task-11
Task 10: Ruling: DesktopRecorder.start() restart keeps prior events (resets t0 only) — never discard recorded data silently; no call site restarts. Cost if wrong: one-line events.clear().
Task 10: fix round 1/5 (2 addressed, 0 open — scroll region filter, idempotent start; commits 50d0e68..1185aa1)
Task 10: complete (commits e40182c..1185aa1, review clean after 1 fix round; merged)
Task 7: fix round 1/5 (1 addressed, 0 open — teardown on any setup failure + 2 tests; commits 708abb9..0b4e4b0)
Task 7: complete (commits e40182c..0b4e4b0, review clean after 1 fix round; merged)
Task 13: dispatched early (BASE 933cc5c) — worktree task-13; README must include the keyboard-shortcut limitation (T10 ruling)
Task 11: implementer DONE_WITH_CONCERNS — accepted plan corrections: `_t0` None sentinel (0.0 truthiness bug), timing test expects 3.98 s (plan's own itemisation; controller mis-summed), FakeDriver.resolve guard. Ruling: all three correct. Cost if wrong: none.
Task 13: Ruling: README documents the repo's actual LICENSE (DBAD), not the plan's assumed MIT — the plan was wrong; user may swap LICENSE if MIT is intended.
Task 11: Ruling: PlayOptions.cursor_visible (when not None) pins cursor visibility for the run; `cursor:` steps become no-ops (debug log). Rationale: `ck play --no-cursor` must mean no cursor. Cost if wrong: scenes can't toggle under an override (that's the point).
Task 11: Ruling: also dump the cursor timeline on the error path (before re-raising) so an errored .partial.mp4 has its companion JSON — cheap, symmetric with abort.
Task 11: minor (deferred): RunResult.video may name a non-existent file if ffmpeg wrote nothing on abort; scroll_duration fed absolute `to` offset (clamps to 4 s); zero-distance move burns the 0.35 s floor; Player not re-entrant; timeline gaps during scroll/type/press; unused loop var; default_*_factory not re-exported.
Task 11: fix round 1/5 dispatched — open: guarded cleanup, abort check per step, cursor_visible pin, setup() inside try, failure-path tests, timeline on error. FIX_BASE 59d7701.
Task 13: Ruling: README must not mention the GUI until it exists — remove the sentence; Task 14 adds a "GUI" section with `uv run ck-gui` (carried into T14 dispatch).
Task 13: minor (deferred): `ck record` flags --viewport/--name not documented in Usage (T14 or final wave may add).
Task 13: fix round 1/5 dispatched — FIX_BASE ec36075.
Task 13: fix round 1/5 (1 addressed, 0 open — GUI mention removed, record flags documented; commits ec36075..cd97165)
Task 13: complete (commits 933cc5c..cd97165, review clean after 1 fix round; merged)
Task 11: fix round 1/5 (6 addressed, 0 open — guarded cleanup, per-step abort, cursor pin, setup in try, 10 failure-path tests, timeline on error; commits 59d7701..91e1ba4)
Task 11: complete (commits e40182c..91e1ba4, review clean after 1 fix round; merged)
Wave C: Tasks 12, 14 dispatched — BASE = merge head after task-11; worktrees task-12, task-14
Task 14: Ruling: `_open_output` catches OSError from os.startfile and reports it in the log panel (surfacing, not swallowing — an unhandled exception in a Qt slot aborts the process). Ruling: style dropdown gets a "(scene default)" first entry mapping to cursor_style=None so the GUI only overrides when the user picks a style, matching `ck play`. Accepted deviations: collision-safe recording names, live folder label, selection preserved across refresh. Deferred: MainWindow creates scenes_dir on disk (acceptable; user-chosen path).
Task 14: pre-review fix dispatched.
Task 12: implementer DONE_WITH_CONCERNS — E2E PASSES on the real desktop (18.4 s, 1146 frames, 1280x720, no chrome, cursor hide/show and eased scroll verified by frame diffs); ck doctor 8/8 OK. Accepted deviations: chromium probe in a child interpreter (in-process sync_playwright printed teardown noise), `_fail` typed NoReturn, E2E scene scrolls back before clicking #email (plan bug: element off-screen).
Task 12: deferred: headed ~9 s E2E runs in the default pytest invocation and steals focus — consider an `e2e` marker gated by env/-m at final review; examples/web-demo.yaml hardcodes the absolute fixture path (as instructed).
Task 14: Ruling: GUI cursor control should be a 'Hide cursor' checkbox (unchecked → cursor_visible=None, scene decides; checked → False) to match ck play --no-cursor — to be applied with the review's fix round.
Task 12: minor (deferred): `_fail` prints to stdout not stderr; CLI unit test installs a real pynput hook (mock StopHotkey); no test loads examples/*.yaml through load_scene; web-demo.yaml absolute path is machine-specific.
Task 12: complete (commits 266a2f1..0043d22, review clean; merged)
Task 14: Ruling: "INFO logs never reach the GUI log panel" (plan-mandated) — fix now: app.main() sets logging.getLogger("capturekarma").setLevel(INFO) (Worker also ensures it), with a Worker test asserting an INFO record from a job reaches the log signal.
Task 14: minor (deferred): `_next_scene_path` untested; README GUI sentence glosses checkbox/dropdown asymmetry (fixed alongside the checkbox change); `root` variable name in worker.
Task 14: fix round 1/5 dispatched — open: logger level, Hide-cursor checkbox semantics. FIX_BASE 96690dd.
Task 14: fix round 1/5 (2 addressed, 0 open — INFO logs forwarded, hide-cursor checkbox; commits 96690dd..7fc4278)
Task 14: complete (commits 266a2f1..7fc4278, review clean after pre-review fix + 1 fix round; merged)
ALL 14 TASKS COMPLETE. Final whole-branch review: MERGE_BASE 256e449.
FINAL REVIEW (Opus): Ready with fixes. Critical: record_desktop lacks set_dpi_awareness (logical vs physical px). Important: CLI raw tracebacks for non-domain exceptions; E2E in default pytest; example absolute path; global keystroke capture privacy; web recorder records its stop key; nvenc+ddagrab branch lacks -pix_fmt yuv420p; recorder→dump→load round trip untested. Triage: deferred 7,16 resolved; 2,5,13,14,17,18 have fix-before-merge slices; rest carry.
Ruling: relative file paths in scene `target.url` (no scheme) resolve against the scene file's directory into a file:// URL — makes examples/web-demo.yaml portable without a public URL. Cost if wrong: an extra loader branch.
Ruling: desktop recorder drops key events while the target window is not foreground (GetForegroundWindow); web recorder skips keydown inside password inputs and never records F9/Escape. README gets a privacy note.
FINAL FIX WAVE dispatched (one implementer, in place). FIX_BASE a24d4fd.
Final wave: DONE_WITH_CONCERNS (966e744). Ruling: controller probed both encoder forms with the bundled ffmpeg — direct ddagrab(d3d11)→h264_nvenc already outputs yuv420p; revert the hwdownload change (avoids a full-frame GPU→CPU copy per frame at 4K60) and drop -pix_fmt on that branch with a comment; spec §3.6's yuv420p requirement is met by the encoder output and asserted in the E2E. E2E/capture tests fall back to parsing `ffmpeg -i` when ffprobe is absent so pix_fmt/fps/dimensions are actually checked here. Cost if wrong: a non-4:2:0 file on some other NVIDIA driver (E2E would catch it).
FINAL RE-REVIEW (Opus): READY TO MERGE — all A–H addressed, no Critical/Important breakage. Residual minors: stale ffprobe paragraphs in CLAUDE.md/README (introduced by the wave); e2e duration check inert on the ffmpeg -i path; 155-char line in loader.py; catch-all would swallow typer.Exit/Abort (latent); gdigrab pix_fmt unasserted.
Ruling: one micro follow-up (same implementer) for the five residual minors — they are minutes of work, two were introduced by this wave, and leaving stale docs misleads the next reader. Cost if wrong: one more small commit + haiku re-review.
Parked (later): scheme-less hostnames now fail at load with a path-style message (add a "did you mean https://" hint); dump_scene doesn't validate `name` (record -o .hidden.yaml yields an unloadable scene); foreground filter drops keys typed into the target app's own dialogs; _video.py float("N/A").
Parked (later): RunResult.duration is playback time, ~0.75-1.0 s shorter than the container (ffmpeg flush latency); the 'saved … (%.1fs)' log reads as video length — consider reporting frames/fps. E2E now asserts |container - frames/fps| <= 0.1 and -0.5 <= container - playback <= 2.0 (empirical bound).
FINAL: micro follow-up re-review clean (1ef4387..9eeae44) — READY TO MERGE. Suite on 9eeae44: 185 pure + 28 win32/integration passed, 0 skipped.
