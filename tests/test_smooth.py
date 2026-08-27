from capturekarma.recorder.events import RawEvent
from capturekarma.recorder.smooth import SmoothConfig, smooth
from capturekarma.scene.model import ClickStep, MoveStep, PressStep, ScrollStep, StepTarget, TypeStep, WaitStep


def test_click_becomes_move_then_click():
    steps = smooth([RawEvent(t=0.1, kind="click", selector="#a", at=(10, 10))])
    assert steps == [MoveStep(to=StepTarget(selector="#a")), ClickStep()]


def test_click_without_selector_uses_at():
    steps = smooth([RawEvent(t=0.1, kind="click", at=(10, 10), button="right")])
    assert steps == [MoveStep(to=StepTarget(at=(10, 10))), ClickStep(button="right")]


def test_gaps_become_capped_waits():
    steps = smooth([RawEvent(t=5.0, kind="click", at=(1, 1)), RawEvent(t=5.5, kind="click", at=(2, 2)),
                    RawEvent(t=5.6, kind="click", at=(3, 3))])
    assert steps[0] == WaitStep(seconds=2.0)               # 5.0 s gap capped
    assert steps[3] == WaitStep(seconds=0.5)               # 0.5 s gap kept
    assert not isinstance(steps[6], WaitStep) and len(steps) == 8   # 0.1 s gap dropped (< min_wait)


def test_scroll_bursts_merge_by_container():
    ev = [RawEvent(t=0.10, kind="scroll", delta=100), RawEvent(t=0.20, kind="scroll", delta=120),
          RawEvent(t=0.35, kind="scroll", delta=80),
          RawEvent(t=0.40, kind="scroll", delta=50, container="#box"),
          RawEvent(t=3.00, kind="scroll", delta=-200)]
    steps = smooth(ev)
    assert steps[0] == ScrollStep(by=300)                     # three page scrolls within 0.3 s merge
    assert steps[1] == ScrollStep(by=50, container="#box")    # different container -> separate step
    assert steps[2] == WaitStep(seconds=2.0)                  # 2.6 s gap capped to max_wait
    assert steps[3] == ScrollStep(by=-200)


def test_keys_group_into_type_and_press():
    ev = [RawEvent(t=0.1, kind="key", key="h"), RawEvent(t=0.2, kind="key", key="i"),
          RawEvent(t=0.3, kind="key", key="Shift"), RawEvent(t=0.4, kind="key", key="!"),
          RawEvent(t=0.5, kind="key", key="Enter"), RawEvent(t=2.1, kind="key", key="x")]
    steps = smooth(ev)
    assert steps == [TypeStep(text="hi!", delay=0.05), PressStep(key="Enter"), WaitStep(seconds=1.6),
                     TypeStep(text="x", delay=0.05)]


def test_typing_pause_splits_type_steps():
    ev = [RawEvent(t=1.0, kind="key", key="a"), RawEvent(t=2.5, kind="key", key="b")]
    assert smooth(ev, SmoothConfig(min_wait=5.0)) == [TypeStep(text="a"), TypeStep(text="b")]


def test_navigate_events_are_ignored_and_input_sorted():
    ev = [RawEvent(t=2.0, kind="click", at=(1, 1)), RawEvent(t=0.5, kind="navigate", url="x")]
    steps = smooth(ev)
    assert steps == [WaitStep(seconds=2.0), MoveStep(to=StepTarget(at=(1, 1))), ClickStep()]
