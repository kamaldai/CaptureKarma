from pathlib import Path
from unittest import mock

from typer.testing import CliRunner

from capturekarma.cli import app
from capturekarma.player.player import RunResult

runner = CliRunner()


def test_play_reports_scene_error(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nname: x\ntarget: {kind: web}\nsteps: []\n", encoding="utf-8")
    r = runner.invoke(app, ["play", str(bad)])
    assert r.exit_code == 1 and "error:" in r.output and "url" in r.output


def test_play_invokes_player_with_options(tmp_path: Path):
    scene = tmp_path / "s.yaml"
    scene.write_text("version: 1\nname: x\ntarget: {kind: web, url: 'http://x'}\nsteps: []\n", encoding="utf-8")
    fake = RunResult(video=tmp_path / "x.mp4", timeline=tmp_path / "x.cursor.json", partial=False, duration=1.0, frames=60)
    with mock.patch("capturekarma.cli.StopHotkey"), mock.patch("capturekarma.cli.Player") as P:
        P.return_value.run.return_value = fake
        r = runner.invoke(app, ["play", str(scene), "--out-dir", str(tmp_path), "--no-cursor", "--gdigrab"])
    assert r.exit_code == 0, r.output
    opts = P.call_args.args[1]
    assert opts.out_dir == tmp_path and opts.cursor_visible is False and opts.prefer_ddagrab is False
    assert "x.mp4" in r.output


def test_record_web_parses_viewport(tmp_path: Path):
    with mock.patch("capturekarma.cli.record_web", return_value=tmp_path / "o.yaml") as rw:
        r = runner.invoke(app, ["record", "web", "http://x", "-o", str(tmp_path / "o.yaml"), "--viewport", "1280x720"])
    assert r.exit_code == 0, r.output
    assert rw.call_args.kwargs["viewport"] == (1280, 720)


def test_record_web_bad_viewport():
    r = runner.invoke(app, ["record", "web", "http://x", "--viewport", "big"])
    assert r.exit_code != 0 and "WxH" in r.output


def test_doctor_runs(tmp_path: Path):
    r = runner.invoke(app, ["doctor"])
    assert r.exit_code in (0, 1) and "ffmpeg" in r.output


def test_unexpected_error_is_reported_without_a_traceback(tmp_path: Path):
    with mock.patch("capturekarma.cli.record_web", side_effect=RuntimeError("kaboom")):
        r = runner.invoke(app, ["record", "web", "http://x", "-o", str(tmp_path / "o.yaml")])
    assert r.exit_code == 1
    assert "error: kaboom" in r.output
    assert "Traceback" not in r.output
    assert r.exception is None or isinstance(r.exception, SystemExit)


def test_unexpected_error_in_record_desktop_is_reported(tmp_path: Path):
    with mock.patch("capturekarma.cli.record_desktop", side_effect=OSError("no window subsystem")):
        r = runner.invoke(app, ["record", "desktop", "-w", "Notepad", "-o", str(tmp_path / "o.yaml")])
    assert r.exit_code == 1 and "error: no window subsystem" in r.output and "Traceback" not in r.output


def test_unexpected_error_in_play_is_reported(tmp_path: Path):
    scene = tmp_path / "s.yaml"
    scene.write_text("version: 1\nname: x\ntarget: {kind: web, url: 'http://x'}\nsteps: []\n", encoding="utf-8")
    with mock.patch("capturekarma.cli.StopHotkey"), mock.patch("capturekarma.cli.Player") as P:
        P.return_value.run.side_effect = RuntimeError("driver exploded")
        r = runner.invoke(app, ["play", str(scene)])
    assert r.exit_code == 1 and "error: driver exploded" in r.output and "Traceback" not in r.output


def test_errors_go_to_stderr(tmp_path: Path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("version: 1\nname: x\ntarget: {kind: web}\nsteps: []\n", encoding="utf-8")
    r = CliRunner().invoke(app, ["play", str(bad)])
    assert r.exit_code == 1
    assert "error:" in r.stderr
    assert "error:" not in r.stdout
