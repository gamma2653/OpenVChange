"""Shared fixtures. Tests run headless and never open real audio devices."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pyaudio
import pytest
from PySide6.QtWidgets import QApplication

from tests.fakes import FakePyAudio


@pytest.fixture(autouse=True)
def fake_pyaudio(monkeypatch):
    """Replace PyAudio for every test."""
    FakePyAudio.reset()
    monkeypatch.setattr(pyaudio, "PyAudio", FakePyAudio)
    yield FakePyAudio
    FakePyAudio.reset()


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole test session."""
    return QApplication.instance() or QApplication([])
