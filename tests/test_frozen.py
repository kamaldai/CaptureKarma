"""`capturekarma._frozen` — the PyInstaller bundle's runtime fix-ups.

Pure: `sys.frozen` / `sys._MEIPASS` are faked and the "bundle" is a tmp dir, so these run
everywhere and never touch a real build.
"""
from __future__ import annotations

import os
import sys

import pytest

from capturekarma import _frozen

FFMPEG_NAME = "ffmpeg-win-x86_64-v7.1.exe"
OTHER_CACHE = r"C:\Users\someone\AppData\Local\ms-playwright"
OTHER_FFMPEG = r"C:\ffmpeg\bin\ffmpeg.exe"


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    monkeypatch.delenv("IMAGEIO_FFMPEG_EXE", raising=False)


@pytest.fixture
def empty_bundle(monkeypatch, tmp_path):
    """`sys.frozen` set, `sys._MEIPASS` pointing at an empty dir: a build that collected nothing."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    return tmp_path


@pytest.fixture
def fake_bundle(empty_bundle):
    """The same, with the ffmpeg binary and Chromium directory a real bundle carries."""
    binaries = empty_bundle / "imageio_ffmpeg" / "binaries"
    binaries.mkdir(parents=True)
    (binaries / FFMPEG_NAME).write_bytes(b"MZ fake")
    (binaries / "README.md").write_text("not an executable", encoding="utf-8")
    (empty_bundle / "playwright" / "driver" / "package" / ".local-browsers" / "chromium-1234").mkdir(parents=True)
    return empty_bundle


def test_bootstrap_is_a_no_op_when_not_frozen(monkeypatch, clean_env):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    _frozen.bootstrap()
    assert "PLAYWRIGHT_BROWSERS_PATH" not in os.environ
    assert "IMAGEIO_FFMPEG_EXE" not in os.environ
    assert _frozen.is_frozen() is False
    assert _frozen.bundle_dir() is None
    assert _frozen.bundled_ffmpeg() is None
    assert _frozen.bundled_browsers() is None


def test_bootstrap_points_playwright_and_ffmpeg_at_the_bundle(fake_bundle, clean_env):
    _frozen.bootstrap()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "0"
    assert os.environ["IMAGEIO_FFMPEG_EXE"] == str(fake_bundle / "imageio_ffmpeg" / "binaries" / FFMPEG_NAME)
    assert _frozen.bundle_dir() == fake_bundle


def test_bootstrap_keeps_an_operator_ffmpeg_override(fake_bundle, monkeypatch):
    """Any ffmpeg build with ddagrab will do, so one the operator named is left in place."""
    monkeypatch.setenv("IMAGEIO_FFMPEG_EXE", OTHER_FFMPEG)
    _frozen.bootstrap()
    assert os.environ["IMAGEIO_FFMPEG_EXE"] == OTHER_FFMPEG


def test_bundled_chromium_beats_a_machine_wide_browsers_path(fake_bundle, monkeypatch, caplog):
    """A dev box's PLAYWRIGHT_BROWSERS_PATH names another install's cache, which lacks our revision."""
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", OTHER_CACHE)
    with caplog.at_level("INFO", logger="capturekarma.frozen"):
        _frozen.bootstrap()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "0"
    assert "ms-playwright" in caplog.text
    assert _frozen.bundled_browsers() == fake_bundle / "playwright" / "driver" / "package" / ".local-browsers"


def test_a_bundle_without_chromium_leaves_the_machine_setting_alone(empty_bundle, monkeypatch, caplog):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", OTHER_CACHE)
    with caplog.at_level("WARNING", logger="capturekarma.frozen"):
        _frozen.bootstrap()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == OTHER_CACHE
    assert "no bundled Chromium" in caplog.text


def test_bootstrap_without_a_bundled_ffmpeg_leaves_discovery_to_path(empty_bundle, clean_env, caplog):
    with caplog.at_level("WARNING", logger="capturekarma.frozen"):
        _frozen.bootstrap()
    assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "0"
    assert "IMAGEIO_FFMPEG_EXE" not in os.environ
    assert "bundled ffmpeg not found" in caplog.text


def test_bundle_dir_falls_back_to_the_executable_directory(monkeypatch, tmp_path):
    """Onedir bundles set `_MEIPASS`, but a build that does not must still resolve somewhere sane."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "ck.exe"))
    assert _frozen.bundle_dir() == tmp_path


def test_probe_flag_is_ignored_for_ordinary_arguments(monkeypatch):
    """`maybe_run_chromium_probe` must not swallow real arguments (nor import playwright to decide)."""
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)  # importing it would raise
    _frozen.maybe_run_chromium_probe([])
    _frozen.maybe_run_chromium_probe(["doctor"])
    _frozen.maybe_run_chromium_probe(["play", "scene.yaml", _frozen.CHROMIUM_PROBE_FLAG])
