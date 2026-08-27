"""Pure tests for the viewport fitting helper and the recorder's measured-viewport bookkeeping."""
from capturekarma.capture.monitors import Monitor
from capturekarma.drivers.web import WINDOW_CHROME, fit_viewport_to_monitor
from capturekarma.recorder.web import WebRecorder
from capturekarma.scene.model import Region


def _monitors(*sizes):
    return [Monitor(index=i, region=Region(0, 0, w, h), primary=(i == 0)) for i, (w, h) in enumerate(sizes)]


def test_a_viewport_that_fits_is_left_alone():
    assert fit_viewport_to_monitor(1280, 720, monitors=_monitors((1920, 1080))) == (1280, 720)


def test_a_full_screen_viewport_shrinks_to_leave_room_for_the_browser_chrome():
    w, h = fit_viewport_to_monitor(1920, 1080, monitors=_monitors((1920, 1080)))
    assert (w, h) == (1920 - WINDOW_CHROME[0], 1080 - WINDOW_CHROME[1])


def test_only_the_oversized_axis_shrinks():
    assert fit_viewport_to_monitor(3000, 400, monitors=_monitors((1920, 1080))) == (1904, 400)


def test_the_primary_monitor_decides_not_the_first_one():
    mons = [Monitor(index=0, region=Region(0, 0, 3840, 2160), primary=False),
            Monitor(index=1, region=Region(0, 0, 1366, 768), primary=True)]
    assert fit_viewport_to_monitor(1920, 1080, monitors=mons) == (1350, 648)


def test_no_monitors_at_all_leaves_the_request_alone():
    assert fit_viewport_to_monitor(1920, 1080, monitors=[]) == (1920, 1080)


def test_to_scene_uses_the_measured_viewport_not_the_requested_one():
    rec = WebRecorder("https://example.com", viewport=(1920, 1080))
    assert rec.to_scene("t").target.viewport == (1920, 1080)   # nothing measured yet: fall back
    rec.actual_viewport = (1920, 1005)                         # what Chromium actually gave us
    assert rec.to_scene("t").target.viewport == (1920, 1005)
