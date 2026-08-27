"""PyInstaller entry point for `CaptureKarma.exe` (windowed).

Nothing may import `playwright` or `imageio_ffmpeg` before `bootstrap()` has run, so the real
`main()` is imported after it rather than at the top of the file.
"""
from capturekarma._frozen import bootstrap, maybe_run_chromium_probe

bootstrap()
maybe_run_chromium_probe()

from capturekarma.gui.app import main  # noqa: E402 - must follow bootstrap()

if __name__ == "__main__":
    main()
