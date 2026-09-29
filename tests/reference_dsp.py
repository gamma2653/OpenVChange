"""The original, sample-by-sample implementations of the effects.

These are slow but obviously correct, and they define what the optimised versions in
`openvchange.dsp` must produce. Each function takes and returns its state explicitly.
"""

from __future__ import annotations

import numpy as np


def delay(data: np.ndarray, buffer: np.ndarray, write_pos: int, delay_samples: int) -> tuple[np.ndarray, int]:
    """Circular-buffer delay. Modifies `buffer` in place. Returns (output, write_pos)."""
    size = len(buffer)
    output = np.empty(len(data), dtype=np.float32)
    for i in range(len(data)):
        buffer[write_pos] = data[i]
        output[i] = buffer[(write_pos - delay_samples) % size]
        write_pos = (write_pos + 1) % size
    return output, write_pos


def smoothed_gain(data: np.ndarray, smoothed: float, target: float, coeff: float) -> tuple[np.ndarray, float]:
    """One-pole glide towards `target`, applied per sample. Returns (output, smoothed)."""
    output = np.empty_like(data)
    for i in range(len(data)):
        smoothed += (target - smoothed) * (1 - coeff)
        output[i] = data[i] * smoothed
    return output, smoothed
