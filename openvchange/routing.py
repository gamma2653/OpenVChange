"""Carrying audio between devices that do not share a clock. No Qt, no PyAudio."""

from __future__ import annotations

import threading

import numpy as np
import numpy.typing as npt

# Devices hand audio over in periods of about this long, whatever buffer size is asked
# for, so with small buffers several arrive at once and then none for a while.
DEVICE_PERIOD_SECONDS = 0.01

# How quickly a link's idea of its usual fill follows the actual fill.
FILL_AVERAGING_SECONDS = 0.5

# Where the limiter starts to act, as a fraction of full scale.
LIMIT_KNEE = 0.8


class Link:
    """A queue of samples from the audio thread of one device to that of another.

    Every device has a clock of its own, so an input delivers slightly more or fewer
    samples per second than an output takes. The difference shows up a whole burst at a
    time: for a long while each read finds the same amount waiting, and then, once the
    two devices have slipped past each other, one burst more or less. Left alone, the
    queue would run empty or fill up within minutes.

    The link therefore watches how full it usually is. When that moves half a burst away
    from where it started, the link hands out one sample more or fewer than it takes in,
    per read, until the fill is back. Such a read is stretched by interpolation, which
    changes the pitch by less than two cents at 1024 samples. All other reads return
    exactly what was written.

    Nothing comes out until `target` samples are waiting, which is two bursts: one that
    a read may take at once, and one to lose when the devices slip. That is the delay a
    link adds. If the queue runs empty anyway, the read is padded with silence and the
    link waits for `target` samples again. If nobody reads, the oldest audio is dropped.

    `write` and `read` may be called from different threads.
    """

    def __init__(self, block: int, sample_rate: int) -> None:
        burst = max(block, round(DEVICE_PERIOD_SECONDS * sample_rate))
        self.target = 2 * burst
        self.most = 4 * burst
        self.capacity = 6 * burst

        # The reads of one burst find less and less waiting. This is how far their
        # average lies below what the first of them finds.
        within_burst = (burst - block) // 2
        self.usual_target = self.target - within_burst
        self.low = self.usual_target - burst // 2
        self.high = self.usual_target + burst // 2
        self.averaging = min(1.0, block / (FILL_AVERAGING_SECONDS * sample_rate))

        self.samples = np.zeros(self.capacity, dtype=np.float32)
        self.fill = 0
        self.flowing = False
        self.usual_fill = 0.0
        self.correction = 0  # extra samples taken per read: -1, 0, or 1
        self.lock = threading.Lock()

    def write(self, data: npt.NDArray[np.floating]) -> None:
        """Add samples at the end of the queue."""
        data = np.asarray(data, dtype=np.float32)[-self.capacity :]
        with self.lock:
            if self.fill + len(data) > self.capacity:
                self._drop(max(self.fill + len(data) - self.capacity, self.fill - self.target))
            self.samples[self.fill : self.fill + len(data)] = data
            self.fill += len(data)

    def read(self, count: int) -> npt.NDArray[np.float32]:
        """Take `count` samples from the front of the queue, or silence while it fills."""
        with self.lock:
            if self.fill > self.most:
                # The reader stood still for a while. Catch up at once, not sample by sample.
                self._drop(self.fill - self.target)
                self.flowing = False
            if not self.flowing:
                if self.fill < self.target:
                    return np.zeros(count, dtype=np.float32)
                self.flowing = True
                self.usual_fill = float(self.usual_target + self.fill - self.target)
                self.correction = 0

            self.usual_fill += (self.fill - self.usual_fill) * self.averaging
            if self.usual_fill > self.high:
                self.correction = 1
            elif self.usual_fill < self.low:
                self.correction = -1
            elif (self.usual_fill - self.usual_target) * self.correction <= 0:
                self.correction = 0

            taken = count + self.correction
            if self.fill < taken:
                out = np.zeros(count, dtype=np.float32)
                out[: self.fill] = self.samples[: self.fill]
                self.fill = 0
                self.flowing = False
                return out

            if taken == count:
                out = self.samples[:count].copy()
            else:
                # One sample past the end keeps the last stretch of the curve honest.
                known = self.samples[: min(taken + 1, self.fill)]
                out = np.interp(np.arange(count) * (taken / count), np.arange(len(known)), known).astype(np.float32)
            self._drop(taken)
            return out

    def _drop(self, count: int) -> None:
        """Remove the oldest `count` samples. The caller holds the lock."""
        count = min(count, self.fill)
        self.samples[: self.fill - count] = self.samples[count : self.fill]
        self.fill -= count

def limit(data: npt.NDArray[np.floating]) -> npt.NDArray[np.float32]:
    """Keep a mix below full scale. Anything below `LIMIT_KNEE` passes unchanged."""
    data = np.asarray(data, dtype=np.float32)
    size = np.abs(data)
    room = 1.0 - LIMIT_KNEE
    squeezed = LIMIT_KNEE + room * np.tanh((size - LIMIT_KNEE) / room)
    return np.where(size > LIMIT_KNEE, np.sign(data) * squeezed, data).astype(np.float32)

