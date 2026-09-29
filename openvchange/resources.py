"""Files that ship with the app.

They live in `openvchange/assets`, both in a source checkout and inside the packaged
executable, which unpacks them next to this module.
"""

from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parent / "assets"

# Windows picks the size it needs from the .ico. Elsewhere the .png is used.
ICON_ICO = ASSETS / "icon.ico"
ICON_PNG = ASSETS / "icon.png"
