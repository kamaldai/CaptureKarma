"""Easing functions [0,1] -> [0,1]. Names must match scene.model.EASING_NAMES."""
from __future__ import annotations

from typing import Callable

Easing = Callable[[float], float]


def linear(t: float) -> float:
    return t


def ease_in_out_cubic(t: float) -> float:
    return 4 * t * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 3) / 2


def ease_out_cubic(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in_out_quint(t: float) -> float:
    return 16 * t ** 5 if t < 0.5 else 1 - ((-2 * t + 2) ** 5) / 2


EASINGS: dict[str, Easing] = {
    "linear": linear,
    "ease_in_out_cubic": ease_in_out_cubic,
    "ease_out_cubic": ease_out_cubic,
    "ease_in_out_quint": ease_in_out_quint,
}


def get_easing(name: str) -> Easing:
    try:
        return EASINGS[name]
    except KeyError:
        raise ValueError(f"unknown easing {name!r}; choose from {', '.join(EASINGS)}") from None
