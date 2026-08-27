from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from capturekarma.scene.model import Point


@dataclass(frozen=True)
class RawEvent:
    """One thing the user did while recording. `t` is seconds since recording start."""
    t: float
    kind: Literal["click", "drag", "scroll", "wheel", "key", "navigate"]
    selector: str | None = None      # web click target
    at: Point | None = None          # web: viewport css px; desktop: region-relative px
    container: str | None = None     # web scroll container selector (None = page)
    delta: int = 0                   # scroll/wheel px, positive = down
    key: str | None = None           # key name (Playwright/W3C style: "a", "Enter", "Shift")
    url: str | None = None
    button: Literal["left", "right", "middle"] = "left"
    path: tuple[Point, ...] = ()     # drag: the sampled pointer path, first point == press point
    duration: float = 0.0            # drag: seconds between press and release
