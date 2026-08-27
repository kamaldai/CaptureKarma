"""Deterministic cursor paths and duration heuristics."""
from __future__ import annotations

import math

from capturekarma.scene.model import Point

from .easing import Easing


def move_duration(distance: float, speed: float, lo: float = 0.35, hi: float = 2.0) -> float:
    """Seconds for a cursor move: distance / speed clamped to [lo, hi]."""
    return max(lo, min(hi, distance / speed))


def scroll_duration(pixels: int, lo: float = 0.5, hi: float = 4.0, px_per_s: float = 900.0) -> float:
    return max(lo, min(hi, abs(pixels) / px_per_s))


def _cubic(p0: float, p1: float, p2: float, p3: float, t: float) -> float:
    u = 1 - t
    return u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3


def bezier_path(start: Point, end: Point, n_ticks: int, easing: Easing, index: int,
                curvature: float = 0.15) -> list[Point]:
    """Points along a cubic Bezier from start to end, one per tick.

    The chord is bowed perpendicular by `curvature * chord_length`; the side alternates with
    `index` parity so successive moves look natural but remain fully deterministic.
    Returns exactly n_ticks points; the last equals `end`.
    """
    n = max(1, n_ticks)
    (x0, y0), (x3, y3) = start, end
    dx, dy = x3 - x0, y3 - y0
    length = math.hypot(dx, dy)
    if length == 0:
        return [end] * n
    nx, ny = -dy / length, dx / length
    side = 1.0 if index % 2 == 0 else -1.0
    off = side * curvature * length
    c1 = (x0 + dx / 3 + nx * off, y0 + dy / 3 + ny * off)
    c2 = (x0 + 2 * dx / 3 + nx * off, y0 + 2 * dy / 3 + ny * off)
    pts: list[Point] = []
    for i in range(1, n + 1):
        t = easing(i / n)
        pts.append((round(_cubic(x0, c1[0], c2[0], x3, t)), round(_cubic(y0, c1[1], c2[1], y3, t))))
    pts[-1] = end
    return pts
