"""Monitor enumeration in physical pixels (requires DPI awareness set first)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from capturekarma._win import IS_WINDOWS
from capturekarma.scene.model import Region

log = logging.getLogger("capturekarma.capture")


class CaptureError(Exception):
    """Raised for capture setup/runtime failures (monitors, ffmpeg)."""


@dataclass(frozen=True)
class Monitor:
    index: int          # DXGI output index on adapter 0 == EnumDisplayMonitors order (single-GPU assumption)
    region: Region      # physical px, virtual-screen coordinates
    primary: bool
    rotated: bool = False   # display orientation != DMDO_DEFAULT; ddagrab ignores rotation, so these need gdigrab


def list_monitors() -> list[Monitor]:
    if not IS_WINDOWS:
        raise CaptureError("monitor enumeration requires Windows")
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    MONITORINFOF_PRIMARY = 1
    ENUM_CURRENT_SETTINGS = -1
    DMDO_DEFAULT = 0

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

    class POINTL(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class DEVMODEW(ctypes.Structure):
        # The dmPosition/dmDisplayOrientation/dmDisplayFixedOutput triple is the display variant of
        # DEVMODEW's printer union; it has the same size and alignment as the printer variant, so the
        # flattened layout below still matches the documented sizeof(DEVMODEW) == 220.
        _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                    ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD),
                    ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
                    ("dmPosition", POINTL), ("dmDisplayOrientation", wintypes.DWORD),
                    ("dmDisplayFixedOutput", wintypes.DWORD), ("dmColor", wintypes.SHORT),
                    ("dmDuplex", wintypes.SHORT), ("dmYResolution", wintypes.SHORT),
                    ("dmTTOption", wintypes.SHORT), ("dmCollate", wintypes.SHORT),
                    ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD),
                    ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                    ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                    ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                    ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD),
                    ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD),
                    ("dmReserved2", wintypes.DWORD), ("dmPanningWidth", wintypes.DWORD),
                    ("dmPanningHeight", wintypes.DWORD)]

    user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW)]
    user32.EnumDisplaySettingsW.restype = wintypes.BOOL

    def is_rotated(device: str) -> bool:
        """True if the display is turned 90/180/270 degrees. False (with a debug log) if unknown."""
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if not user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
            log.debug("EnumDisplaySettingsW failed for %s; assuming unrotated", device)
            return False
        return dm.dmDisplayOrientation != DMDO_DEFAULT

    MonitorEnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                         ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    found: list[Monitor] = []

    def cb(hmon, hdc, lprc, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            found.append(Monitor(len(found), Region(r.left, r.top, r.right - r.left, r.bottom - r.top),
                                 bool(info.dwFlags & MONITORINFOF_PRIMARY), is_rotated(info.szDevice)))
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
