"""Widgets that Qt does not provide."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget


class LevelMeter(QWidget):
    """A peak meter on a decibel scale, with a peak-hold marker and a clip light.

    The bar jumps up to each new level and falls back at a steady rate, so short peaks
    stay visible. The marker remembers the highest recent level. The light at the right
    end comes on when the signal clips and stays on for a moment.

    Time is passed in by the caller as the length of audio each update covers, so the
    meter moves with the audio and not with the wall clock.
    """

    FLOOR_DB = -60.0
    FALL_DB_PER_SECOND = 24.0
    PEAK_HOLD_SECONDS = 1.5
    CLIP_HOLD_SECONDS = 2.0

    # Where the bar changes colour, and the marks drawn along it.
    WARN_DB = -18.0
    HOT_DB = -6.0
    MARKS_DB = (-48.0, -36.0, -24.0, -12.0, -6.0)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.level_db = self.FLOOR_DB
        self.peak_db = self.FLOOR_DB
        self.clipped = False
        self._peak_age = 0.0
        self._clip_age = 0.0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setToolTip("Peak level in dB below full scale. The red light means the signal clipped.")

    def sizeHint(self) -> QSize:
        return QSize(200, 16)

    def minimumSizeHint(self) -> QSize:
        return QSize(60, 12)

    def update_level(self, level_db: float, clipped: bool, seconds: float) -> None:
        """Show a new level, `seconds` of audio after the previous one."""
        level_db = min(max(level_db, self.FLOOR_DB), 0.0)
        fallen = self.level_db - self.FALL_DB_PER_SECOND * seconds
        self.level_db = max(level_db, fallen, self.FLOOR_DB)

        if level_db >= self.peak_db:
            self.peak_db = level_db
            self._peak_age = 0.0
        else:
            self._peak_age += seconds
            if self._peak_age >= self.PEAK_HOLD_SECONDS:
                self.peak_db = self.level_db
                self._peak_age = 0.0

        if clipped:
            self.clipped = True
            self._clip_age = 0.0
        elif self.clipped:
            self._clip_age += seconds
            if self._clip_age >= self.CLIP_HOLD_SECONDS:
                self.clipped = False

        self.update()

    def reset(self) -> None:
        """Back to silence, as when the stream stops."""
        self.level_db = self.FLOOR_DB
        self.peak_db = self.FLOOR_DB
        self.clipped = False
        self._peak_age = 0.0
        self._clip_age = 0.0
        self.update()

    def fraction(self, level_db: float) -> float:
        """Where a level sits along the bar, from 0 at the floor to 1 at full scale."""
        return min(max((level_db - self.FLOOR_DB) / -self.FLOOR_DB, 0.0), 1.0)

    def readout(self) -> str:
        """The held peak as text."""
        if self.peak_db <= self.FLOOR_DB:
            return f"< {self.FLOOR_DB:.0f} dB"
        return f"{self.peak_db:.0f} dB"

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        palette = self.palette()
        height = self.height()
        light = height  # the clip light is a square at the right end
        gap = 3
        bar = QRectF(0, 0, max(self.width() - light - gap, 1), height)

        painter.fillRect(bar, palette.color(palette.ColorRole.Base).darker(115))

        # The bar, in up to three colours
        zones = (
            (self.FLOOR_DB, self.WARN_DB, QColor(60, 170, 80)),
            (self.WARN_DB, self.HOT_DB, QColor(215, 180, 50)),
            (self.HOT_DB, 0.0, QColor(210, 70, 60)),
        )
        for low, high, colour in zones:
            if self.level_db <= low:
                break
            left = bar.width() * self.fraction(low)
            right = bar.width() * self.fraction(min(self.level_db, high))
            painter.fillRect(QRectF(left, 0, right - left, height), colour)

        # Scale marks
        painter.setPen(palette.color(palette.ColorRole.Mid))
        for mark in self.MARKS_DB:
            x = round(bar.width() * self.fraction(mark))
            painter.drawLine(x, height - 4, x, height)

        # Peak-hold marker
        if self.peak_db > self.FLOOR_DB:
            x = min(bar.width() * self.fraction(self.peak_db), bar.width() - 2)
            painter.fillRect(QRectF(x, 0, 2, height), palette.color(palette.ColorRole.Text))

        # Clip light
        lamp = QRectF(bar.width() + gap, 0, light, height)
        painter.fillRect(lamp, QColor(230, 40, 40) if self.clipped else palette.color(palette.ColorRole.Mid))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.end()
