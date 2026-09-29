"""A keyboard shortcut that works while another application has the focus.

Windows only. Elsewhere `GlobalHotkey.supported` is False and setting a shortcut raises
HotkeyError.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Protocol

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Qt, Signal
from PySide6.QtGui import QKeySequence

if sys.platform == "win32":
    from ctypes import wintypes

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # holding the keys down counts as one press

WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# Identifies our shortcut among the messages of this thread.
HOTKEY_ID = 0x4F56

# Keys whose Windows code is not simply their character.
NAMED_KEYS = {
    Qt.Key.Key_Space: 0x20,
    Qt.Key.Key_PageUp: 0x21,
    Qt.Key.Key_PageDown: 0x22,
    Qt.Key.Key_End: 0x23,
    Qt.Key.Key_Home: 0x24,
    Qt.Key.Key_Left: 0x25,
    Qt.Key.Key_Up: 0x26,
    Qt.Key.Key_Right: 0x27,
    Qt.Key.Key_Down: 0x28,
    Qt.Key.Key_Insert: 0x2D,
    Qt.Key.Key_Delete: 0x2E,
    Qt.Key.Key_Pause: 0x13,
    Qt.Key.Key_ScrollLock: 0x91,
}


class HotkeyError(Exception):
    """A shortcut could not be used. The message completes "... cannot be used: "."""


def to_windows(sequence: QKeySequence) -> tuple[int, int]:
    """Translate a shortcut into the modifiers and key code Windows asks for."""
    if sequence.count() != 1:
        raise HotkeyError("it has to be a single key combination")
    combination = sequence[0]
    key = combination.key()
    pressed = combination.keyboardModifiers()

    modifiers = 0
    for qt_modifier, windows_modifier in (
        (Qt.KeyboardModifier.ControlModifier, MOD_CONTROL),
        (Qt.KeyboardModifier.AltModifier, MOD_ALT),
        (Qt.KeyboardModifier.ShiftModifier, MOD_SHIFT),
        (Qt.KeyboardModifier.MetaModifier, MOD_WIN),
    ):
        if pressed & qt_modifier:
            modifiers |= windows_modifier

    value = key.value
    if Qt.Key.Key_F1.value <= value <= Qt.Key.Key_F24.value:
        # Function keys do nothing while typing, so they may be used on their own.
        return modifiers, 0x70 + value - Qt.Key.Key_F1.value

    if Qt.Key.Key_A.value <= value <= Qt.Key.Key_Z.value or Qt.Key.Key_0.value <= value <= Qt.Key.Key_9.value:
        code = value
    elif key in NAMED_KEYS:
        code = NAMED_KEYS[key]
    else:
        raise HotkeyError("that key is not supported; use a letter, a digit, or a function key")

    if not modifiers & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        raise HotkeyError("it needs Ctrl, Alt, or the Windows key, or it would get in the way of typing")
    return modifiers, code


class Backend(Protocol):
    """Whatever registers shortcuts with the operating system."""

    def register(self, hotkey_id: int, modifiers: int, key_code: int) -> None: ...

    def unregister(self, hotkey_id: int) -> None: ...


class WindowsBackend:
    """Registers shortcuts for the calling thread, which has to be the GUI thread."""

    def __init__(self) -> None:
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]

    def register(self, hotkey_id: int, modifiers: int, key_code: int) -> None:
        if self.user32.RegisterHotKey(None, hotkey_id, modifiers | MOD_NOREPEAT, key_code):
            return
        error = ctypes.get_last_error()  # type: ignore[attr-defined]
        if error == ERROR_HOTKEY_ALREADY_REGISTERED:
            raise HotkeyError("another application already uses it")
        raise HotkeyError(f"Windows refused it (error {error})")

    def unregister(self, hotkey_id: int) -> None:
        self.user32.UnregisterHotKey(None, hotkey_id)


def default_backend() -> Backend | None:
    """The backend for this platform, or None where shortcuts are not supported."""
    return WindowsBackend() if sys.platform == "win32" else None


class _Listener(QAbstractNativeEventFilter):
    """Watches the messages of the GUI thread for our shortcut."""

    def __init__(self, on_pressed) -> None:
        super().__init__()
        self.on_pressed = on_pressed

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == HOTKEY_ID:
                self.on_pressed()
        return False, 0


class GlobalHotkey(QObject):
    """One shortcut that works system-wide. Emits `pressed`."""

    pressed = Signal()

    def __init__(self, backend: Backend | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.backend = backend if backend is not None else default_backend()
        self.sequence = QKeySequence()
        self._listener = None
        if self.supported:
            self._listener = _Listener(self.pressed.emit)
            QCoreApplication.instance().installNativeEventFilter(self._listener)

    @property
    def supported(self) -> bool:
        return self.backend is not None

    def set_sequence(self, sequence: QKeySequence) -> None:
        """Use this shortcut from now on. An empty one turns the shortcut off.

        Raises HotkeyError if it cannot be used, and then the previous shortcut stays.
        """
        if sequence.isEmpty():
            self.clear()
            return
        if self.backend is None:
            raise HotkeyError("shortcuts that work in other applications need Windows")

        modifiers, key_code = to_windows(sequence)
        previous = self.sequence
        self.clear()
        try:
            self.backend.register(HOTKEY_ID, modifiers, key_code)
        except HotkeyError:
            if not previous.isEmpty():
                self.backend.register(HOTKEY_ID, *to_windows(previous))
                self.sequence = previous
            raise
        self.sequence = sequence

    def clear(self) -> None:
        """Turn the shortcut off."""
        if self.backend is not None and not self.sequence.isEmpty():
            self.backend.unregister(HOTKEY_ID)
        self.sequence = QKeySequence()

    def close(self) -> None:
        """Give the shortcut back to the system. Safe to call more than once."""
        self.clear()
        if self._listener is not None:
            app = QCoreApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._listener)
            self._listener = None
