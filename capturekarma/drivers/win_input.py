"""Win32 input and window helpers via ctypes. Pure helpers (parse_key, wheel_steps) work anywhere."""
from __future__ import annotations

import logging
import time
from typing import Callable, Iterator

from capturekarma._win import IS_WINDOWS
from capturekarma.scene.model import Region

from .base import WindowNotFound

log = logging.getLogger("capturekarma.drivers.win_input")

KEY_NAMES: dict[str, int] = {
    "Backspace": 0x08, "Tab": 0x09, "Enter": 0x0D, "Shift": 0x10, "Control": 0x11, "Alt": 0x12,
    "Escape": 0x1B, "Space": 0x20, "PageUp": 0x21, "PageDown": 0x22, "End": 0x23, "Home": 0x24,
    "ArrowLeft": 0x25, "ArrowUp": 0x26, "ArrowRight": 0x27, "ArrowDown": 0x28, "Delete": 0x2E,
    "Meta": 0x5B,
    **{f"F{i}": 0x6F + i for i in range(1, 13)},
}
_ALIASES = {"Ctrl": "Control", "Esc": "Escape", "Return": "Enter", "Win": "Meta", "Cmd": "Meta", "Del": "Delete",
            "Left": "ArrowLeft", "Right": "ArrowRight", "Up": "ArrowUp", "Down": "ArrowDown"}
_MODIFIERS = ("Control", "Shift", "Alt", "Meta")
WHEEL_DELTA = 120
PX_PER_NOTCH = 100  # approximate pixels one wheel notch scrolls in typical Windows apps


def parse_key(name: str) -> tuple[list[int], int]:
    """'Ctrl+Shift+a' -> ([VK_CONTROL, VK_SHIFT], VK 'A'). Single characters map to their VK via ord(upper)."""
    parts = [p.strip() for p in name.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"empty key name {name!r}")
    *mods, main = parts
    mod_vks: list[int] = []
    for m in mods:
        canon = _ALIASES.get(m, m)
        if canon not in _MODIFIERS:
            raise ValueError(f"unknown modifier {m!r} in {name!r}")
        mod_vks.append(KEY_NAMES[canon])
    main = _ALIASES.get(main, main)
    if main in KEY_NAMES:
        return mod_vks, KEY_NAMES[main]
    if len(main) == 1 and main.isascii() and main.isalnum():
        return mod_vks, ord(main.upper())
    raise ValueError(f"unknown key {main!r} in {name!r}")


def wheel_steps(total_px: int, n_ticks: int, easing: Callable[[float], float]) -> Iterator[int]:
    """Per-tick wheel deltas whose sum is exactly `round(-total_px * WHEEL_DELTA / PX_PER_NOTCH)`.

    `total_px` is positive for a downward scroll; wheel units use the opposite Windows sign
    (positive = up). One notch is WHEEL_DELTA units and moves PX_PER_NOTCH pixels, which is the
    same ratio the recorder uses to turn observed wheel events into pixels. Rounding carries over
    between ticks, so the deltas add up exactly however the easing distributes them.
    """
    total_units = round(-total_px * WHEEL_DELTA / PX_PER_NOTCH)
    emitted = 0
    for i in range(1, n_ticks + 1):
        target = round(total_units * easing(i / n_ticks))
        yield target - emitted
        emitted = target


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    ULONG_PTR = ctypes.c_size_t

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
    MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
    MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
    MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
    MOUSEEVENTF_WHEEL = 0x0800
    KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
    _BUTTON_FLAGS = {"left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
                     "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
                     "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP)}

    def _send(*inputs: INPUT) -> None:
        arr = (INPUT * len(inputs))(*inputs)
        sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            raise ctypes.WinError()

    def _mouse(flags: int, data: int = 0) -> INPUT:
        inp = INPUT(type=INPUT_MOUSE)
        inp.u.mi = MOUSEINPUT(0, 0, ctypes.c_uint32(data & 0xFFFFFFFF).value, flags, 0, 0)
        return inp

    def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
        return inp

    def set_cursor_pos(x: int, y: int) -> None:
        if not user32.SetCursorPos(int(x), int(y)):
            raise ctypes.WinError()

    def mouse_button(button: str, down: bool) -> None:
        d, u = _BUTTON_FLAGS[button]
        _send(_mouse(d if down else u))

    def wheel(delta: int) -> None:
        if delta:
            _send(_mouse(MOUSEEVENTF_WHEEL, delta))

    def type_text(text: str, delay: float, sleep: Callable[[float], None] = time.sleep) -> None:
        for ch in text:
            code = ord(ch)
            if code > 0xFFFF:  # surrogate pair for astral characters
                code -= 0x10000
                units = [0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)]
            else:
                units = [code]
            for u in units:
                _send(_key(0, u, KEYEVENTF_UNICODE), _key(0, u, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            if delay > 0:
                sleep(delay)

    def press_key(name: str) -> None:
        mods, vk = parse_key(name)
        downs = [_key(m) for m in mods] + [_key(vk)]
        ups = [_key(vk, 0, KEYEVENTF_KEYUP)] + [_key(m, 0, KEYEVENTF_KEYUP) for m in reversed(mods)]
        _send(*downs, *ups)

    def list_window_titles() -> list[str]:
        titles: list[str] = []
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    titles.append(buf.value)
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        return titles

    def find_window(substring: str) -> tuple[int, str]:
        matches: list[tuple[int, str]] = []
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                n = user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    user32.GetWindowTextW(hwnd, buf, n + 1)
                    if substring.lower() in buf.value.lower():
                        matches.append((hwnd, buf.value))
            return True

        user32.EnumWindows(EnumWindowsProc(cb), 0)
        if not matches:
            visible = "\n  ".join(list_window_titles())
            raise WindowNotFound(f"no visible window title contains {substring!r}. Visible windows:\n  {visible}")
        return matches[0]

    def get_foreground_window() -> int:
        """Handle of the window with keyboard focus; 0 when no window has it."""
        return int(user32.GetForegroundWindow() or 0)

    def window_client_region(hwnd: int) -> Region:
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError()
        pt = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(hwnd, ctypes.byref(pt)):
            raise ctypes.WinError()
        return Region(pt.x, pt.y, rect.right - rect.left, rect.bottom - rect.top)

    def focus_window(hwnd: int) -> None:
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        # Windows refuses SetForegroundWindow unless our process recently received input;
        # a synthetic ALT tap satisfies that rule.
        _send(_key(KEY_NAMES["Alt"]), _key(KEY_NAMES["Alt"], 0, KEYEVENTF_KEYUP))
        if not user32.SetForegroundWindow(hwnd):
            # Not fatal: SendInput is positional, so clicks and scrolls still land on the window
            # under the cursor. Keystrokes, however, go wherever the focus actually is.
            log.warning("SetForegroundWindow refused for hwnd %s; continuing", hwnd)
        time.sleep(0.15)
