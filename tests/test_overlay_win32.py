import time

import pytest
from PIL import ImageGrab

from capturekarma._win import set_dpi_awareness
from capturekarma.cursor.overlay import CursorOverlay
from capturekarma.cursor.sprites import FRAME_SIZE

pytestmark = pytest.mark.win32


def test_overlay_draws_and_hides():
    set_dpi_awareness()
    ov = CursorOverlay(style="default", ripple=True, visible=True)
    ov.start()
    try:
        x, y = 300, 300
        ov.set_position(x, y)
        time.sleep(0.3)
        box = (x - FRAME_SIZE // 2, y - FRAME_SIZE // 2, x + FRAME_SIZE // 2, y + FRAME_SIZE // 2)
        shown = ImageGrab.grab(bbox=box, all_screens=True)
        ov.set_visible(False)
        time.sleep(0.3)
        hidden = ImageGrab.grab(bbox=box, all_screens=True)
        assert shown.tobytes() != hidden.tobytes()
        assert ov.position == (x, y) and ov.visible is False
    finally:
        ov.stop()
