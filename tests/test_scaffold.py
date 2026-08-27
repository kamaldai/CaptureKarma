import capturekarma
from capturekarma import _win


def test_version():
    assert capturekarma.__version__.startswith("2.")


def test_high_res_timer_is_a_context_manager():
    with _win.high_res_timer():
        pass


def test_set_dpi_awareness_returns_bool():
    assert isinstance(_win.set_dpi_awareness(), bool)
