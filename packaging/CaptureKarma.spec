# -*- mode: python ; coding: utf-8 -*-
"""One onedir bundle, two executables, one shared `_internal/`.

`CaptureKarma.exe` is the windowed GUI and `ck.exe` the console CLI. Both are analysed separately
(their import graphs differ: only the CLI pulls typer, only the GUI pulls PySide6) and handed to a
single COLLECT, which merges the two dependency sets into one `_internal/` directory.

Everything the app shells out to is bundled: Chromium (installed into the `playwright` package by
`build_windows.ps1` with `PLAYWRIGHT_BROWSERS_PATH=0`) and the `imageio-ffmpeg` binary.
`capturekarma._frozen.bootstrap()`, called first thing by both entry scripts, points the libraries
at them.

Build with `packaging/build_windows.ps1`, not by hand: the spec alone does not install Chromium.
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH is injected by PyInstaller
PKG = ROOT / "capturekarma"

# Playwright ships its driver as data (node.exe, cli.js) and, after the install step, Chromium
# under driver/package/.local-browsers. Chromium's DLLs are deliberately kept in `datas` rather
# than `binaries`: entries in `binaries` are dependency-scanned and may be hoisted out of their
# directory, and Chromium only runs if its own layout survives intact.
pw_datas, pw_binaries, pw_hiddenimports = collect_all("playwright")
pw_datas += pw_binaries

datas = [
    *pw_datas,
    # imageio-ffmpeg's binaries/ dir: ffmpeg-win-x86_64-*.exe, with ddagrab, h264_nvenc, libx264.
    *collect_data_files("imageio_ffmpeg"),
    # Read at import time via Path(__file__).parent, so they must exist on disk beside the package.
    (str(PKG / "drivers" / "web_scroll.js"), "capturekarma/drivers"),
    (str(PKG / "recorder" / "web_recorder.js"), "capturekarma/recorder"),
    # Cursor styles: every PNG dropped in here becomes a --cursor-style value.
    (str(PKG / "cursor" / "assets"), "capturekarma/cursor/assets"),
    (str(ROOT / "examples"), "examples"),
    (str(ROOT / "README.md"), "."),
    (str(ROOT / "LICENSE"), "."),
]

hiddenimports = [
    *pw_hiddenimports,
    # pynput picks its backend at runtime from the platform, which static analysis cannot see.
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    # Imported lazily inside functions.
    "capturekarma.doctor",
    "capturekarma.gui.main_window",
    "capturekarma.gui.worker",
]

excludes = ["tkinter", "pytest", "_pytest", "setuptools", "pip"]

common = dict(
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

a_gui = Analysis([str(ROOT / "packaging" / "entry_gui.py")], binaries=[], **common)
a_cli = Analysis([str(ROOT / "packaging" / "entry_cli.py")], binaries=[], **common)

pyz_gui = PYZ(a_gui.pure)  # noqa: F821
pyz_cli = PYZ(a_cli.pure)  # noqa: F821

exe_gui = EXE(  # noqa: F821
    pyz_gui,
    a_gui.scripts,
    [],
    exclude_binaries=True,
    name="CaptureKarma",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "resources" / "app_icon.ico"),
)

exe_cli = EXE(  # noqa: F821
    pyz_cli,
    a_cli.scripts,
    [],
    exclude_binaries=True,
    name="ck",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "resources" / "app_icon.ico"),
)

coll = COLLECT(  # noqa: F821
    exe_gui,
    a_gui.binaries,
    a_gui.datas,
    exe_cli,
    a_cli.binaries,
    a_cli.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CaptureKarma",
)
