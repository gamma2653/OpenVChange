"""The system-wide shortcut."""

import ctypes
import json
import os
import sys

import pytest
from PySide6.QtGui import QKeySequence

from openvchange import hotkey
from openvchange.__main__ import MainWindow
from openvchange.hotkey import (
    HOTKEY_ID,
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    MOD_SHIFT,
    WM_HOTKEY,
    GlobalHotkey,
    HotkeyError,
    to_windows,
)
from tests.fakes import FakeHotkeyBackend

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows")


def keys(text: str) -> QKeySequence:
    return QKeySequence.fromString(text, QKeySequence.SequenceFormat.PortableText)


# --- translating a shortcut ------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "modifiers", "code"),
    [
        ("Ctrl+E", MOD_CONTROL, 0x45),
        ("Ctrl+Alt+E", MOD_CONTROL | MOD_ALT, 0x45),
        ("Ctrl+Shift+F9", MOD_CONTROL | MOD_SHIFT, 0x78),
        ("Alt+7", MOD_ALT, 0x37),
        ("F13", 0, 0x7C),
        ("Shift+F1", MOD_SHIFT, 0x70),
        ("F24", 0, 0x87),
        ("Ctrl+Space", MOD_CONTROL, 0x20),
        ("Ctrl+Alt+PgDown", MOD_CONTROL | MOD_ALT, 0x22),
        ("Alt+Ins", MOD_ALT, 0x2D),
    ],
)
def test_shortcuts_translate_to_windows_codes(qapp, text, modifiers, code):
    assert to_windows(keys(text)) == (modifiers, code)


@pytest.mark.parametrize("text", ["E", "Shift+E", "7", "Space", "Shift+Home"])
def test_keys_used_for_typing_need_a_real_modifier(qapp, text):
    with pytest.raises(HotkeyError, match="would get in the way of typing"):
        to_windows(keys(text))


@pytest.mark.parametrize("text", ["Ctrl+,", "Ctrl+Alt+-", "Ctrl+Tab", "Ctrl+Return", "Ctrl+Esc"])
def test_other_keys_are_refused(qapp, text):
    with pytest.raises(HotkeyError, match="not supported"):
        to_windows(keys(text))


@pytest.mark.parametrize("text", ["", "Ctrl+K, Ctrl+E"])
def test_only_a_single_combination_is_accepted(qapp, text):
    with pytest.raises(HotkeyError, match="single key combination"):
        to_windows(keys(text))


# --- registering -----------------------------------------------------------------


@pytest.fixture
def shortcut(qapp):
    h = GlobalHotkey()
    yield h
    h.close()


def test_setting_a_shortcut_registers_it(shortcut):
    shortcut.set_sequence(keys("Ctrl+Shift+F9"))

    assert shortcut.backend.registered == {HOTKEY_ID: (MOD_CONTROL | MOD_SHIFT, 0x78)}
    assert shortcut.sequence == keys("Ctrl+Shift+F9")


def test_changing_the_shortcut_gives_the_old_one_back_first(shortcut):
    shortcut.set_sequence(keys("Ctrl+Shift+F9"))
    shortcut.set_sequence(keys("Alt+F3"))

    assert shortcut.backend.calls == [
        ("register", MOD_CONTROL | MOD_SHIFT, 0x78),
        ("unregister",),
        ("register", MOD_ALT, 0x72),
    ]
    assert shortcut.backend.registered == {HOTKEY_ID: (MOD_ALT, 0x72)}


def test_an_empty_shortcut_turns_it_off(shortcut):
    shortcut.set_sequence(keys("Ctrl+Shift+F9"))
    shortcut.set_sequence(QKeySequence())

    assert shortcut.backend.registered == {}
    assert shortcut.sequence.isEmpty()


def test_a_shortcut_in_use_elsewhere_is_refused_and_the_old_one_stays(shortcut):
    shortcut.set_sequence(keys("Ctrl+Shift+F9"))
    FakeHotkeyBackend.taken = {(MOD_ALT, 0x72)}

    with pytest.raises(HotkeyError, match="another application already uses it"):
        shortcut.set_sequence(keys("Alt+F3"))

    assert shortcut.sequence == keys("Ctrl+Shift+F9")
    assert shortcut.backend.registered == {HOTKEY_ID: (MOD_CONTROL | MOD_SHIFT, 0x78)}


def test_an_unusable_shortcut_is_refused_before_the_old_one_is_touched(shortcut):
    shortcut.set_sequence(keys("Ctrl+Shift+F9"))

    with pytest.raises(HotkeyError):
        shortcut.set_sequence(keys("Shift+E"))

    assert shortcut.backend.calls == [("register", MOD_CONTROL | MOD_SHIFT, 0x78)]
    assert shortcut.sequence == keys("Ctrl+Shift+F9")


def test_close_gives_the_shortcut_back_and_may_be_repeated(shortcut):
    shortcut.set_sequence(keys("Ctrl+Shift+F9"))
    shortcut.close()
    shortcut.close()
    assert shortcut.backend.registered == {}


def test_where_shortcuts_are_not_supported_setting_one_says_so(qapp, monkeypatch):
    monkeypatch.setattr(hotkey, "default_backend", lambda: None)
    h = GlobalHotkey()

    assert not h.supported
    with pytest.raises(HotkeyError, match="need Windows"):
        h.set_sequence(keys("Ctrl+Shift+F9"))
    h.set_sequence(QKeySequence())
    h.close()


# --- hearing about a press -------------------------------------------------------


def post_hotkey_message(message: int, identifier: int) -> None:
    """Put a message into the queue of this thread, as Windows does on a key press."""
    kernel32 = ctypes.WinDLL("kernel32")
    user32 = ctypes.WinDLL("user32")
    assert user32.PostThreadMessageW(kernel32.GetCurrentThreadId(), message, identifier, 0)


@windows_only
def test_a_press_is_heard(qapp, shortcut):
    heard = []
    shortcut.pressed.connect(lambda: heard.append(True))
    shortcut.set_sequence(keys("Ctrl+Shift+F9"))

    post_hotkey_message(WM_HOTKEY, HOTKEY_ID)
    qapp.processEvents()

    assert heard == [True]


@windows_only
def test_other_messages_and_other_shortcuts_are_ignored(qapp, shortcut):
    heard = []
    shortcut.pressed.connect(lambda: heard.append(True))
    shortcut.set_sequence(keys("Ctrl+Shift+F9"))

    post_hotkey_message(WM_HOTKEY, HOTKEY_ID + 1)
    post_hotkey_message(WM_HOTKEY + 1, HOTKEY_ID)
    qapp.processEvents()

    assert heard == []


@windows_only
def test_nothing_is_heard_after_close(qapp):
    h = GlobalHotkey()
    heard = []
    h.pressed.connect(lambda: heard.append(True))
    h.set_sequence(keys("Ctrl+Shift+F9"))
    h.close()

    post_hotkey_message(WM_HOTKEY, HOTKEY_ID)
    qapp.processEvents()

    assert heard == []


@windows_only
@pytest.mark.skipif(bool(os.environ.get("CI")), reason="build machines may have no desktop to register with")
def test_windows_accepts_and_releases_a_real_shortcut(qapp):
    backend = hotkey.WindowsBackend()
    combination = (MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x87)  # Ctrl+Alt+Shift+F24

    backend.register(HOTKEY_ID, *combination)
    try:
        with pytest.raises(HotkeyError, match="another application already uses it"):
            backend.register(HOTKEY_ID + 1, *combination)
    finally:
        backend.unregister(HOTKEY_ID)

    backend.register(HOTKEY_ID, *combination)
    backend.unregister(HOTKEY_ID)


def test_holding_the_keys_counts_once():
    assert MOD_NOREPEAT == 0x4000


# --- in the window ---------------------------------------------------------------


@pytest.fixture
def window(qapp):
    w = MainWindow()
    yield w
    w.close()


def enter(window, text: str) -> None:
    """Type a shortcut into the field and leave it."""
    window.hotkey_edit.setKeySequence(keys(text))
    window.hotkey_edit.editingFinished.emit()


def test_no_shortcut_is_set_by_default(window):
    assert window.hotkey.sequence.isEmpty()
    assert window.hotkey_edit.keySequence().isEmpty()
    assert window.hotkey.backend.registered == {}


def test_entering_a_shortcut_registers_it(window):
    enter(window, "Ctrl+Shift+F9")

    assert window.hotkey.sequence == keys("Ctrl+Shift+F9")
    assert window.status_label.text() == "Status: Ctrl+Shift+F9 now switches the effects"


def test_pressing_the_shortcut_switches_the_effects(window):
    enter(window, "Ctrl+Shift+F9")
    assert window.audio_processor.effects_enabled

    window.hotkey.pressed.emit()
    assert not window.audio_processor.effects_enabled
    assert not window.effects_checkbox.isChecked()

    window.hotkey.pressed.emit()
    assert window.audio_processor.effects_enabled


@windows_only
def test_a_press_reaches_the_window_through_the_message_queue(qapp, window):
    enter(window, "Ctrl+Shift+F9")

    post_hotkey_message(WM_HOTKEY, HOTKEY_ID)
    qapp.processEvents()

    assert not window.effects_checkbox.isChecked()


def test_a_shortcut_that_cannot_be_used_is_explained_and_the_field_goes_back(window):
    enter(window, "Ctrl+Shift+F9")

    enter(window, "Shift+E")

    assert window.status_label.text() == (
        "Status: Shift+E cannot be used: it needs Ctrl, Alt, or the Windows key, "
        "or it would get in the way of typing"
    )
    assert window.hotkey_edit.keySequence() == keys("Ctrl+Shift+F9")
    assert window.hotkey.sequence == keys("Ctrl+Shift+F9")


def test_a_shortcut_in_use_elsewhere_is_explained(window):
    FakeHotkeyBackend.taken = {(MOD_CONTROL | MOD_ALT, 0x45)}
    enter(window, "Ctrl+Alt+E")
    assert window.status_label.text() == "Status: Ctrl+Alt+E cannot be used: another application already uses it"
    assert window.hotkey_edit.keySequence().isEmpty()


def test_clearing_the_field_removes_the_shortcut(window):
    enter(window, "Ctrl+Shift+F9")
    enter(window, "")

    assert window.hotkey.backend.registered == {}
    assert window.status_label.text() == "Status: Shortcut removed"


def test_leaving_the_field_unchanged_does_nothing(window):
    enter(window, "Ctrl+Shift+F9")
    window.status_label.setText("Status: Running")

    window.hotkey_edit.editingFinished.emit()

    assert window.status_label.text() == "Status: Running"
    assert len(window.hotkey.backend.calls) == 1


def test_the_shortcut_survives_a_restart(qapp, settings_path):
    w = MainWindow()
    enter(w, "Ctrl+Shift+F9")
    w.close()
    assert w.hotkey.backend.registered == {}
    assert json.loads(settings_path.read_text())["effects_shortcut"] == "Ctrl+Shift+F9"

    w = MainWindow()

    assert w.hotkey.sequence == keys("Ctrl+Shift+F9")
    assert w.hotkey_edit.keySequence() == keys("Ctrl+Shift+F9")
    assert w.hotkey.backend.registered == {HOTKEY_ID: (MOD_CONTROL | MOD_SHIFT, 0x78)}
    assert w.status_label.text() == "Status: Stopped"
    w.close()


def test_a_remembered_shortcut_that_is_now_taken_is_mentioned(qapp, settings_path):
    w = MainWindow()
    enter(w, "Ctrl+Shift+F9")
    w.gain_slider.setValue(4)
    w.close()
    FakeHotkeyBackend.taken = {(MOD_CONTROL | MOD_SHIFT, 0x78)}

    w = MainWindow()

    assert w.hotkey.sequence.isEmpty()
    assert w.gain_slider.value() == 4
    assert w.status_label.text() == (
        "Status: Stopped (the shortcut Ctrl+Shift+F9 cannot be used: another application already uses it)"
    )
    w.close()


def test_the_field_is_disabled_where_shortcuts_are_not_supported(qapp, monkeypatch):
    monkeypatch.setattr(hotkey, "default_backend", lambda: None)
    w = MainWindow()
    assert not w.hotkey_edit.isEnabled()
    w.close()


def test_closing_the_window_gives_the_shortcut_back(window):
    enter(window, "Ctrl+Shift+F9")
    backend = window.hotkey.backend

    window.close()

    assert backend.registered == {}
