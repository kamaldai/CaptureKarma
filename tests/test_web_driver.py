import pytest

from capturekarma.drivers.base import DriverError, StepError
from capturekarma.drivers.web import WebDriver
from capturekarma.motion.easing import get_easing
from capturekarma.scene.model import Scene, ScrollStep, StepTarget, Target

pytestmark = pytest.mark.integration


@pytest.fixture
def driver(fixture_url):
    d = WebDriver(headless=True)
    d.setup(Scene(name="t", target=Target(kind="web", url=fixture_url, viewport=(1000, 600)), steps=()))
    yield d
    d.teardown()


def test_setup_region_matches_viewport_times_dpr(driver):
    m = driver.metrics
    assert (m.css_w, m.css_h) == (1000, 600)
    r = driver.region
    assert r.width == round(1000 * m.dpr) and r.height == round(600 * m.dpr)


def test_resolve_selector_center_inside_region(driver):
    x, y = driver.resolve(StepTarget(selector="#btn-primary"))
    r = driver.region
    assert r.x <= x < r.right and r.y <= y < r.bottom
    box = driver.page.locator("#btn-primary").bounding_box()
    cx, cy = driver.to_css(x, y)
    assert abs(cx - (box["x"] + box["width"] / 2)) <= 1 and abs(cy - (box["y"] + box["height"] / 2)) <= 1


def test_resolve_at_and_roundtrip(driver):
    p = driver.resolve(StepTarget(at=(100, 50)))
    assert tuple(round(v) for v in driver.to_css(*p)) == (100, 50)


def test_resolve_offscreen_raises(driver):
    with pytest.raises(StepError, match="off-screen"):
        driver.resolve(StepTarget(selector="#deep"))


def test_resolve_missing_raises(driver):
    with pytest.raises(StepError, match="#nope"):
        driver.resolve(StepTarget(selector="#nope"))


def test_smooth_scroll_by_and_to(driver):
    e = get_easing("ease_in_out_cubic")
    driver.smooth_scroll(ScrollStep(by=500), duration=0.3, easing=e)
    assert driver.page.evaluate("window.scrollY") == 500
    driver.smooth_scroll(ScrollStep(to=100), duration=0.3, easing=e)
    assert driver.page.evaluate("window.scrollY") == 100
    driver.smooth_scroll(ScrollStep(by=400, container="#box"), duration=0.3, easing=e)
    assert driver.page.evaluate("document.querySelector('#box').scrollTop") == 400


def test_scroll_makes_deep_button_resolvable(driver):
    driver.smooth_scroll(ScrollStep(to=2800), duration=0.2, easing=get_easing("linear"))
    driver.resolve(StepTarget(selector="#deep"))  # no raise


def test_scroll_bad_container_raises_step_error(driver):
    with pytest.raises(StepError, match="scroll failed"):
        driver.smooth_scroll(ScrollStep(by=100, container="#no-such-box"), duration=0.1,
                             easing=get_easing("linear"))


def test_click_and_type(driver):
    x, y = driver.resolve(StepTarget(selector="#email"))
    driver.pointer_to(x, y)
    driver.mouse_down()
    driver.mouse_up()
    driver.type_text("hi@x.io", 0.0)
    assert driver.page.evaluate("document.querySelector('#email').value") == "hi@x.io"
    driver.press("Control+a")
    driver.press("Backspace")
    assert driver.page.evaluate("document.querySelector('#email').value") == ""


def test_screenshot(driver, tmp_path):
    driver.screenshot(tmp_path / "s.png")
    assert (tmp_path / "s.png").stat().st_size > 0


def test_coordinate_helpers_before_setup_raise():
    d = WebDriver(headless=True)
    with pytest.raises(Exception, match="not set up"):
        d.to_screen(0, 0)


def test_setup_tears_down_on_unexpected_error(fixture_url, monkeypatch):
    """A non-Playwright failure mid-setup must not leak the browser process."""
    def boom(self):
        raise KeyError("ow")

    monkeypatch.setattr(WebDriver, "_measure", boom)
    d = WebDriver(headless=True)
    with pytest.raises(KeyError, match="ow"):
        d.setup(Scene(name="t", target=Target(kind="web", url=fixture_url, viewport=(800, 600)),
                      steps=()))
    assert d.page is None and d._browser is None and d._context is None and d._pw is None


def test_setup_bad_url_raises_driver_error_and_tears_down():
    d = WebDriver(headless=True)
    with pytest.raises(DriverError, match="could not launch browser or open"):
        d.setup(Scene(name="t", target=Target(kind="web", url="http://127.0.0.1:9/",
                                              viewport=(800, 600)), steps=()))
    assert d.page is None and d._browser is None and d._context is None and d._pw is None


def test_malformed_selector_raises_step_error_not_a_playwright_error(driver):
    with pytest.raises(StepError, match="invalid or failing selector"):
        driver.resolve(StepTarget(selector="#btn-primary >>> :::"))
