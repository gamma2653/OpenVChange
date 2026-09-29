"""Shared fixtures. Tests run headless and never open real audio devices."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyaudio
import pytest
from PySide6.QtWidgets import QApplication

from openvchange import hotkey, settings
from tests.fakes import FakeHotkeyBackend, FakePyAudio


@pytest.fixture(autouse=True)
def fake_pyaudio(monkeypatch):
    """Replace PyAudio for every test."""
    FakePyAudio.reset()
    monkeypatch.setattr(pyaudio, "PyAudio", FakePyAudio)
    yield FakePyAudio
    FakePyAudio.reset()


@pytest.fixture(autouse=True)
def fake_hotkeys(monkeypatch):
    """Keep every test from registering shortcuts with the real system."""
    FakeHotkeyBackend.reset()
    monkeypatch.setattr(hotkey, "default_backend", FakeHotkeyBackend)
    yield FakeHotkeyBackend
    FakeHotkeyBackend.reset()


@pytest.fixture(autouse=True)
def settings_path(monkeypatch, tmp_path):
    """Keep every test away from the real settings of whoever runs the tests."""
    path = tmp_path / "config" / "settings.json"
    monkeypatch.setattr(settings, "default_path", lambda: path)
    return path


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole test session."""
    return QApplication.instance() or QApplication([])
