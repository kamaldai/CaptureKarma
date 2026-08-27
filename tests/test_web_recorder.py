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
