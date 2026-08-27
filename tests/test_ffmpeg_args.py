from pathlib import Path

from capturekarma.capture.ffmpeg import Capabilities, build_capture_args, even_region, parse_probe_output
from capturekarma.capture.monitors import Monitor
from capturekarma.scene.model import Region

CAPS_NV = Capabilities(exe="ffmpeg", version="7.1", ddagrab=True, nvenc=True, libx264=True)
CAPS_SW = Capabilities(exe="ffmpeg", version="7.1", ddagrab=True, nvenc=False, libx264=True)
MON = Monitor(1, Region(2560, 0, 1920, 1080), False)
OUT = Path("out.mp4")


def test_even_region_trims_odd():
    assert even_region(Region(1, 1, 101, 51)) == Region(1, 1, 100, 50)
    assert even_region(Region(0, 0, 100, 50)) == Region(0, 0, 100, 50)


def test_ddagrab_nvenc_args():
    args = build_capture_args(CAPS_NV, Region(2660, 100, 800, 600), MON, 60, OUT, use_ddagrab=True)
    assert args[0] == "ffmpeg" and args[-1] == str(OUT)
    joined = " ".join(args)
    assert "-f lavfi -i ddagrab=output_idx=1:offset_x=100:offset_y=100:video_size=800x600:framerate=60:draw_mouse=0" in joined
    assert "-c:v h264_nvenc" in joined and "-movflags +faststart" in joined
    assert "-pix_fmt yuv420p" in joined      # spec 3.6: every branch produces 4:2:0 for player compatibility
    # NVENC cannot honour an explicit -pix_fmt while the frames are still on the GPU, so the
    # ddagrab frames come down first here too (verified against real ddagrab + NVENC hardware).
    assert joined.index("-vf hwdownload,format=bgra") < joined.index("-c:v h264_nvenc")
    assert "-progress pipe:1" in joined and "-nostats" in joined


def test_ddagrab_libx264_downloads_frames():
    joined = " ".join(build_capture_args(CAPS_SW, Region(2660, 100, 800, 600), MON, 30, OUT, use_ddagrab=True))
    assert "-vf hwdownload,format=bgra" in joined
    assert "-c:v libx264 -preset veryfast -crf 18" in joined and "-pix_fmt yuv420p" in joined


def test_gdigrab_args_use_screen_coords():
    joined = " ".join(build_capture_args(CAPS_SW, Region(2660, 100, 800, 600), MON, 60, OUT, use_ddagrab=False))
    assert "-f gdigrab" in joined and "-offset_x 2660 -offset_y 100" in joined
    assert "-video_size 800x600" in joined and "-draw_mouse 0" in joined and "-i desktop" in joined
    assert "hwdownload" not in joined


def test_parse_probe_output():
    caps = parse_probe_output("ffmpeg",
        version_text="ffmpeg version 7.1-essentials_build Copyright",
        filters_text=" ... ddagrab           |->V ...",
        encoders_text=" V..... libx264 ...\n V....D h264_nvenc ...")
    assert caps == Capabilities("ffmpeg", "7.1-essentials_build", True, True, True)
