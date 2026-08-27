"""Driver protocol and driver-level exceptions."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from capturekarma.motion.easing import Easing
from capturekarma.scene.model import Point, Region, Scene, ScrollStep, StepTarget, WheelStep


class DriverError(Exception):
    """Setup/teardown failures (browser didn't launch, window missing, ...)."""


class WindowNotFound(DriverError):
    pass


class StepError(Exception):
    """A step could not be executed. The player fills in step_index and screenshot."""

    def __init__(self, message: str, step_index: int | None = None, screenshot: Path | None = None):
        super().__init__(message)
        self.message = message
        self.step_index = step_index
        self.screenshot = screenshot

    def __str__(self) -> str:
        prefix = f"step {self.step_index + 1}: " if self.step_index is not None else ""
        suffix = f" (screenshot: {self.screenshot})" if self.screenshot else ""
        return prefix + self.message + suffix


class Driver(Protocol):
    def setup(self, scene: Scene) -> Region: ...
    def resolve(self, target: StepTarget) -> Point: ...
    def pointer_to(self, x: int, y: int) -> None: ...
    def mouse_down(self, button: str = "left") -> None: ...
    def mouse_up(self, button: str = "left") -> None: ...
    def smooth_scroll(self, step: ScrollStep, duration: float, easing: Easing) -> None: ...
    def smooth_wheel(self, step: WheelStep, duration: float, easing: Easing) -> None: ...
    def type_text(self, text: str, delay: float) -> None: ...
    def press(self, key: str) -> None: ...
    def screenshot(self, path: Path) -> None: ...
    def teardown(self) -> None: ...
