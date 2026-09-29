"""Reading, checking, and writing preset files.

A preset is a JSON object that maps setting names to values in the units of the
controls: whole numbers for sliders, true or false for checkboxes. Nothing here depends
on Qt. The window describes its controls as fields and gets back values that are safe to
apply.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class PresetError(Exception):
    """A preset could not be read, written, or used. The message is meant for the user."""


@dataclass(frozen=True)
class Toggle:
    """A setting that is on or off."""


@dataclass(frozen=True)
class Number:
    """A whole number within a range."""

    minimum: int
    maximum: int


@dataclass(frozen=True)
class Choice:
    """One of a fixed set of whole numbers."""

    options: tuple[int, ...]


Field = Toggle | Number | Choice
Value = bool | int


def check(preset: object, fields: Mapping[str, Field]) -> tuple[dict[str, Value], list[str]]:
    """Check a loaded preset against the controls it is meant for.

    Returns the values to apply and a note for each value that had to be changed or
    left out. Raises PresetError if a value has the wrong type; in that case nothing
    should be applied, since the file is not what it claims to be.

    Settings the preset does not mention are left alone, and settings this version does
    not know are ignored, so presets from older and newer versions both load.
    """
    if not isinstance(preset, dict):
        raise PresetError("the file does not contain a preset")

    values: dict[str, Value] = {}
    notes: list[str] = []
    for name, field in fields.items():
        if name not in preset:
            continue
        raw = preset[name]

        if isinstance(field, Toggle):
            if not isinstance(raw, bool):
                raise PresetError(f"'{name}' must be true or false, not {describe(raw)}")
            values[name] = raw
            continue

        number = whole_number(raw)
        if number is None:
            raise PresetError(f"'{name}' must be a whole number, not {describe(raw)}")

        if isinstance(field, Choice):
            if number in field.options:
                values[name] = number
            else:
                allowed = ", ".join(str(option) for option in field.options)
                notes.append(f"'{name}' was left unchanged: {number} is not one of {allowed}")
            continue

        clamped = min(max(number, field.minimum), field.maximum)
        if clamped != number:
            notes.append(f"'{name}' was changed from {number} to {clamped} to fit its range")
        values[name] = clamped

    return values, notes


def whole_number(raw: object) -> int | None:
    """The value as an int, if it is one. True and false are not numbers here."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float) and raw.is_integer():
        return int(raw)
    return None


def describe(raw: object) -> str:
    """A short description of a value that was not what was expected."""
    if raw is None:
        return "empty"
    if isinstance(raw, bool):
        return "true" if raw else "false"
    if isinstance(raw, str):
        shown = raw if len(raw) <= 20 else raw[:17] + "..."
        return f'the text "{shown}"'
    if isinstance(raw, (int, float)):
        return str(raw)
    return "a list" if isinstance(raw, list) else "a nested object"


def load(path: str | Path) -> object:
    """Read a preset file. Raises PresetError if it cannot be read or is not JSON."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise PresetError(f"the file could not be read ({reason(e)})") from e
    except UnicodeDecodeError as e:
        raise PresetError("the file is not a text file") from e

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise PresetError(f"the file is not valid JSON (line {e.lineno})") from e


def save(path: str | Path, preset: Mapping[str, Value]) -> None:
    """Write a preset file. Raises PresetError if it cannot be written."""
    try:
        Path(path).write_text(json.dumps(dict(preset), indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        raise PresetError(f"the file could not be written ({reason(e)})") from e


def reason(error: OSError) -> str:
    """The operating system's explanation, without the path or error number."""
    return (error.strerror or type(error).__name__).rstrip(".").lower()
