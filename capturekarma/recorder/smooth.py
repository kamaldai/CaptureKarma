"""Turn raw recorded events into clean scene steps. Pure function; no timing side effects."""
from __future__ import annotations

from dataclasses import dataclass

from capturekarma.scene.model import ClickStep, MoveStep, PressStep, ScrollStep, Step, StepTarget, TypeStep, WaitStep

from .events import RawEvent

MODIFIER_KEYS = {"Shift", "Control", "Alt", "Meta", "CapsLock", "NumLock", "ScrollLock", "AltGraph"}


@dataclass(frozen=True)
class SmoothConfig:
    scroll_merge_window: float = 0.3   # scroll events closer than this merge into one step
    max_wait: float = 2.0              # long pauses collapse to this
    min_wait: float = 0.3              # shorter pauses are dropped entirely
    type_gap: float = 1.0              # a pause longer than this splits typing into two steps
    type_delay: float = 0.05           # per-character delay written into type steps


def PRINTABLE_KEY(key: str) -> bool:
    return len(key) == 1 and key.isprintable()


def _wait(gap: float, cfg: SmoothConfig) -> list[Step]:
    if gap < cfg.min_wait:
        return []
    return [WaitStep(seconds=round(min(gap, cfg.max_wait), 3))]


def smooth(events: list[RawEvent], config: SmoothConfig = SmoothConfig()) -> list[Step]:
    evs = sorted((e for e in events if e.kind != "navigate"), key=lambda e: e.t)
    steps: list[Step] = []
    last_t = 0.0
    i = 0
    while i < len(evs):
        e = evs[i]
        if e.kind == "click":
            steps += _wait(e.t - last_t, config)
            steps.append(MoveStep(to=StepTarget(selector=e.selector) if e.selector else StepTarget(at=e.at)))
            steps.append(ClickStep(button=e.button))
            last_t = e.t
            i += 1
        elif e.kind == "scroll":
            steps += _wait(e.t - last_t, config)
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
            steps += _wait(e.t - last_t, config)
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
