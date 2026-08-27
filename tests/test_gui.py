import logging
import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from capturekarma.cursor.sprites import available_styles  # noqa: E402
from capturekarma.gui import main_window as mw  # noqa: E402
from capturekarma.gui.main_window import MainWindow  # noqa: E402
from capturekarma.gui.worker import Worker  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_scene_list_and_play_enabled_state(qapp, tmp_path: Path):
    (tmp_path / "a.yaml").write_text("version: 1\nname: a\ntarget: {kind: web, url: 'http://x'}\nsteps: []\n")
    (tmp_path / "notes.txt").write_text("x")
    w = MainWindow(scenes_dir=tmp_path)
    assert [w.scene_list.item(i).text() for i in range(w.scene_list.count())] == ["a.yaml"]
    assert not w.play_btn.isEnabled()
    w.scene_list.setCurrentRow(0)
    assert w.play_btn.isEnabled()
    assert not w.hide_cursor_cb.isChecked() and w.style_combo.currentText() == "(scene default)"
    entries = [w.style_combo.itemText(i) for i in range(w.style_combo.count())]
    assert entries == ["(scene default)"] + available_styles()


def test_log_appends(qapp, tmp_path: Path):
    w = MainWindow(scenes_dir=tmp_path)
    w.append_log("hello")
    assert "hello" in w.log_view.toPlainText()


def test_refresh_keeps_selection_and_picks_up_new_scenes(qapp, tmp_path: Path):
    (tmp_path / "a.yaml").write_text("version: 1\nname: a\ntarget: {kind: web, url: 'http://x'}\nsteps: []\n")
    w = MainWindow(scenes_dir=tmp_path)
    w.scene_list.setCurrentRow(0)
    (tmp_path / "b.yaml").write_text("version: 1\nname: b\ntarget: {kind: web, url: 'http://x'}\nsteps: []\n")
    w.refresh_scenes()
    assert [w.scene_list.item(i).text() for i in range(w.scene_list.count())] == ["a.yaml", "b.yaml"]
    assert w.scene_list.currentItem().text() == "a.yaml"
    assert w.play_btn.isEnabled()


def test_selected_style_is_none_until_the_user_picks_one(qapp, tmp_path: Path):
    w = MainWindow(scenes_dir=tmp_path)
    assert w._selected_style() is None  # scene's own cursor.style wins
    w.style_combo.setCurrentIndex(1)
    assert w.style_combo.currentText() == available_styles()[0] == "default"
    assert w._selected_style() == "default"


def test_open_output_reports_failure_in_the_log(qapp, tmp_path: Path, monkeypatch):
    w = MainWindow(scenes_dir=tmp_path)
    w.output_dir = tmp_path / "out"
    monkeypatch.setattr(mw, "IS_WINDOWS", True)

    def boom(_path):
        raise OSError("boom")

    monkeypatch.setattr(os, "startfile", boom, raising=False)
    w._open_output()
    text = w.log_view.toPlainText()
    assert "could not open" in text and "boom" in text


def test_cursor_visible_option_defers_to_the_scene_until_hidden(qapp, tmp_path: Path):
    w = MainWindow(scenes_dir=tmp_path)
    assert w._cursor_visible_option() is None  # scene's own cursor.visible wins
    w.hide_cursor_cb.setChecked(True)
    assert w._cursor_visible_option() is False  # exactly `ck play --no-cursor`


def test_worker_forwards_info_logs(qapp):
    lib_logger = logging.getLogger("capturekarma")
    previous = lib_logger.level
    lines: list[str] = []
    results: list[object] = []

    def job():
        logging.getLogger("capturekarma.test").info("hello from job")
        return 1

    try:
        worker = Worker(job)
        worker.log.connect(lines.append)
        worker.done.connect(results.append)
        worker.start()
        assert worker.wait(5000)
        qapp.processEvents()
        assert any("hello from job" in line for line in lines), lines
        assert results == [1]
    finally:
        lib_logger.setLevel(previous)


def _scene_yaml(name: str, out_dir: Path) -> str:
    return (f"version: 1\nname: {name}\ntarget: {{kind: web, url: 'http://x'}}\n"
            f"output: {{dir: '{out_dir.as_posix()}'}}\nsteps: []\n")


def test_open_output_uses_the_selected_scenes_output_dir(qapp, tmp_path: Path, monkeypatch):
    scene_out = tmp_path / "scene-videos"
    (tmp_path / "a.yaml").write_text(_scene_yaml("a", scene_out), encoding="utf-8")
    w = MainWindow(scenes_dir=tmp_path)
    w.output_dir = tmp_path / "default-videos"
    w.scene_list.setCurrentRow(0)
    monkeypatch.setattr(mw, "IS_WINDOWS", True)
    opened: list[str] = []
    monkeypatch.setattr(os, "startfile", lambda p: opened.append(str(p)), raising=False)
    w._open_output()
    assert opened == [str(scene_out)] and scene_out.exists()


def test_open_output_expands_a_tilde_in_the_scenes_output_dir(qapp, tmp_path: Path, monkeypatch):
    (tmp_path / "a.yaml").write_text(
        "version: 1\nname: a\ntarget: {kind: web, url: 'http://x'}\n"
        "output: {dir: '~/Videos/CaptureKarmaTest'}\nsteps: []\n", encoding="utf-8")
    w = MainWindow(scenes_dir=tmp_path)
    w.scene_list.setCurrentRow(0)
    assert w._output_dir_for_selection() == Path("~/Videos/CaptureKarmaTest").expanduser()


def test_open_output_falls_back_to_the_default_folder(qapp, tmp_path: Path, monkeypatch):
    """No selection, or a scene that will not load, must still open something."""
    w = MainWindow(scenes_dir=tmp_path)
    w.output_dir = tmp_path / "default-videos"
    assert w._output_dir_for_selection() == w.output_dir      # nothing selected

    (tmp_path / "broken.yaml").write_text("version: 2\nname: b\n", encoding="utf-8")
    w.refresh_scenes()
    w.scene_list.setCurrentRow(0)
    assert w._output_dir_for_selection() == w.output_dir
    assert "broken.yaml" in w.log_view.toPlainText()


def test_install_file_log_writes_library_logs_to_a_rotating_file(tmp_path: Path):
    from capturekarma.gui.app import install_file_log

    lib_logger = logging.getLogger("capturekarma")
    before = list(lib_logger.handlers)
    try:
        path = install_file_log(tmp_path)
        assert path == tmp_path / "capturekarma.log"
        handler = next(h for h in lib_logger.handlers if getattr(h, "baseFilename", None) == str(path))
        assert handler.maxBytes == 1_000_000 and handler.backupCount == 3
        assert handler.level == logging.INFO

        logging.getLogger("capturekarma.player").info("step 3/9: DragStep")
        logging.getLogger("capturekarma.player").debug("chatter")
        handler.flush()
        text = path.read_text(encoding="utf-8")
        assert "step 3/9: DragStep" in text and "chatter" not in text

        assert install_file_log(tmp_path) == path          # idempotent: no duplicate handler
        assert sum(1 for h in lib_logger.handlers if getattr(h, "baseFilename", None) == str(path)) == 1
    finally:
        for h in list(lib_logger.handlers):
            if h not in before:
                h.close()
                lib_logger.removeHandler(h)


def test_install_file_log_survives_an_unwritable_directory(tmp_path: Path, monkeypatch):
    from capturekarma.gui import app as app_mod

    def boom(*a, **kw):
        raise OSError("access is denied")

    monkeypatch.setattr(Path, "mkdir", boom)
    assert app_mod.install_file_log(tmp_path / "nope") is None


def test_worker_failure_message_names_the_type_and_the_failing_step(qapp):
    from capturekarma.drivers.base import StepError

    failures: list[str] = []

    def job():
        raise StepError("element not found: '#missing'", step_index=4)

    worker = Worker(job)
    worker.failed.connect(failures.append)
    worker.start()
    assert worker.wait(5000)
    qapp.processEvents()
    assert failures == ["StepError: step 5: element not found: '#missing'"]
