from .desktop import DesktopRecorder, record_desktop
from .events import RawEvent
from .hotkey import StopHotkey
from .smooth import SmoothConfig, smooth
from .web import WebRecorder, record_web

__all__ = ["RawEvent", "StopHotkey", "SmoothConfig", "smooth", "WebRecorder", "record_web",
           "DesktopRecorder", "record_desktop"]
