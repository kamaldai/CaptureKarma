import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from capturekarma.cursor.sprites import available_styles  # noqa: E402
from capturekarma.gui import main_window as mw  # noqa: E402
from capturekarma.gui.main_window import MainWindow  # noqa: E402


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
    assert w.show_cursor_cb.isChecked() and w.style_combo.currentText() == "(scene default)"
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
