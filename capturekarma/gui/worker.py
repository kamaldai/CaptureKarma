"""Background QThread that runs one library call and relays its logs/result as Qt signals."""
from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QThread, Signal


class _QtLogHandler(logging.Handler):
    def __init__(self, emit: Callable[[str], None]):
        super().__init__(level=logging.INFO)
        self._emit = emit

    def emit(self, record: logging.LogRecord) -> None:
        self._emit(self.format(record))


class Worker(QThread):
    """Runs a blocking callable off the UI thread; relays library logs and the result via signals."""

    log = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], object]):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        handler = _QtLogHandler(self.log.emit)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        lib_logger = logging.getLogger("capturekarma")
        if lib_logger.level == logging.NOTSET:
            # Otherwise it inherits root's WARNING and the library's INFO progress lines never
            # reach the handler, leaving the panel silent for a whole run.
            lib_logger.setLevel(logging.INFO)
        lib_logger.addHandler(handler)
        try:
            self.done.emit(self._fn())
        except Exception as exc:  # noqa: BLE001 - every failure must reach the UI log
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            lib_logger.removeHandler(handler)
