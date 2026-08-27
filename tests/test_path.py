import pytest

from capturekarma.motion.easing import get_easing
from capturekarma.motion.path import bezier_path, move_duration, scroll_duration


def test_move_duration_clamps():
    assert move_duration(0, 1400) == 0.35
    assert move_duration(1400, 1400) == pytest.approx(1.0)
    assert move_duration(100000, 1400) == 2.0


def test_scroll_duration_clamps():
    assert scroll_duration(0) == 0.5
    assert scroll_duration(900) == pytest.approx(1.0)
    assert scroll_duration(-900) == pytest.approx(1.0)
    assert scroll_duration(100000) == 4.0


def test_bezier_path_shape():
    e = get_easing("ease_in_out_cubic")
    pts = bezier_path((0, 0), (600, 0), 120, e, index=0)
    assert len(pts) == 120
    assert pts[-1] == (600, 0)
    assert all(isinstance(p[0], int) and isinstance(p[1], int) for p in pts)
    # arcs off the chord: some points have non-zero y, and they bulge to one side only
    ys = [p[1] for p in pts]
    assert max(abs(y) for y in ys) > 5
    assert (min(ys) >= 0) or (max(ys) <= 0)


def test_bezier_alternates_side_by_index():
    e = get_easing("linear")
    a = bezier_path((0, 0), (600, 0), 60, e, index=0)
    b = bezier_path((0, 0), (600, 0), 60, e, index=1)
    assert a[30][1] == -b[30][1] != 0


def test_bezier_is_deterministic_and_zero_distance():
    e = get_easing("linear")
    assert bezier_path((10, 10), (500, 300), 50, e, 3) == bezier_path((10, 10), (500, 300), 50, e, 3)
    assert bezier_path((7, 7), (7, 7), 5, e, 0) == [(7, 7)] * 5


def test_bezier_x_progress_follows_easing():
    e = get_easing("ease_in_out_cubic")
    pts = bezier_path((0, 0), (1000, 0), 100, e, index=0)
    # at t=0.5 easing is 0.5 -> x≈500
    assert abs(pts[49][0] - 500) <= 15
    # first quarter moves less than middle quarter (ease-in)
    assert pts[24][0] - pts[0][0] < pts[74][0] - pts[49][0]
