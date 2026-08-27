# Packaging report — self-contained Windows bundle (2026-08-27)

Built with `pwsh -File packaging/build_windows.ps1` (PyInstaller 6, onedir, two executables sharing `_internal/`).

- `dist/CaptureKarma/` — 781.3 MB unpacked (Chromium ≈ 535 MB, Qt, ffmpeg 7.1)
- `dist/CaptureKarma-2.0.0a1-win64.zip` — 339.5 MB

## Smoke tests on the reference machine (no venv, machine-wide PLAYWRIGHT_BROWSERS_PATH set)

`ck.exe doctor` → exit 0; every check OK; ffmpeg and Chromium resolve **inside** `_internal/`
(`_frozen.bootstrap()` overrides the inherited PLAYWRIGHT_BROWSERS_PATH when the bundle carries a browser).

`ck.exe play examples\web-demo.yaml` → `saved web-demo_20260827_202209.mp4 (21.8s, 1365 frames)`;
bundled ffmpeg reports `h264 (Main), yuv420p, 1280x720, 60 fps, 60 tbr`, container 22.75 s.

`CaptureKarma.exe` → window titled "CaptureKarma", process responding; closed cleanly.

## Problems hit
- A developer machine's user-level `PLAYWRIGHT_BROWSERS_PATH` made the frozen app look for Chromium outside the
  bundle; `bootstrap()` now forces `PLAYWRIGHT_BROWSERS_PATH=0` whenever `.local-browsers` is present in the bundle.
- `ck doctor`'s Chromium probe used `python -c`, which a frozen app lacks; the entry scripts answer a private
  `--ck-chromium-path` flag instead.
- The repo example points at `../tests/fixtures/page.html`; the build ships the fixture as `examples/page.html`
  and rewrites the shipped scene's `url:` (the repo copy is unchanged so tests stay green).
- The viewport-to-screen mapping was 8 px low on Windows 10 (bottom border counted as top chrome); fixed in
  `drivers/web.py` (commit e114d15) and verified by pixel-row measurement against the fixture header.

## Still manual
- The build is unsigned; SmartScreen will warn on first launch ("More info → Run anyway").
- Chromium inside the bundle is pinned to the Playwright release in `uv.lock`; rebuild to update it.
