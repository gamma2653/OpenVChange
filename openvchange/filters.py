"""Second-order filters: their design, and running them on a stream.

Every filter here is a biquad, described by three feed-forward coefficients `b` and
three feedback coefficients `a` with `a[0] == 1`. The designs are from the Audio EQ
Cookbook by Robert Bristow-Johnson.

Nothing here depends on Qt, on audio devices, or on SciPy.
"""

from __future__ import annotations

import cmath
import math

import numpy as np
import numpy.typing as npt

Coefficients = tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]

# Q of a second-order Butterworth filter, the flattest possible in its pass band.
BUTTERWORTH_Q = 1 / math.sqrt(2)


def normalised(b0: float, b1: float, b2: float, a0: float, a1: float, a2: float) -> Coefficients:
    return np.array([b0 / a0, b1 / a0, b2 / a0]), np.array([1.0, a1 / a0, a2 / a0])


def lowpass(freq: float, sample_rate: float, q: float = BUTTERWORTH_Q) -> Coefficients:
    """Passes what lies below `freq`, and falls by 12 dB per octave above it."""
    w0 = 2 * math.pi * freq / sample_rate
    alpha = math.sin(w0) / (2 * q)
    cos_w0 = math.cos(w0)
    return normalised((1 - cos_w0) / 2, 1 - cos_w0, (1 - cos_w0) / 2, 1 + alpha, -2 * cos_w0, 1 - alpha)


def highpass(freq: float, sample_rate: float, q: float = BUTTERWORTH_Q) -> Coefficients:
    """Passes what lies above `freq`, and falls by 12 dB per octave below it."""
    w0 = 2 * math.pi * freq / sample_rate
    alpha = math.sin(w0) / (2 * q)
    cos_w0 = math.cos(w0)
    return normalised((1 + cos_w0) / 2, -(1 + cos_w0), (1 + cos_w0) / 2, 1 + alpha, -2 * cos_w0, 1 - alpha)


def bandpass(freq: float, sample_rate: float, q: float) -> Coefficients:
    """Passes a band around `freq`, with unity gain at `freq` itself."""
    w0 = 2 * math.pi * freq / sample_rate
    alpha = math.sin(w0) / (2 * q)
    return normalised(alpha, 0.0, -alpha, 1 + alpha, -2 * math.cos(w0), 1 - alpha)


def shelf(freq: float, sample_rate: float, gain_db: float, high: bool, slope: float = 0.7) -> Coefficients:
    """Raises or lowers everything below `freq`, or above it if `high`, by `gain_db`."""
    amp = 10 ** (gain_db / 40)
    w0 = 2 * math.pi * freq / sample_rate
    cos_w0 = math.cos(w0)
    alpha = math.sin(w0) / 2 * math.sqrt((amp + 1 / amp) * (1 / slope - 1) + 2)
    edge = 2 * math.sqrt(amp) * alpha
    # The two kinds are mirror images: the sign of every cosine term is swapped.
    sign = -1.0 if high else 1.0
    return normalised(
        amp * ((amp + 1) - sign * (amp - 1) * cos_w0 + edge),
        sign * 2 * amp * ((amp - 1) - sign * (amp + 1) * cos_w0),
        amp * ((amp + 1) - sign * (amp - 1) * cos_w0 - edge),
        (amp + 1) + sign * (amp - 1) * cos_w0 + edge,
        sign * -2 * ((amp - 1) + sign * (amp + 1) * cos_w0),
        (amp + 1) + sign * (amp - 1) * cos_w0 - edge,
    )


def response_db(coefficients: Coefficients, freq: float, sample_rate: float) -> float:
    """Gain of a filter at one frequency, in dB."""
    b, a = coefficients
    z = cmath.exp(-2j * math.pi * freq / sample_rate)
    h = (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return 20 * math.log10(max(abs(h), 1e-15))


# How far the terms of a running sum may grow before the sum is started afresh.
# Far below the point where double precision overflows.
MAX_GROWTH = 1e200


class Biquad:
    """Runs a second-order filter over a stream, one buffer at a time.

    A filter like this feeds its own output back in, so each output depends on the one
    before and the obvious way to compute it is a loop over the samples. This instead
    splits the feedback into two one-pole stages, and uses the fact that a one-pole
    stage has a closed form:

        w[n] = p * w[n-1] + x[n]   is the same as   w[n] = p^n * (p * w[-1] + sum(x[k] / p^k))

    The sum is a cumulative sum, which NumPy computes for the whole buffer at once. The
    poles `p` of the filters used here come in complex pairs, so the stages work in
    complex numbers and the result is real again after the second one.

    The terms of the sum grow as 1 / |p|^k. Long buffers are therefore cut into pieces
    short enough for that to stay within range.
    """

    def __init__(self, coefficients: Coefficients, first_sample: float = 0.0) -> None:
        self.set_coefficients(coefficients)
        # Start as if the input had always been at the level of its first sample.
        # The filter then begins without a jolt.
        self.stage_one = first_sample / (1 - self.pole_one)
        settled = (self.stage_one / (1 - self.pole_two)).real
        self.stage_two = (settled, settled)  # the last output of stage two, and the one before

    def set_coefficients(self, coefficients: Coefficients) -> None:
        """Change what the filter does. Its state carries over."""
        b, a = coefficients
        self.b = (float(b[0]), float(b[1]), float(b[2]))
        root = cmath.sqrt(a[1] * a[1] - 4 * a[2])
        self.pole_one = (-a[1] + root) / 2
        self.pole_two = (-a[1] - root) / 2

        smallest = max(min(abs(self.pole_one), abs(self.pole_two)), 1e-12)
        self.piece = max(16, int(math.log(MAX_GROWTH) / -math.log(smallest))) if smallest < 1 else 1 << 30
        self._powers: tuple[int, tuple[npt.NDArray, ...]] | None = None

    def powers(self, n: int) -> tuple[npt.NDArray, ...]:
        """Each pole raised to 0..n-1, and one over that. Kept, since buffers rarely change size."""
        if self._powers is None or self._powers[0] < n:
            k = np.arange(n)
            one = self.pole_one**k
            two = self.pole_two**k
            self._powers = (n, (one, 1 / one, two, 1 / two))
        return tuple(table[:n] for table in self._powers[1])

    def process(self, data: npt.NDArray[np.floating]) -> npt.NDArray[np.float64]:
        """Filter the next buffer."""
        out = np.empty(len(data) + 2)
        out[:2] = self.stage_two[1], self.stage_two[0]
        samples = data.astype(np.complex128)

        for start in range(0, len(samples), self.piece):
            piece = samples[start : start + self.piece]
            one, one_inverse, two, two_inverse = self.powers(len(piece))

            first = one * (np.cumsum(piece * one_inverse) + self.pole_one * self.stage_one)
            second = two * (np.cumsum(first * two_inverse) + self.pole_two * out[start + 1])
            self.stage_one = first[-1]
            out[start + 2 : start + 2 + len(piece)] = second.real

        if len(data):
            self.stage_two = (float(out[-1]), float(out[-2]))
        b0, b1, b2 = self.b
        return b0 * out[2:] + b1 * out[1:-1] + b2 * out[:-2]
