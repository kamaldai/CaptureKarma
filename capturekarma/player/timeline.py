from __future__ import annotations

import json
from pathlib import Path

from capturekarma.scene.model import Region


class CursorTimeline:
    """Per-tick cursor samples: [t, x, y, visible, click]. Enables post-compositing later."""

    def __init__(self) -> None:
        self.samples: list[list] = []

    def add(self, t: float, x: int, y: int, visible: bool, click: bool = False) -> None:
        self.samples.append([round(t, 4), int(x), int(y), bool(visible), bool(click)])

    def dump(self, path: Path, region: Region, hz: int) -> Path:
        data = {"version": 1, "hz": hz, "region": [region.x, region.y, region.width, region.height],
                "fields": ["t", "x", "y", "visible", "click"], "samples": self.samples}
        Path(path).write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        return Path(path)
