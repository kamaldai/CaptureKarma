"""Transparent, click-through, always-on-top cursor overlay window (Win32, own thread)."""
from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
from typing import Literal

from capturekarma._win import IS_WINDOWS
from capturekarma.scene.model import Point

from .sprites import FRAME_SIZE, HOTSPOT, Ripple, load_sprite, prune_ripples, render_frame, to_premultiplied_bgra

log = logging.getLogger("capturekarma.cursor")

_Cmd = tuple[Literal["pos", "vis", "click", "stop"], object]
_class_seq = itertools.count()


class CursorOverlay:
    """Draws the rendered cursor (and click ripple) in a layered window that never takes focus."""

    def __init__(self, style: str = "default", ripple: bool = True, visible: bool = True):
        self._sprite = load_sprite(style)
        self._ripple_enabled = ripple
        self._visible = visible
        self._pos: Point = (0, 0)
        self._q: queue.Queue[_Cmd] = queue.Queue()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None

    # ---- public API (any thread) ----
    @property
    def position(self) -> Point:
        return self._pos

    @property
    def visible(self) -> bool:
        return self._visible

    def start(self) -> None:
        if not IS_WINDOWS:
            raise RuntimeError("CursorOverlay requires Windows")
        self._thread = threading.Thread(target=self._run, name="cursor-overlay", daemon=True)
        self._thread.start()
        if not self._ready.wait(5.0):
            raise RuntimeError("cursor overlay did not start")
        if self._error:
            raise RuntimeError(f"cursor overlay failed to start: {self._error!r}")

    def set_position(self, x: int, y: int) -> None:
        self._pos = (int(x), int(y))
        self._q.put(("pos", self._pos))

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        self._q.put(("vis", self._visible))

    def click(self) -> None:
        self._q.put(("click", None))

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._q.put(("stop", None))
            self._thread.join(timeout=3.0)

    # ---- window thread ----
    def _run(self) -> None:
        import ctypes
        from ctypes import wintypes

        # Private library handles so the restype/argtypes declarations below stay local to
        # this module and cannot surprise other ctypes users in the same process.
        user32 = ctypes.WinDLL("user32")
        gdi32 = ctypes.WinDLL("gdi32")
        kernel32 = ctypes.WinDLL("kernel32")

        WS_POPUP = 0x80000000
        WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x80000, 0x20, 0x8, 0x80
        WS_EX_NOACTIVATE = 0x08000000
        SW_SHOWNOACTIVATE, SW_HIDE = 4, 0
        ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 2, 0, 1
        PM_REMOVE = 1
        SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_NOZORDER = 0x1, 0x2, 0x10, 0x4
        HWND_TOPMOST = wintypes.HWND(-1)
        LRESULT = ctypes.c_ssize_t

        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                        ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                        ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]

        # Full prototypes are mandatory, not tidiness: the ctypes default of c_int both truncates
        # returned 64-bit handles and truncates handles passed back in, so an untyped call here
        # silently corrupts every HWND/HDC/HBITMAP on 64-bit Windows.
        P = ctypes.POINTER
        user32.DefWindowProcW.restype = LRESULT
        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.RegisterClassW.argtypes = [P(WNDCLASSW)]
        user32.UnregisterClassW.restype = wintypes.BOOL
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                           wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.UpdateLayeredWindow.restype = wintypes.BOOL
        user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, P(wintypes.POINT), P(wintypes.SIZE),
                                               wintypes.HDC, P(wintypes.POINT), wintypes.COLORREF,
                                               P(BLENDFUNCTION), wintypes.DWORD]
        user32.GetDC.restype = wintypes.HDC
        user32.GetDC.argtypes = [wintypes.HWND]
        user32.ReleaseDC.restype = ctypes.c_int
        user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        user32.PeekMessageW.restype = wintypes.BOOL
        user32.PeekMessageW.argtypes = [P(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [P(wintypes.MSG)]
        user32.DispatchMessageW.restype = LRESULT
        user32.DispatchMessageW.argtypes = [P(wintypes.MSG)]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi32.CreateDIBSection.restype = wintypes.HBITMAP
        gdi32.CreateDIBSection.argtypes = [wintypes.HDC, P(BITMAPINFO), wintypes.UINT, P(ctypes.c_void_p),
                                           wintypes.HANDLE, wintypes.DWORD]
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteDC.restype = wintypes.BOOL
        gdi32.DeleteDC.argtypes = [wintypes.HDC]

        def wndproc(hwnd, msg, wparam, lparam):
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        hwnd = None
        hdc_mem = None
        hbmp = None
        hbmp_old = None
        class_atom = 0
        class_name = ""
        hinstance = None
        try:
            user32.SetProcessDPIAware  # noqa: B018 - presence check only; awareness set by caller
            proc = WNDPROC(wndproc)
            cls = WNDCLASSW()
            cls.lpfnWndProc = proc
            hinstance = kernel32.GetModuleHandleW(None)
            cls.hInstance = hinstance
            class_name = f"CaptureKarmaCursor{id(self)}_{next(_class_seq)}"
            cls.lpszClassName = class_name
            class_atom = user32.RegisterClassW(ctypes.byref(cls))
            if not class_atom:
                raise ctypes.WinError()
            ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            hwnd = user32.CreateWindowExW(ex, class_name, "CaptureKarma Cursor", WS_POPUP,
                                          0, 0, FRAME_SIZE, FRAME_SIZE, None, None, hinstance, None)
            if not hwnd:
                raise ctypes.WinError()

            # 32-bpp top-down DIB section reused for every frame
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = FRAME_SIZE
            bmi.bmiHeader.biHeight = -FRAME_SIZE
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bits = ctypes.c_void_p()
            hdc_screen = user32.GetDC(None)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbmp = gdi32.CreateDIBSection(hdc_screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
            user32.ReleaseDC(None, hdc_screen)
            if not hdc_mem or not hbmp:
                raise ctypes.WinError()
            hbmp_old = gdi32.SelectObject(hdc_mem, hbmp)
            nbytes = FRAME_SIZE * FRAME_SIZE * 4

            blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
            size = wintypes.SIZE(FRAME_SIZE, FRAME_SIZE)
            pt_src = wintypes.POINT(0, 0)
            ripples: list[Ripple] = []
            visible = self._visible
            pos = self._pos

            def paint(now: float) -> None:
                frame = render_frame(self._sprite, ripples, now, self._ripple_enabled)
                ctypes.memmove(bits, to_premultiplied_bgra(frame), nbytes)
                dst = wintypes.POINT(pos[0] - HOTSPOT[0], pos[1] - HOTSPOT[1])
                if not user32.UpdateLayeredWindow(hwnd, None, ctypes.byref(dst), ctypes.byref(size), hdc_mem,
                                                  ctypes.byref(pt_src), 0, ctypes.byref(blend), ULW_ALPHA):
                    raise ctypes.WinError()

            paint(time.perf_counter())
            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)
            self._ready.set()

            msg = wintypes.MSG()
            running = True
            while running:
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                dirty = False
                try:
                    while True:
                        kind, val = self._q.get_nowait()
                        if kind == "pos":
                            pos = val  # type: ignore[assignment]
                            dirty = True
                        elif kind == "vis":
                            visible = bool(val)
                            user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE if visible else SW_HIDE)
                            dirty = True
                        elif kind == "click":
                            ripples.append(Ripple(time.perf_counter()))
                            dirty = True
                        elif kind == "stop":
                            running = False
                except queue.Empty:
                    pass
                now = time.perf_counter()
                if ripples:
                    ripples = prune_ripples(ripples, now)
                    dirty = True
                if dirty and running:
                    paint(now)
                    # SWP_NOMOVE is essential: without it this "nudge" would drag the window back to
                    # (0, 0) every frame, undoing the position UpdateLayeredWindow just applied.
                    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOZORDER)
                time.sleep(1 / 240)
        except BaseException as exc:  # noqa: BLE001 - surfaced to start() / logged
            self._error = exc
            log.error("cursor overlay thread failed: %r", exc)
            self._ready.set()
        finally:
            if hwnd:
                user32.DestroyWindow(hwnd)
            if hdc_mem and hbmp_old:
                gdi32.SelectObject(hdc_mem, hbmp_old)
            if hbmp:
                gdi32.DeleteObject(hbmp)
            if hdc_mem:
                gdi32.DeleteDC(hdc_mem)
            if class_atom:
                user32.UnregisterClassW(class_name, hinstance)
