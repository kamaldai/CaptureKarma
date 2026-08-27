import threading

import pytest

from capturekarma.recorder.events import RawEvent
from capturekarma.recorder.web import WebRecorder
from capturekarma.scene.model import ClickStep, MoveStep, ScrollStep, StepTarget, TypeStep

pytestmark = pytest.mark.integration


@pytest.fixture
def rec(fixture_url):
    r = WebRecorder(fixture_url, viewport=(1000, 600), headless=True)
    r.start()
    yield r
    r.stop()


def _kinds(events: list[RawEvent]) -> list[str]:
    return [e.kind for e in events]


def test_click_records_stable_selector(rec):
    rec.page.click("#btn-primary")
    rec.page.click("#btn-secondary")
    rec.page.click("text=Plain")
    rec.page.wait_for_timeout(200)
    clicks = [e for e in rec.events if e.kind == "click"]
    assert [c.selector for c in clicks] == ['[data-testid="primary"]', "#btn-secondary", "button.plain"]
    assert all(c.at is not None for c in clicks)


def test_scroll_and_keys_recorded(rec):
    # Order matters: type first and scroll the inner box before scrolling the page, so that
    # Playwright never has to auto-scroll an off-screen element into view (which would add
    # extra page-scroll events and break the exact sums below).
    rec.page.click("#email")
    rec.page.keyboard.type("ab")
    rec.page.keyboard.press("Enter")
    rec.page.hover("#box")
    rec.page.mouse.wheel(0, 100)
    rec.page.wait_for_timeout(400)
    rec.page.mouse.move(900, 300)     # right of the box, over the page body
    rec.page.mouse.wheel(0, 400)
    rec.page.wait_for_timeout(400)
    kinds = _kinds(rec.events)
    assert "scroll" in kinds and "key" in kinds
    page_scroll = sum(e.delta for e in rec.events if e.kind == "scroll" and e.container is None)
    assert page_scroll == 400
    box_scroll = sum(e.delta for e in rec.events if e.kind == "scroll" and e.container == "#box")
    assert box_scroll == 100
    assert [e.key for e in rec.events if e.kind == "key"] == ["a", "b", "Enter"]


def test_to_scene_produces_valid_steps(rec):
    rec.page.click("#btn-primary")
    rec.page.click("#email")
    rec.page.keyboard.type("x")
    rec.page.mouse.move(900, 300)
    rec.page.mouse.wheel(0, 300)
    rec.page.wait_for_timeout(400)
    scene = rec.to_scene("t")
    assert scene.target.kind == "web" and scene.target.viewport == (1000, 600)
    kinds = [type(s) for s in scene.steps]
    assert kinds.count(MoveStep) == 2 and kinds.count(ClickStep) == 2 and ScrollStep in kinds and TypeStep in kinds
    assert MoveStep(to=StepTarget(selector='[data-testid="primary"]')) in scene.steps


def test_wait_returns_when_stop_set(rec):
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    rec.wait(stop)  # must return promptly


def test_wait_dispatches_events_live(rec):
    # Playwright's sync API only dispatches browser events while the calling thread is inside a
    # Playwright call, so wait() has to keep pumping: otherwise every action performed during a
    # recording session arrives in one burst at stop() time with a collapsed timestamp.
    rec.page.evaluate("setTimeout(() => document.querySelector('#btn-primary').click(), 200)")
    stop = threading.Event()
    threading.Timer(1.0, stop.set).start()
    rec.wait(stop)
    clicks = [e for e in rec.events if e.kind == "click"]
    assert len(clicks) == 1
    assert clicks[0].t < 0.7


def test_password_input_keystrokes_are_never_recorded(rec):
    rec.page.click("#pw")
    rec.page.keyboard.type("hunter2")
    rec.page.keyboard.press("Enter")
    rec.page.wait_for_timeout(200)
    assert [e for e in rec.events if e.kind == "key"] == []
    assert any(e.kind == "click" for e in rec.events)     # the click itself is still recorded


def test_stop_keys_are_never_recorded(rec):
    rec.page.click("#email")
    rec.page.keyboard.press("F9")
    rec.page.keyboard.press("Escape")
    rec.page.keyboard.type("a")
    rec.page.wait_for_timeout(200)
    assert [e.key for e in rec.events if e.kind == "key"] == ["a"]


def test_recorded_scene_survives_a_dump_load_round_trip(rec, tmp_path):
    from capturekarma.scene import dump_scene, load_scene

    rec.page.click("#btn-primary")
    rec.page.click("#email")
    rec.page.keyboard.type("x")
    rec.page.mouse.move(900, 300)
    rec.page.mouse.wheel(0, 300)
    rec.page.wait_for_timeout(400)
    scene = rec.to_scene("round-trip")     # url is already a file:/// URI, so load_scene leaves it alone
    path = tmp_path / "round-trip.yaml"
    dump_scene(scene, path)
    assert load_scene(path) == scene


def _stage_center(rec):
    box = rec.page.locator("#stage").bounding_box()
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def test_a_drag_on_the_canvas_is_recorded_as_a_drag_not_a_click(rec):
    cx, cy = _stage_center(rec)
    rec.page.mouse.move(cx, cy)
    rec.page.mouse.down()
    for dx in (30, 60, 90, 120):
        rec.page.mouse.move(cx + dx, cy + dx / 3)
        rec.page.wait_for_timeout(50)
    rec.page.mouse.up()
    rec.page.wait_for_timeout(300)
    kinds = _kinds(rec.events)
    assert kinds.count("drag") == 1
    assert "click" not in kinds            # the synthetic click after the drag is suppressed
    drag = next(e for e in rec.events if e.kind == "drag")
    assert len(drag.path) >= 3
    assert drag.path[0] == (round(cx), round(cy))
    assert drag.path[-1] == (round(cx) + 120, round(cy) + 40)
    assert drag.button == "left" and drag.duration > 0


def test_a_press_and_release_in_place_is_still_a_click(rec):
    rec.page.click("#btn-primary")
    rec.page.wait_for_timeout(300)
    kinds = _kinds(rec.events)
    assert kinds.count("click") == 1 and "drag" not in kinds


def test_a_wheel_over_a_zooming_canvas_is_recorded_as_a_wheel(rec):
    # Scroll *down*: the page is at the top of a 4000 px body, so it would certainly have moved had
    # the canvas not swallowed the event. A negative delta would prove nothing - the page is
    # already at offset 0 and could not scroll up regardless.
    assert rec.page.evaluate("window.scrollY") == 0
    cx, cy = _stage_center(rec)
    rec.page.mouse.move(cx, cy)
    rec.page.mouse.wheel(0, 120)
    rec.page.mouse.wheel(0, 120)
    rec.page.wait_for_timeout(400)
    wheels = [e for e in rec.events if e.kind == "wheel"]
    assert len(wheels) == 1 and wheels[0].delta == 240
    assert wheels[0].at == (round(cx), round(cy))
    assert rec.page.evaluate("window.scrollY") == 0             # the page really never moved
    assert not [e for e in rec.events if e.kind == "scroll"]


def test_a_wheel_that_scrolls_the_page_is_not_recorded_as_a_wheel(rec):
    rec.page.mouse.move(900, 300)     # page body, right of everything
    rec.page.mouse.wheel(0, 400)
    rec.page.wait_for_timeout(400)
    kinds = _kinds(rec.events)
    assert "wheel" not in kinds
    assert sum(e.delta for e in rec.events if e.kind == "scroll") == 400


def test_canvas_drag_and_wheel_replay_through_the_driver(fixture_url):
    """End-to-end: record a drag + a wheel on the canvas, then play the scene back into it.

    The recorder is stopped before the driver starts: Playwright's sync API refuses a second
    instance in the same thread while the first is still running.
    """
    from capturekarma.drivers.web import WebDriver
    from capturekarma.motion import get_easing, polyline_path
    from capturekarma.scene.model import DragStep, MoveStep, WheelStep

    rec = WebRecorder(fixture_url, viewport=(1000, 600), headless=True)
    rec.start()
    try:
        cx, cy = _stage_center(rec)
        rec.page.mouse.move(cx, cy)
        rec.page.mouse.down()
        for dx in (40, 80, 120):
            rec.page.mouse.move(cx + dx, cy + 20)
            rec.page.wait_for_timeout(60)
        rec.page.mouse.up()
        rec.page.wait_for_timeout(250)
        rec.page.mouse.wheel(0, -240)
        rec.page.wait_for_timeout(400)
        recorded = rec.page.evaluate("[window.__stage.dx, window.__stage.dy, window.__stage.wheel]")
        scene = rec.to_scene("canvas")
    finally:
        rec.stop()
    assert recorded == [120, 20, -240]

    kinds = [type(s) for s in scene.steps]
    assert MoveStep in kinds and DragStep in kinds and WheelStep in kinds
    drag = next(s for s in scene.steps if isinstance(s, DragStep))
    wheel = next(s for s in scene.steps if isinstance(s, WheelStep))
    assert wheel.by == -240

    d = WebDriver(headless=True)
    try:
        d.setup(scene)
        # Replayed at driver level: the player's own motion is covered by tests/test_player.py.
        pts = polyline_path([d.resolve(StepTarget(at=p)) for p in drag.path], 12,
                            get_easing("ease_in_out_cubic"))
        d.pointer_to(*pts[0])
        d.mouse_down(drag.button)
        for pt in pts:
            d.pointer_to(*pt)
        d.mouse_up(drag.button)
        d.pointer_to(*d.resolve(wheel.at))
        d.smooth_wheel(wheel, duration=0.2, easing=get_easing("linear"))
        played = d.page.evaluate("[window.__stage.dx, window.__stage.dy, window.__stage.wheel]")
    finally:
        d.teardown()
    assert played == recorded


def test_multiline_button_text_is_normalised_into_a_selector_that_resolves(rec):
    """The old recorder wrote raw innerText, newlines and all: unquotable, and it matched nothing.

    Playwright's :has-text() searches the element's whitespace-normalised *textContent*, so that
    is what has to be written out - here "3Steps", since a <br> contributes nothing to textContent.
    """
    rec.page.click("text=Steps")
    rec.page.wait_for_timeout(200)
    clicks = [e for e in rec.events if e.kind == "click"]
    assert [c.selector for c in clicks] == ['button:has-text("3Steps")']
    sel = clicks[0].selector
    assert "\n" not in sel
    assert rec.page.locator(sel).count() == 1        # and Playwright really resolves it


def test_text_selectors_are_only_used_when_the_substring_match_is_unique(rec):
    """:has-text() is a substring match: a label contained in another button's label is unusable."""
    rec.page.evaluate("document.body.insertAdjacentHTML('beforeend',"
                      "'<button><span>3</span><br>Steps and more</button>')")
    rec.page.locator("button", has_text="3Steps").first.click()   # the original "3Steps" button
    rec.page.wait_for_timeout(200)
    sel = [e for e in rec.events if e.kind == "click"][-1].selector
    # "3Steps and more" also contains "3Steps", so :has-text("3Steps") would be ambiguous
    assert sel is not None and not sel.startswith("button:has-text(")
    assert rec.page.locator(sel).count() == 1

    # the longer label is still unique on its own, and is still used
    rec.page.locator("button", has_text="3Steps and more").click()
    rec.page.wait_for_timeout(200)
    sel = [e for e in rec.events if e.kind == "click"][-1].selector
    assert sel == 'button:has-text("3Steps and more")'
    assert rec.page.locator(sel).count() == 1


def test_the_recorded_scene_carries_the_measured_viewport(rec):
    measured = tuple(rec.page.evaluate("[window.innerWidth, window.innerHeight]"))
    assert rec.actual_viewport == measured
    assert rec.to_scene("t").target.viewport == measured


def test_a_right_button_drag_does_not_swallow_the_next_real_click(rec):
    """No synthetic click follows a right/middle drag, so arming suppressClick would eat the next one."""
    cx, cy = _stage_center(rec)
    rec.page.mouse.move(cx, cy)
    rec.page.mouse.down(button="right")
    for dx in (30, 60, 90):
        rec.page.mouse.move(cx + dx, cy)
        rec.page.wait_for_timeout(50)
    rec.page.mouse.up(button="right")
    rec.page.wait_for_timeout(250)
    rec.page.click("#btn-primary")
    rec.page.wait_for_timeout(250)
    kinds = _kinds(rec.events)
    assert kinds.count("drag") == 1
    assert [e.button for e in rec.events if e.kind == "drag"] == ["right"]
    clicks = [e for e in rec.events if e.kind == "click"]
    assert [c.selector for c in clicks] == ['[data-testid="primary"]']   # the real click survived


def test_a_cancelled_drag_does_not_swallow_the_next_real_click(rec):
    cx, cy = _stage_center(rec)
    rec.page.mouse.move(cx, cy)
    rec.page.mouse.down()
    rec.page.mouse.move(cx + 80, cy + 10)
    rec.page.wait_for_timeout(60)
    rec.page.evaluate("window.dispatchEvent(new Event('blur'))")   # alt-tab mid-gesture
    rec.page.mouse.up()
    rec.page.wait_for_timeout(250)
    rec.page.click("#btn-primary")
    rec.page.wait_for_timeout(250)
    assert "drag" not in _kinds(rec.events)                        # the half-gesture was discarded
    # With no drag recognised the gesture's own synthetic click is (correctly) kept as a click -
    # what matters is that the *following* real click was not swallowed by a stale suppress flag.
    assert [e.selector for e in rec.events if e.kind == "click"][-1] == '[data-testid="primary"]'
