"""Turn raw recorded events into clean scene steps. Pure function; no timing side effects."""
from __future__ import annotations

import math
from dataclasses import dataclass

from capturekarma.scene.model import (
    ClickStep, DragStep, MoveStep, Point, PressStep, ScrollStep, Step, StepTarget, TypeStep, WaitStep,
    WheelStep,
)

from .events import RawEvent

MODIFIER_KEYS = {"Shift", "Control", "Alt", "Meta", "CapsLock", "NumLock", "ScrollLock", "AltGraph"}


@dataclass(frozen=True)
class SmoothConfig:
    scroll_merge_window: float = 0.3   # scroll/wheel events closer than this merge into one step
    wheel_merge_radius: float = 40.0   # ... and only when they happened this close together on screen
    min_drag: float = 0.6              # a recorded drag never replays faster than this
    max_drag: float = 6.0              # ... nor slower
    max_wait: float = 2.0              # long pauses collapse to this - except the very first one
    min_wait: float = 0.3              # shorter pauses are dropped entirely, first one included
    type_gap: float = 1.0              # a pause longer than this splits typing into two steps
    type_delay: float = 0.05           # per-character delay written into type steps


def PRINTABLE_KEY(key: str) -> bool:
    return len(key) == 1 and key.isprintable()


def _near(a: Point | None, b: Point | None, radius: float) -> bool:
    """True when two wheel bursts happened at roughly the same place (so they are one gesture)."""
    if a is None or b is None:
        return a is b
    return math.dist(a, b) <= radius


def _wait(gap: float, cfg: SmoothConfig, first: bool = False) -> list[Step]:
    """A pause between events, capped at `max_wait` - unless it is the very first one.

    The gap from recording start to the first event is the app's *load time*, not a pause the
    presenter took: a 3D viewer can still be downloading its model ten seconds in. Capping it to
    2 s makes playback reach for an element the page has not painted yet, so the first wait is
    written out in full. Every later gap is a human pause and still collapses to `max_wait`.
    """
    if gap < cfg.min_wait:
        return []
    return [WaitStep(seconds=round(gap if first else min(gap, cfg.max_wait), 3))]


def smooth(events: list[RawEvent], config: SmoothConfig = SmoothConfig()) -> list[Step]:
    evs = sorted((e for e in events if e.kind != "navigate"), key=lambda e: e.t)
    steps: list[Step] = []
    last_t = 0.0
    i = 0
    while i < len(evs):
        e = evs[i]
        if e.kind == "click":
            steps += _wait(e.t - last_t, config, first=not steps)
            steps.append(MoveStep(to=StepTarget(selector=e.selector) if e.selector else StepTarget(at=e.at)))
            steps.append(ClickStep(button=e.button))
            last_t = e.t
            i += 1
        elif e.kind == "drag":
            steps += _wait(e.t - last_t, config, first=not steps)
            steps.append(MoveStep(to=StepTarget(at=e.path[0])))
            steps.append(DragStep(path=e.path,
                                  duration=round(max(config.min_drag, min(config.max_drag, e.duration)), 3),
                                  button=e.button))
            last_t = e.t
            i += 1
        elif e.kind == "wheel":
            steps += _wait(e.t - last_t, config, first=not steps)
            total, j = e.delta, i + 1
            while (j < len(evs) and evs[j].kind == "wheel"
                   and _near(evs[j].at, e.at, config.wheel_merge_radius)
                   and evs[j].t - evs[j - 1].t <= config.scroll_merge_window):
                total += evs[j].delta
                j += 1
            if total != 0:
                steps.append(WheelStep(by=total, at=StepTarget(at=e.at) if e.at else None))
            last_t = evs[j - 1].t
            i = j
        elif e.kind == "scroll":
            steps += _wait(e.t - last_t, config, first=not steps)
            total, j = e.delta, i + 1
            while (j < len(evs) and evs[j].kind == "scroll" and evs[j].container == e.container
                   and evs[j].t - evs[j - 1].t <= config.scroll_merge_window):
                total += evs[j].delta
                j += 1
            if total != 0:
                steps.append(ScrollStep(by=total, container=e.container))
            last_t = evs[j - 1].t
            i = j
        elif e.kind == "key":
            assert e.key is not None
            if e.key in MODIFIER_KEYS:
                i += 1
                continue
            steps += _wait(e.t - last_t, config, first=not steps)
            if PRINTABLE_KEY(e.key):
                text, j = e.key, i + 1
                while (j < len(evs) and evs[j].kind == "key" and evs[j].key is not None
                       and (PRINTABLE_KEY(evs[j].key) or evs[j].key in MODIFIER_KEYS)
                       and evs[j].t - evs[j - 1].t <= config.type_gap):
                    if PRINTABLE_KEY(evs[j].key):
                        text += evs[j].key
                    j += 1
                steps.append(TypeStep(text=text, delay=config.type_delay))
                last_t = evs[j - 1].t
                i = j
            else:
                steps.append(PressStep(key=e.key))
                last_t = e.t
                i += 1
        else:
            i += 1
    return steps
