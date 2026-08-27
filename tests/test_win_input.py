import pytest

from capturekarma.drivers.win_input import KEY_NAMES, parse_key, wheel_steps


def test_parse_simple_and_combo_keys():
    assert parse_key("Enter") == ([], KEY_NAMES["Enter"])
    mods, vk = parse_key("Ctrl+Shift+a")
    assert mods == [KEY_NAMES["Control"], KEY_NAMES["Shift"]] and vk == ord("A")
    assert parse_key("F5")[1] == KEY_NAMES["F5"]


def test_parse_unknown_key():
    with pytest.raises(ValueError, match="Hyper"):
        parse_key("Hyper")


def test_wheel_steps_quantize_with_carry():
    # 250 px down over 4 ticks with linear easing -> 250 * 1.2 = 300 wheel units, sign negative
    deltas = list(wheel_steps(total_px=250, n_ticks=4, easing=lambda t: t))
    assert len(deltas) == 4 and sum(deltas) == -300
    up = list(wheel_steps(total_px=-100, n_ticks=3, easing=lambda t: t))
    assert sum(up) == 120


def test_wheel_steps_sum_is_exact_when_ticks_do_not_divide_evenly():
    assert sum(wheel_steps(total_px=100, n_ticks=7, easing=lambda t: t)) == -120
