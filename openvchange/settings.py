"""What the app remembers between launches: the routes, their devices, and their settings.

Stored as one JSON file in the user's configuration folder. The effect settings inside
it have the same form as a preset file. Nothing here depends on Qt.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "OpenVChange"
FILE_NAME = "settings.json"


class SettingsError(Exception):
    """The settings could not be read or written. The message is meant for the user."""


def default_path() -> Path:
    """Where the settings live for the current user."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / APP_NAME / FILE_NAME


def load(path: str | Path) -> dict:
    """Read the settings. A missing file is not an error: it gives no settings.

    Raises SettingsError if the file exists but cannot be used.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as e:
        raise SettingsError("the file could not be read") from e

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise SettingsError("the file is damaged") from e
    if not isinstance(data, dict):
        raise SettingsError("the file is damaged")
    return data


def save(path: str | Path, data: dict) -> None:
    """Write the settings, creating the folder if needed.

    The file is written under another name and then moved into place, so a failure half
    way through leaves the previous settings intact. Raises SettingsError.
    """
    path = Path(path)
    partial = path.with_name(path.name + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(partial, path)
    except OSError as e:
        raise SettingsError("the file could not be written") from e


def routes(data: dict) -> list[dict]:
    """The routes in saved settings, checked for their form.

    A route is {"input_device", "input_channel", "output_device", "output_channel",
    "shortcut", "preset"}, where the preset holds its settings and is not checked here.
    Settings from before there were routes name one input device, one output device,
    one shortcut, and one preset; they give one route.

    Raises SettingsError if the file says something else than this.
    """
    if "routes" not in data:
        return [
            {
                "input_device": data.get("input_device"),
                "input_channel": None,
                "output_device": data.get("output_device"),
                "output_channel": None,
                "shortcut": data.get("effects_shortcut"),
                "preset": data.get("preset", {}),
            }
        ]

    saved = data["routes"]
    if not isinstance(saved, list) or not saved or not all(isinstance(route, dict) for route in saved):
        raise SettingsError("the file is damaged")
    for route in saved:
        for side in ("input", "output"):
            channel = route.get(f"{side}_channel")
            if channel is not None and not is_count(channel):
                raise SettingsError("the file is damaged")
    return [
        {
            "input_device": route.get("input_device"),
            "input_channel": route.get("input_channel"),
            "output_device": route.get("output_device"),
            "output_channel": route.get("output_channel"),
            "shortcut": route.get("shortcut"),
            "preset": route.get("preset", {}),
        }
        for route in saved
    ]


def is_count(value: object) -> bool:
    """Whether a value is a whole number from zero up. True and false are not numbers here."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
