"""Scene data model. Frozen dataclasses; parsing/validation lives in loader.py."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

Point = tuple[int, int]

EASING_NAMES: tuple[str, ...] = ("linear", "ease_in_out_cubic", "ease_out_cubic", "ease_in_out_quint")


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return (self.x + self.width // 2, self.y + self.height // 2)

    def contains(self, other: "Region") -> bool:
        return (self.x <= other.x and self.y <= other.y
                and other.right <= self.right and other.bottom <= self.bottom)


@dataclass(frozen=True)
class Target:
    kind: Literal["web", "desktop"]
    url: str | None = None
    viewport: tuple[int, int] = (1920, 1080)
    window: str | None = None
    region: Region | None = None


@dataclass(frozen=True)
class Output:
    fps: int = 60
    dir: str = "~/Videos/CaptureKarma"
    lead_in: float = 0.5
    lead_out: float = 0.5


@dataclass(frozen=True)
class CursorConfig:
    visible: bool = True
    style: str = "default"
    ripple: bool = True
    speed: float = 1400.0


@dataclass(frozen=True)
class Defaults:
    easing: str = "ease_in_out_cubic"
    hold: float = 0.6


@dataclass(frozen=True)
class StepTarget:
    """Web: selector (Playwright) or `at` in viewport CSS px. Desktop: `at` region-relative px."""
    selector: str | None = None
    at: Point | None = None


@dataclass(frozen=True, kw_only=True)
class StepBase:
    duration: float | None = None
    easing: str | None = None
    hold: float | None = None


@dataclass(frozen=True, kw_only=True)
class WaitStep(StepBase):
    seconds: float


@dataclass(frozen=True, kw_only=True)
class MoveStep(StepBase):
    to: StepTarget


@dataclass(frozen=True, kw_only=True)
class ClickStep(StepBase):
    to: StepTarget | None = None
    button: Literal["left", "right", "middle"] = "left"


@dataclass(frozen=True, kw_only=True)
class ScrollStep(StepBase):
    by: int | None = None          # positive = down
    to: int | None = None          # absolute offset (web only)
    container: str | None = None   # selector of scroll container (web only)


@dataclass(frozen=True, kw_only=True)
class TypeStep(StepBase):
    text: str
    delay: float = 0.05


@dataclass(frozen=True, kw_only=True)
class PressStep(StepBase):
    key: str


@dataclass(frozen=True, kw_only=True)
class CursorStep(StepBase):
    visible: bool


Step = Union[WaitStep, MoveStep, ClickStep, ScrollStep, TypeStep, PressStep, CursorStep]


@dataclass(frozen=True)
class Scene:
    name: str
    target: Target
    steps: tuple[Step, ...]
    output: Output = field(default_factory=Output)
    cursor: CursorConfig = field(default_factory=CursorConfig)
    defaults: Defaults = field(default_factory=Defaults)
    version: int = 1
