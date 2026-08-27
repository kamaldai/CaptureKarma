"""Entry point for `ck-gui`: DPI awareness, a QApplication, one window."""
from __future__ import annotations

import sys
from pathlib import Path

from capturekarma._win import set_dpi_awareness


def main() -> None:
    set_dpi_awareness()
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(sys.argv)
    scenes_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("~/Videos/CaptureKarma/scenes").expanduser()
    win = MainWindow(scenes_dir=scenes_dir)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
