"""Entry point for `ck-gui`: DPI awareness, a rotating log file, a QApplication, one window."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from capturekarma._win import set_dpi_awareness

LOG_DIR = Path("~/Videos/CaptureKarma")
LOG_NAME = "capturekarma.log"
log = logging.getLogger("capturekarma.gui")


def install_file_log(directory: Path | None = None) -> Path | None:
    """Tee the library's INFO log to a rotating file so a failed take stays diagnosable.

    The GUI's log panel is gone the moment the window closes, which is exactly when a marketing
    user asks what went wrong. Returns the log path, or None if it could not be opened (a
    read-only or missing Videos folder must never stop the app from starting).
    """
    d = Path(directory or LOG_DIR).expanduser()
    path = d / LOG_NAME
    lib_logger = logging.getLogger("capturekarma")
    if any(getattr(h, "baseFilename", None) == str(path) for h in lib_logger.handlers):
        return path                      # already installed (a second main() in the same process)
    try:
        d.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=3, encoding="utf-8", delay=True)
    except OSError as exc:
        log.warning("cannot open the log file %s: %s", path, exc)
        return None
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    lib_logger.addHandler(handler)
    lib_logger.setLevel(logging.INFO)
    return path


def main() -> None:
    set_dpi_awareness()
    logging.getLogger("capturekarma").setLevel(logging.INFO)  # so the log panel sees progress lines
    log_path = install_file_log()
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    scenes_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("~/Videos/CaptureKarma/scenes").expanduser()
    win = MainWindow(scenes_dir=scenes_dir)
    if log_path is not None:
        log.info("logging to %s", log_path)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
