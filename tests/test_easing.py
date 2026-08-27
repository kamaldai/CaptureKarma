import pytest

from capturekarma.motion.easing import EASINGS, get_easing
from capturekarma.scene.model import EASING_NAMES


def test_all_scene_easing_names_exist():
    assert set(EASING_NAMES) == set(EASINGS)


@pytest.mark.parametrize("name", EASING_NAMES)
def test_easing_endpoints_and_monotonic(name):
    f = get_easing(name)
    assert f(0.0) == pytest.approx(0.0) and f(1.0) == pytest.approx(1.0)
    xs = [i / 200 for i in range(201)]
    ys = [f(x) for x in xs]
    assert all(b >= a - 1e-12 for a, b in zip(ys, ys[1:]))


def test_unknown_easing():
    with pytest.raises(ValueError, match="bouncy"):
        get_easing("bouncy")
