"""Draw the application icon and write it in the formats the app needs.

The icon is drawn from code, so there is no source image to keep. Run this again after
changing the drawing:

    poetry run python scripts/make_icon.py

It writes `openvchange/assets/icon.ico`, with every size Windows asks for, and
`openvchange/assets/icon.png`.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath

ASSETS = Path(__file__).resolve().parent.parent / "openvchange" / "assets"
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

BACKGROUND_TOP = QColor(38, 34, 84)
BACKGROUND_BOTTOM = QColor(18, 20, 46)
BARS_LEFT = QColor(64, 208, 232)
BARS_RIGHT = QColor(232, 92, 200)

# Height of each bar as a share of the tallest: a voice, louder in the middle.
BAR_HEIGHTS = (0.34, 0.66, 1.0, 0.58, 0.82, 0.40)


def draw(size: int) -> QImage:
    """The icon at `size` pixels square, drawn at that size and not scaled down."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)

    # Rounded square
    margin = size * 0.04
    square = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    background = QLinearGradient(QPointF(0, square.top()), QPointF(0, square.bottom()))
    background.setColorAt(0.0, BACKGROUND_TOP)
    background.setColorAt(1.0, BACKGROUND_BOTTOM)
    outline = QPainterPath()
    outline.addRoundedRect(square, size * 0.22, size * 0.22)
    painter.fillPath(outline, background)

    # Bars, changing colour from one side to the other
    # Small sizes get fewer, thicker bars so that they stay apart.
    heights = BAR_HEIGHTS if size >= 32 else BAR_HEIGHTS[1:5]
    area = square.adjusted(size * 0.17, size * 0.20, -size * 0.17, -size * 0.20)
    pitch = area.width() / len(heights)
    width = pitch * 0.58
    colours = QLinearGradient(QPointF(area.left(), 0), QPointF(area.right(), 0))
    colours.setColorAt(0.0, BARS_LEFT)
    colours.setColorAt(1.0, BARS_RIGHT)
    painter.setBrush(colours)
    for i, share in enumerate(heights):
        height = max(area.height() * share, width)
        left = area.left() + i * pitch + (pitch - width) / 2
        bar = QRectF(left, area.center().y() - height / 2, width, height)
        painter.drawRoundedRect(bar, width / 2, width / 2)

    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def ico_bytes(images: dict[int, bytes]) -> bytes:
    """An ICO file holding one PNG per size."""
    header = struct.pack("<HHH", 0, 1, len(images))
    directory = b""
    offset = len(header) + 16 * len(images)
    for size, png in images.items():
        # A size of 256 is written as 0.
        directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    return header + directory + b"".join(images.values())


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    ASSETS.mkdir(parents=True, exist_ok=True)

    images = {size: png_bytes(draw(size)) for size in ICO_SIZES}
    (ASSETS / "icon.ico").write_bytes(ico_bytes(images))
    (ASSETS / "icon.png").write_bytes(images[256])
    for name in ("icon.ico", "icon.png"):
        print(f"wrote {ASSETS / name} ({(ASSETS / name).stat().st_size} bytes)")
    del app


if __name__ == "__main__":
    main()
