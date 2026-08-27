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
    ERROR_ACCESS_DENIED, S_OK, E_ACCESSDENIED = 5, 0, 0x80070005
    try:
        if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return True
        # ERROR_ACCESS_DENIED means awareness was already set for this process.
        if ctypes.GetLastError() == ERROR_ACCESS_DENIED:
            return True
    except AttributeError:
        pass  # pre-1703 Windows: fall through to shcore
    try:
        hr = ctypes.windll.shcore.SetProcessDpiAwareness(2) & 0xFFFFFFFF  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception as exc:  # noqa: BLE001 - reported to caller via return value
        log.warning("Could not set DPI awareness: %s", exc)
        return False
    if hr in (S_OK, E_ACCESSDENIED):  # E_ACCESSDENIED: already set, which is what we wanted
        return True
    log.warning("SetProcessDpiAwareness failed with HRESULT 0x%08X", hr)
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
