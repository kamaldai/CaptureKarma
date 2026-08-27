from capturekarma.recorder.events import RawEvent
from capturekarma.recorder.smooth import SmoothConfig, smooth
from capturekarma.scene.model import (
    ClickStep, DragStep, MoveStep, PressStep, ScrollStep, StepTarget, TypeStep, WaitStep, WheelStep,
)


def test_click_becomes_move_then_click():
    steps = smooth([RawEvent(t=0.1, kind="click", selector="#a", at=(10, 10))])
    assert steps == [MoveStep(to=StepTarget(selector="#a")), ClickStep()]


def test_click_without_selector_uses_at():
    steps = smooth([RawEvent(t=0.1, kind="click", at=(10, 10), button="right")])
    assert steps == [MoveStep(to=StepTarget(at=(10, 10))), ClickStep(button="right")]


def test_gaps_become_capped_waits():
    steps = smooth([RawEvent(t=5.0, kind="click", at=(1, 1)), RawEvent(t=5.5, kind="click", at=(2, 2)),
                    RawEvent(t=5.6, kind="click", at=(3, 3))])
    # The leading 5.0 s is the app's load time, not a pause: it is written out in full (see below).
    assert steps[0] == WaitStep(seconds=5.0)
    assert steps[3] == WaitStep(seconds=0.5)               # 0.5 s gap kept
    assert not isinstance(steps[6], WaitStep) and len(steps) == 8   # 0.1 s gap dropped (< min_wait)


def test_the_first_wait_is_the_load_time_and_is_never_capped():
    """Capping it made playback reach for elements a slow single-page app had not painted yet."""
    steps = smooth([RawEvent(t=7.3, kind="click", at=(1, 1)),      # 7.3 s of loading
                    RawEvent(t=12.3, kind="click", at=(2, 2))])    # then a 5 s human pause
    assert steps[0] == WaitStep(seconds=7.3)
    assert steps[3] == WaitStep(seconds=2.0)


def test_a_short_first_gap_is_still_dropped():
    steps = smooth([RawEvent(t=0.2, kind="click", at=(1, 1))])
    assert not any(isinstance(s, WaitStep) for s in steps)


def test_only_the_leading_gap_is_uncapped_not_the_first_gap_of_each_kind():
    """`first` means "nothing emitted yet", not "first scroll" - a mid-scene pause still caps."""
    steps = smooth([RawEvent(t=0.1, kind="click", at=(1, 1)),
                    RawEvent(t=9.1, kind="scroll", delta=100)])
    assert steps == [MoveStep(to=StepTarget(at=(1, 1))), ClickStep(),
                     WaitStep(seconds=2.0), ScrollStep(by=100)]


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


def test_drag_becomes_a_move_to_the_start_then_a_drag():
    ev = [RawEvent(t=0.1, kind="drag", path=((100, 100), (140, 130), (200, 120)), duration=1.2)]
    steps = smooth(ev)
    assert steps == [MoveStep(to=StepTarget(at=(100, 100))),
                     DragStep(path=((100, 100), (140, 130), (200, 120)), duration=1.2)]


def test_drag_duration_is_clamped_and_button_kept():
    fast = smooth([RawEvent(t=0.1, kind="drag", path=((0, 0), (5, 5)), duration=0.12, button="right")])
    assert fast[1] == DragStep(path=((0, 0), (5, 5)), duration=0.6, button="right")
    slow = smooth([RawEvent(t=0.1, kind="drag", path=((0, 0), (5, 5)), duration=30.0)])
    assert slow[1] == DragStep(path=((0, 0), (5, 5)), duration=6.0)


def test_drag_gaps_become_waits_like_any_other_event():
    ev = [RawEvent(t=0.1, kind="click", at=(1, 1)),
          RawEvent(t=3.1, kind="drag", path=((10, 10), (20, 20)), duration=0.8)]
    steps = smooth(ev)
    assert steps[2] == WaitStep(seconds=2.0)
    assert isinstance(steps[4], DragStep)


def test_wheel_bursts_merge_when_close_in_time_and_place():
    ev = [RawEvent(t=0.10, kind="wheel", delta=-120, at=(500, 300)),
          RawEvent(t=0.20, kind="wheel", delta=-120, at=(510, 320)),   # 22 px away: same gesture
          RawEvent(t=0.60, kind="wheel", delta=-100, at=(505, 305)),   # 0.4 s later: new step
          RawEvent(t=0.70, kind="wheel", delta=200, at=(900, 100))]    # far away: new step
    steps = smooth(ev)
    assert steps == [WheelStep(by=-240, at=StepTarget(at=(500, 300))),
                     WaitStep(seconds=0.4),                              # the burst gap is a real pause
                     WheelStep(by=-100, at=StepTarget(at=(505, 305))),
                     WheelStep(by=200, at=StepTarget(at=(900, 100)))]


def test_wheel_burst_summing_to_zero_is_dropped():
    ev = [RawEvent(t=0.1, kind="wheel", delta=120, at=(10, 10)),
          RawEvent(t=0.2, kind="wheel", delta=-120, at=(10, 10))]
    assert smooth(ev) == []


def test_wheel_never_merges_into_a_scroll():
    ev = [RawEvent(t=0.10, kind="scroll", delta=100),
          RawEvent(t=0.20, kind="wheel", delta=-120, at=(10, 10))]
    steps = smooth(ev)
    assert steps == [ScrollStep(by=100), WheelStep(by=-120, at=StepTarget(at=(10, 10)))]
