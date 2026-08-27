"""The whole GUI: a thin shell whose buttons call the same library functions the CLI does."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from capturekarma._win import IS_WINDOWS
from capturekarma.cursor.sprites import available_styles
from capturekarma.player import Player, PlayOptions
from capturekarma.recorder.desktop import record_desktop
from capturekarma.recorder.web import record_web
from capturekarma.scene import load_scene

from .worker import Worker


class MainWindow(QMainWindow):
    def __init__(self, scenes_dir: Path):
        super().__init__()
        self.setWindowTitle("CaptureKarma")
        self.resize(820, 600)
        self.scenes_dir = Path(scenes_dir)
        self.scenes_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir = Path("~/Videos/CaptureKarma").expanduser()
        self._worker: Worker | None = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)

        # left: scenes
        left = QVBoxLayout()
        self.scenes_label = QLabel(f"Scenes in {self.scenes_dir}")
        left.addWidget(self.scenes_label)
        self.scene_list = QListWidget()
        self.scene_list.currentRowChanged.connect(lambda _r: self._update_buttons())
        left.addWidget(self.scene_list, 1)
        row = QHBoxLayout()
        self.choose_dir_btn = QPushButton("Scenes folder…")
        self.choose_dir_btn.clicked.connect(self._choose_scenes_dir)
        self.play_btn = QPushButton("Play selected")
        self.play_btn.clicked.connect(self._play)
        row.addWidget(self.choose_dir_btn)
        row.addWidget(self.play_btn)
        left.addLayout(row)
        layout.addLayout(left, 1)

        # right: record + options + log
        right = QVBoxLayout()
        rec = QGroupBox("Record")
        rec_l = QVBoxLayout(rec)
        web_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://your.app/page")
        self.record_web_btn = QPushButton("Record web")
        self.record_web_btn.clicked.connect(self._record_web)
        web_row.addWidget(self.url_edit, 1)
        web_row.addWidget(self.record_web_btn)
        rec_l.addLayout(web_row)
        desk_row = QHBoxLayout()
        self.window_combo = QComboBox()
        self.window_combo.setEditable(True)
        self.refresh_windows_btn = QPushButton("↻")
        self.refresh_windows_btn.setFixedWidth(32)
        self.refresh_windows_btn.clicked.connect(self.refresh_windows)
        self.record_desktop_btn = QPushButton("Record desktop")
        self.record_desktop_btn.clicked.connect(self._record_desktop)
        desk_row.addWidget(self.window_combo, 1)
        desk_row.addWidget(self.refresh_windows_btn)
        desk_row.addWidget(self.record_desktop_btn)
        rec_l.addLayout(desk_row)
        rec_l.addWidget(QLabel("Press F9 in any window to stop recording or abort playback."))
        right.addWidget(rec)

        opts = QGroupBox("Playback options (override the scene for this run)")
        opts_l = QHBoxLayout(opts)
        self.show_cursor_cb = QCheckBox("Show cursor")
        self.show_cursor_cb.setChecked(True)
        self.style_combo = QComboBox()
        self.style_combo.addItems(available_styles())
        self.open_btn = QPushButton("Open output folder")
        self.open_btn.clicked.connect(self._open_output)
        opts_l.addWidget(self.show_cursor_cb)
        opts_l.addWidget(QLabel("Cursor style"))
        opts_l.addWidget(self.style_combo)
        opts_l.addStretch(1)
        opts_l.addWidget(self.open_btn)
        right.addWidget(opts)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        right.addWidget(self.log_view, 1)
        layout.addLayout(right, 2)

        self.refresh_scenes()
        self.refresh_windows()
        self._update_buttons()

    # ---- state ----
    def refresh_scenes(self) -> None:
        item = self.scene_list.currentItem()
        selected = item.text() if item else None
        self.scenes_label.setText(f"Scenes in {self.scenes_dir}")
        self.scene_list.clear()
        for p in sorted(self.scenes_dir.glob("*.y*ml")):
            self.scene_list.addItem(p.name)
        if selected is not None:  # a refresh after a run must not silently drop the user's pick
            for i in range(self.scene_list.count()):
                if self.scene_list.item(i).text() == selected:
                    self.scene_list.setCurrentRow(i)
                    break
        self._update_buttons()

    def refresh_windows(self) -> None:
        self.window_combo.clear()
        if IS_WINDOWS:
            from capturekarma.drivers.win_input import list_window_titles
            self.window_combo.addItems(sorted(set(list_window_titles())))

    def append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _busy(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _update_buttons(self) -> None:
        busy = self._busy()
        self.play_btn.setEnabled(self.scene_list.currentRow() >= 0 and not busy)
        self.record_web_btn.setEnabled(not busy)
        self.record_desktop_btn.setEnabled(not busy)

    def _run(self, fn) -> None:
        self._worker = Worker(fn)
        self._worker.log.connect(self.append_log)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._update_buttons)
        self._worker.start()
        self._update_buttons()

    def _on_done(self, result) -> None:
        self.append_log(f"done: {result}")
        self.refresh_scenes()

    def _on_failed(self, message: str) -> None:
        self.append_log(f"ERROR: {message}")

    # ---- actions ----
    def _choose_scenes_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Scenes folder", str(self.scenes_dir))
        if d:
            self.scenes_dir = Path(d)
            self.refresh_scenes()

    def _selected_scene(self) -> Path | None:
        item = self.scene_list.currentItem()
        return self.scenes_dir / item.text() if item else None

    def _play(self) -> None:
        path = self._selected_scene()
        if not path:
            return
        visible = self.show_cursor_cb.isChecked()
        style = self.style_combo.currentText()
        from capturekarma.recorder.hotkey import StopHotkey

        def job():
            scene = load_scene(path)
            hotkey = StopHotkey()
            hotkey.start()
            try:
                return Player(scene, PlayOptions(cursor_visible=visible, cursor_style=style),
                              stop_event=hotkey.triggered).run()
            finally:
                hotkey.stop()

        self.append_log(f"playing {path.name} …")
        self._run(job)

    def _record_web(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            self.append_log("enter a URL first")
            return
        out = self._next_scene_path("web")
        self.append_log(f"recording {url} → {out.name}; press F9 or close the browser to stop")
        self._run(lambda: record_web(url, out))

    def _record_desktop(self) -> None:
        title = self.window_combo.currentText().strip()
        if not title:
            self.append_log("pick a window first")
            return
        out = self._next_scene_path("desktop")
        self.append_log(f"recording window {title!r} → {out.name}; press F9 to stop")
        self._run(lambda: record_desktop(title, out))

    def _next_scene_path(self, prefix: str) -> Path:
        """First `<prefix>-N.yaml` in the scenes folder that does not exist yet — never overwrite a scene."""
        n = len(list(self.scenes_dir.glob("*.yaml"))) + 1
        while (self.scenes_dir / f"{prefix}-{n}.yaml").exists():
            n += 1
        return self.scenes_dir / f"{prefix}-{n}.yaml"

    def _open_output(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if IS_WINDOWS:
            os.startfile(self.output_dir)  # type: ignore[attr-defined]
        else:
            self.append_log(str(self.output_dir))
