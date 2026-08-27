import pytest
from PIL import Image

from capturekarma.cursor.sprites import (
    FRAME_SIZE, HOTSPOT, RIPPLE_DURATION, Ripple, load_sprite, render_frame, to_premultiplied_bgra,
)


def test_default_sprite_is_rgba_and_small():
    s = load_sprite("default")
    assert s.mode == "RGBA" and s.width <= 48 and s.height <= 48
    assert s.getbbox() is not None


def test_unknown_style_lists_available():
    with pytest.raises(ValueError, match="default"):
        load_sprite("nope")


def test_render_frame_places_tip_at_hotspot():
    s = load_sprite("default")
    f = render_frame(s, [], now=0.0, ripple_enabled=True)
    assert f.size == (FRAME_SIZE, FRAME_SIZE) and f.mode == "RGBA"
    # the tip sits within a 3x3 neighbourhood of the hotspot; the far corner is transparent
    hx, hy = HOTSPOT
    assert any(f.getpixel((hx + dx, hy + dy))[3] > 0 for dx in range(3) for dy in range(3))
    assert f.getpixel((hx - 4, hy - 4))[3] == 0   # nothing above/left of the tip
    assert f.getpixel((0, 0))[3] == 0


def test_ripple_grows_and_fades():
    s = load_sprite("default")
    r = [Ripple(start=10.0)]
    early = render_frame(s, r, now=10.05, ripple_enabled=True)
    late = render_frame(s, r, now=10.35, ripple_enabled=True)
    done = render_frame(s, r, now=10.0 + RIPPLE_DURATION + 0.01, ripple_enabled=True)
    off = render_frame(s, r, now=10.05, ripple_enabled=False)

    def alpha_sum(img: Image.Image) -> int:
        return sum(img.getchannel("A").tobytes())

    base = alpha_sum(render_frame(s, [], now=0.0, ripple_enabled=True))
    assert alpha_sum(early) > base and alpha_sum(late) > base
    assert alpha_sum(done) == base and alpha_sum(off) == base
    # late ring is wider: some alpha further from the hotspot than in the early frame
    def max_radius(img):
        a = img.getchannel("A").load()
        best = 0
        for y in range(FRAME_SIZE):
            for x in range(FRAME_SIZE):
                if a[x, y] > 0:
                    best = max(best, (x - HOTSPOT[0]) ** 2 + (y - HOTSPOT[1]) ** 2)
        return best
    assert max_radius(late) > max_radius(early)


def test_premultiplied_bgra_layout():
    img = Image.new("RGBA", (2, 1))
    img.putpixel((0, 0), (255, 0, 0, 128))   # red, half alpha
    img.putpixel((1, 0), (0, 0, 255, 255))   # blue, opaque
    b = to_premultiplied_bgra(img)
    assert len(b) == 8
    assert b[0:4] == bytes([0, 0, 128, 128])  # B,G,R,A premultiplied (255*128/255=128)
    assert b[4:8] == bytes([255, 0, 0, 255])
