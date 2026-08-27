"""StopHotkey is covered with a fake pynput listener; no real key press is ever required."""
from __future__ import annotations

import threading

import pytest
from pynput import keyboard

from capturekarma.recorder.hotkey import StopHotkey


class FakeListener:
    """Stands in for `pynput.keyboard.Listener`, recording construction, attribute sets and calls."""

    def __init__(self, **kwargs):
        object.__setattr__(self, "log", [])
        object.__setattr__(self, "kwargs", kwargs)

    def __setattr__(self, name, value):
        self.log.append(("set", name, value))
        object.__setattr__(self, name, value)

    def start(self):
        self.log.append(("start",))

    def stop(self):
        self.log.append(("stop",))


@pytest.fixture
def fake_listeners(monkeypatch) -> list[FakeListener]:
    made: list[FakeListener] = []

    def factory(**kwargs):
        listener = FakeListener(**kwargs)
        made.append(listener)
        return listener

    monkeypatch.setattr("pynput.keyboard.Listener", factory)
    return made


def test_not_triggered_before_start():
    hotkey = StopHotkey()
    assert isinstance(hotkey.triggered, threading.Event)
    assert hotkey.is_set() is False


def test_stop_before_start_is_a_no_op(fake_listeners):
    StopHotkey().stop()
    assert fake_listeners == []


def test_start_builds_one_daemon_listener(fake_listeners):
    StopHotkey().start()
    assert len(fake_listeners) == 1
    listener = fake_listeners[0]
    assert set(listener.kwargs) == {"on_press"}
    assert listener.log == [("set", "daemon", True), ("start",)]  # daemon set before start


@pytest.mark.parametrize("key", [keyboard.Key.f9, keyboard.Key.esc])
def test_default_keys_trigger(fake_listeners, key):
    hotkey = StopHotkey()
    hotkey.start()
    fake_listeners[0].kwargs["on_press"](key)
    assert hotkey.is_set() is True


@pytest.mark.parametrize("key", [keyboard.Key.f8, keyboard.KeyCode.from_char("a")])
def test_other_keys_do_not_trigger(fake_listeners, key):
    hotkey = StopHotkey()
    hotkey.start()
    fake_listeners[0].kwargs["on_press"](key)
    assert hotkey.is_set() is False


def test_custom_keys_ignore_unlisted_key(fake_listeners):
    hotkey = StopHotkey(keys=("f9",))
    hotkey.start()
    on_press = fake_listeners[0].kwargs["on_press"]
    on_press(keyboard.Key.esc)
    assert hotkey.is_set() is False
    on_press(keyboard.Key.f9)
    assert hotkey.is_set() is True


def test_stop_stops_listener_once(fake_listeners):
    hotkey = StopHotkey()
    hotkey.start()
    hotkey.stop()
    hotkey.stop()
    assert fake_listeners[0].log.count(("stop",)) == 1
