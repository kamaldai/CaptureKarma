"""`ck` command line."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import NoReturn, Optional

import typer

from capturekarma.capture import CaptureError
from capturekarma.drivers.base import DriverError, StepError
from capturekarma.player import Player, PlayOptions
from capturekarma.recorder.desktop import record_desktop
from capturekarma.recorder.hotkey import StopHotkey
from capturekarma.recorder.web import record_web
from capturekarma.scene import SceneError, load_scene

app = typer.Typer(help="CaptureKarma: record a demo once, replay it cinematically, capture to MP4.",
                  no_args_is_help=True)
record_app = typer.Typer(help="Record a scene file by performing the demo once.", no_args_is_help=True)
app.add_typer(record_app, name="record")

_ERRORS = (SceneError, StepError, DriverError, CaptureError)
log = logging.getLogger("capturekarma.cli")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")


def _fail(exc: BaseException) -> NoReturn:
    typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code=1)


def _parse_viewport(value: str) -> tuple[int, int]:
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise typer.BadParameter("expected WxH, e.g. 1920x1080") from None


@record_app.command("web")
def record_web_cmd(
    url: str = typer.Argument(..., help="Page to open"),
    out: Path = typer.Option(Path("scene.yaml"), "-o", "--out", help="Scene file to write"),
    viewport: str = typer.Option("1920x1080", help="Viewport WxH in CSS px"),
    name: Optional[str] = typer.Option(None, help="Scene name (default: file stem)"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Open URL in Chromium, record your clicks/scrolls/typing; press F9 or close the browser to stop."""
    _setup_logging(verbose)
    vp = _parse_viewport(viewport)
    try:
        path = record_web(url, out, viewport=vp, name=name)
    except _ERRORS as exc:
        _fail(exc)
    except Exception as exc:  # noqa: BLE001 - a CLI must not spray tracebacks; -v shows the full one
        log.debug("unexpected error", exc_info=True)
        _fail(exc)
    typer.echo(f"wrote {path}")


@record_app.command("desktop")
def record_desktop_cmd(
    window: str = typer.Option(..., "--window", "-w", help="Substring of the target window title"),
    out: Path = typer.Option(Path("scene.yaml"), "-o", "--out"),
    name: Optional[str] = typer.Option(None),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Record clicks/scrolls/typing in a desktop window; press F9 to stop."""
    _setup_logging(verbose)
    try:
        path = record_desktop(window, out, name=name)
    except _ERRORS as exc:
        _fail(exc)
    except Exception as exc:  # noqa: BLE001 - a CLI must not spray tracebacks; -v shows the full one
        log.debug("unexpected error", exc_info=True)
        _fail(exc)
    typer.echo(f"wrote {path}")


@app.command()
def play(
    scene: Path = typer.Argument(..., exists=True, dir_okay=False, help="Scene YAML file"),
    out_dir: Optional[Path] = typer.Option(None, "--out-dir", help="Override output directory"),
    no_cursor: bool = typer.Option(False, "--no-cursor", help="Hide the rendered cursor for this run"),
    cursor_style: Optional[str] = typer.Option(None, "--cursor-style"),
    gdigrab: bool = typer.Option(False, "--gdigrab", help="Force the gdigrab capture backend"),
    verbose: bool = typer.Option(False, "-v", "--verbose"),
) -> None:
    """Replay a scene and record it to MP4. Press F9 or Esc to abort (partial video is kept)."""
    _setup_logging(verbose)
    try:
        sc = load_scene(scene)
        opts = PlayOptions(out_dir=out_dir, cursor_visible=False if no_cursor else None,
                           cursor_style=cursor_style, prefer_ddagrab=not gdigrab)
        hotkey = StopHotkey()
        hotkey.start()
        try:
            result = Player(sc, opts, stop_event=hotkey.triggered).run()
        except KeyboardInterrupt:
            hotkey.triggered.set()
            raise
        finally:
            hotkey.stop()
    except _ERRORS as exc:
        _fail(exc)
    except Exception as exc:  # noqa: BLE001 - a CLI must not spray tracebacks; -v shows the full one
        log.debug("unexpected error", exc_info=True)
        _fail(exc)
    status = "PARTIAL " if result.partial else ""
    typer.echo(f"{status}saved {result.video} ({result.duration:.1f}s, {result.frames} frames)")
    typer.echo(f"cursor timeline: {result.timeline}")


@app.command()
def doctor() -> None:
    """Check ffmpeg, capture backends, encoders, Playwright, monitors."""
    from capturekarma.doctor import run_doctor

    checks = run_doctor()
    for c in checks:
        mark = typer.style("OK  ", fg=typer.colors.GREEN) if c.ok else typer.style("FAIL", fg=typer.colors.RED)
        typer.echo(f"{mark} {c.name:<20} {c.detail}")
        if not c.ok and c.fix:
            typer.echo(f"     fix: {c.fix}")
    if not all(c.ok for c in checks if c.name in ("ffmpeg", "playwright chromium", "windows")):
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
