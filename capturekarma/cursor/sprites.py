"""Cursor sprite loading and frame rendering (pure Pillow/numpy, no Win32)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

FRAME_SIZE = 160
HOTSPOT = (FRAME_SIZE // 2, FRAME_SIZE // 2)
RIPPLE_DURATION = 0.4
RIPPLE_R0, RIPPLE_R1 = 6.0, 48.0
RIPPLE_COLOR = (59, 130, 246)  # blue-500
ASSETS_DIR = Path(__file__).parent / "assets"


@dataclass(frozen=True)
class Ripple:
    start: float  # clock time (seconds) when the click happened


def _draw_default_arrow() -> Image.Image:
    """Classic white arrow with a dark outline, tip at (0, 0), ~32 px tall, rendered 4x then downsampled."""
    s = 4
    img = Image.new("RGBA", (24 * s, 34 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(0, 0), (0, 26), (7, 20), (12, 32), (16, 30), (11, 18), (20, 18)]
    poly = [(x * s + 2 * s, y * s + 2 * s) for x, y in pts]
    d.polygon(poly, fill=(255, 255, 255, 255), outline=(20, 20, 20, 255))
    d.line(poly + [poly[0]], fill=(20, 20, 20, 255), width=2 * s)
    return img.resize((24, 34), Image.LANCZOS)


def available_styles() -> list[str]:
    styles = ["default"]
    if ASSETS_DIR.exists():
        styles += sorted(p.stem for p in ASSETS_DIR.glob("*.png"))
    return styles


def load_sprite(style: str) -> Image.Image:
    """RGBA sprite whose pixel (0, 0) is the cursor tip."""
    if style == "default":
        return _draw_default_arrow()
    p = ASSETS_DIR / f"{style}.png"
    if not p.exists():
        raise ValueError(f"unknown cursor style {style!r}; available: {', '.join(available_styles())}")
    return Image.open(p).convert("RGBA")


def render_frame(sprite: Image.Image, ripples: list[Ripple], now: float, ripple_enabled: bool) -> Image.Image:
    frame = Image.new("RGBA", (FRAME_SIZE, FRAME_SIZE), (0, 0, 0, 0))
    if ripple_enabled:
        d = ImageDraw.Draw(frame)
        for rp in ripples:
            t = (now - rp.start) / RIPPLE_DURATION
            if not 0.0 <= t < 1.0:
                continue
            radius = RIPPLE_R0 + (RIPPLE_R1 - RIPPLE_R0) * math.sqrt(t)
            alpha = int(180 * (1.0 - t))
            width = max(1, int(6 * (1.0 - t)) + 1)
            cx, cy = HOTSPOT
            d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                      outline=(*RIPPLE_COLOR, alpha), width=width)
    frame.alpha_composite(sprite, dest=HOTSPOT)
    return frame


def prune_ripples(ripples: list[Ripple], now: float) -> list[Ripple]:
    return [r for r in ripples if now - r.start < RIPPLE_DURATION]


def to_premultiplied_bgra(img: Image.Image) -> bytes:
    """Top-down premultiplied BGRA bytes as required by UpdateLayeredWindow with AC_SRC_ALPHA."""
    a = np.asarray(img.convert("RGBA"), dtype=np.uint16)
    alpha = a[..., 3:4]
    rgb = (a[..., :3] * alpha + 127) // 255
    bgra = np.concatenate([rgb[..., 2:3], rgb[..., 1:2], rgb[..., 0:1], alpha], axis=-1).astype(np.uint8)
    return bgra.tobytes()
