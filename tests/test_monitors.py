import pytest

from capturekarma.capture.monitors import Monitor, monitor_for_region
from capturekarma.capture.recorder import CaptureError
from capturekarma.scene.model import Region

MONS = [Monitor(0, Region(0, 0, 2560, 1440), True), Monitor(1, Region(2560, 0, 1920, 1080), False)]


def test_region_inside_second_monitor():
    assert monitor_for_region(Region(2600, 10, 800, 600), MONS).index == 1


def test_monitor_rotated_defaults_false():
    assert Monitor(0, Region(0, 0, 1, 1), True).rotated is False


def test_region_spanning_monitors_is_error():
    with pytest.raises(CaptureError, match="single monitor"):
        monitor_for_region(Region(2000, 0, 1000, 500), MONS)


@pytest.mark.win32
def test_list_monitors_real():
    from capturekarma.capture.monitors import list_monitors
    mons = list_monitors()
    assert mons and any(m.primary for m in mons)
    assert all(m.region.width > 0 and m.region.height > 0 for m in mons)
    assert all(isinstance(m.rotated, bool) for m in mons)
    if any(m.region.height > m.region.width for m in mons):
        assert any(m.rotated for m in mons), "a portrait monitor must be reported as rotated"
