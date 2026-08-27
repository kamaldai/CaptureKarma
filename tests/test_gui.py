import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

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
    assert w.show_cursor_cb.isChecked() and w.style_combo.currentText() == "default"


def test_log_appends(qapp, tmp_path: Path):
    w = MainWindow(scenes_dir=tmp_path)
    w.append_log("hello")
    assert "hello" in w.log_view.toPlainText()
