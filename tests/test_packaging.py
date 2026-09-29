"""What ships with the app: its icon, its version, and the recipe for the executable."""

import json
import re
import struct
from pathlib import Path

import pytest
import tomllib
from PySide6.QtGui import QIcon, QImage

import openvchange
from openvchange import resources
from openvchange.__main__ import MainWindow, application_icon

ROOT = Path(__file__).resolve().parent.parent


# --- icon ------------------------------------------------------------------------


def ico_entries(path: Path) -> list[tuple[int, bytes]]:
    """Each image in an ICO file, as (size, data)."""
    data = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", data, 0)
    assert (reserved, kind) == (0, 1), "not an icon file"
    entries = []
    for i in range(count):
        width, height, _, _, _, bits, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + 16 * i)
        assert width == height
        assert bits == 32
        entries.append((width or 256, data[offset : offset + length]))
    return entries


def test_icon_holds_every_size_windows_asks_for():
    sizes = [size for size, _ in ico_entries(resources.ICON_ICO)]
    assert sizes == [16, 24, 32, 48, 64, 128, 256]


def test_every_image_in_the_icon_is_a_picture_of_its_stated_size(qapp):
    for size, data in ico_entries(resources.ICON_ICO):
        image = QImage.fromData(data, "PNG")
        assert (image.width(), image.height()) == (size, size)
        # Transparent corners, solid middle.
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(size // 2, size // 2).alpha() == 255


def test_icon_loads_in_qt(qapp):
    icon = QIcon(str(resources.ICON_ICO))
    assert not icon.isNull()
    assert sorted(s.width() for s in icon.availableSizes()) == [16, 24, 32, 48, 64, 128, 256]


def test_application_icon_is_found(qapp):
    icon = application_icon()
    assert not icon.isNull()
    assert not icon.pixmap(32, 32).isNull()


def test_icon_matches_what_the_script_draws(qapp):
    # The icon files are made by scripts/make_icon.py. If the drawing changes, the
    # files have to be made again.
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_icon", ROOT / "scripts" / "make_icon.py")
    make_icon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(make_icon)

    for size, data in ico_entries(resources.ICON_ICO):
        assert QImage.fromData(data, "PNG") == make_icon.draw(size).convertToFormat(QImage.Format.Format_ARGB32)


# --- version ---------------------------------------------------------------------


def declared_versions() -> dict[str, str]:
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    return {
        "package.json": json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"],
        "package-lock.json": lock["version"],
        "pyproject.toml": tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["poetry"][
            "version"
        ],
        "openvchange/__init__.py": openvchange.__version__,
    }


def test_the_version_is_the_same_everywhere():
    versions = declared_versions()
    assert len(set(versions.values())) == 1, versions


def test_the_window_shows_the_version(qapp):
    window = MainWindow()
    assert window.version_label.text() == f"OpenVChange {openvchange.__version__}"
    window.close()


# --- recipe for the executable ---------------------------------------------------


@pytest.fixture(scope="module")
def spec_text() -> str:
    return (ROOT / "openvchange.spec").read_text(encoding="utf-8")


def test_the_executable_gets_the_icon_and_the_assets(spec_text):
    assert 'ICON = "openvchange/assets/icon.ico"' in spec_text
    assert "icon=ICON" in spec_text
    assert '("openvchange/assets/*", "openvchange/assets")' in spec_text
    assert (ROOT / "openvchange" / "assets" / "icon.ico").exists()


def test_the_executable_gets_its_version_from_the_project(spec_text):
    assert "version=VERSION_INFO" in spec_text
    assert re.search(r'tomllib\.load\(f\)\["tool"\]\["poetry"\]\["version"\]', spec_text)


@pytest.mark.parametrize(
    ("version", "numbers"),
    [("0.1.0", [0, 1, 0, 0]), ("1.12.3", [1, 12, 3, 0]), ("2.0.0-beta.4", [2, 0, 0, 0]), ("3.1", [3, 1, 0, 0])],
)
def test_versions_become_four_numbers_for_windows(spec_text, version, numbers):
    # The same two lines as in the spec, which cannot be imported.
    lines = [line for line in spec_text.splitlines() if line.startswith("_numbers")]
    assert len(lines) == 2
    scope = {"re": re, "VERSION": version}
    exec("\n".join(lines), scope)  # noqa: S102 - two lines of our own build recipe
    assert scope["_numbers"] == numbers
