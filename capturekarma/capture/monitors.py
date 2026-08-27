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
