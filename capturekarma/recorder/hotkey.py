"""Global stop hotkey (F9 / Esc) via pynput. Works while another window has focus."""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("capturekarma.recorder")


class StopHotkey:
    def __init__(self, keys: tuple[str, ...] = ("f9", "esc")):
        self._names = set(keys)
        self.triggered = threading.Event()
        self._listener = None

    def start(self) -> None:
        from pynput import keyboard

        wanted = {getattr(keyboard.Key, n) for n in self._names if hasattr(keyboard.Key, n)}

        def on_press(key):
            if key in wanted:
                log.info("stop hotkey pressed")
                self.triggered.set()

        self._listener = keyboard.Listener(on_press=on_press)
        self._listener.daemon = True
        self._listener.start()

    def is_set(self) -> bool:
        return self.triggered.is_set()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
