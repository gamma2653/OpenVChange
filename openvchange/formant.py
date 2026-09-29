"""Moving the formants of a voice without moving its pitch.

A voice is a buzz from the vocal cords, shaped by the resonances of the throat and
mouth. The buzz sets the pitch. The resonances, called formants, set which vowel is
heard and how large the speaker sounds. In the spectrum the buzz is a row of fine,
evenly spaced peaks, and the formants are the broad outline over them, the spectral
envelope.

`FormantShifter` works on short overlapping frames. For each it estimates the envelope,
works out where the envelope would be if it were stretched along the frequency axis, and
scales every frequency by the ratio of the two. The fine peaks stay where they are, so
the pitch does not change.

Nothing here depends on Qt or on audio devices.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

# Frames last about this long. Long enough to see the shape of the spectrum, short
# enough that the delay is hard to notice.
FRAME_SECONDS = 0.0213

# Each frame starts a quarter of a frame after the one before.
OVERLAP = 4

# The envelope is the part of the spectrum that varies slowly along the frequency axis.
# How slowly is set per frame from the pitch: the envelope may hold detail down to
# this share of the pitch period, within the limits below. More would let the peaks of
# the pitch itself into the envelope, and they would then be moved along with it.
ENVELOPE_SHARE_OF_PERIOD = 0.6
ENVELOPE_SECONDS_MIN = 0.0015
ENVELOPE_SECONDS_MAX = 0.006

# Pitches looked for, and how strong the sign of a pitch has to be to count.
PITCH_HZ_MIN = 70.0
PITCH_HZ_MAX = 500.0
PITCH_STRENGTH_MIN = 0.08

# A plain smoothed spectrum runs through the middle of the pitch peaks. Formants are
# better described by a line over their tops, which these passes move towards.
ENVELOPE_PASSES = 3

# The most that any frequency is turned up or down. Without a limit, a frequency that
# is nearly absent could be raised until it is all noise.
MAX_CHANGE_DB = 30.0

# Levels below this are treated as silence when the envelope is estimated.
FLOOR = 1e-6


class FormantShifter:
    """Shifts formants by a ratio, frame by frame, on a continuous stream.

    Audio can be fed in buffers of any size and the result does not depend on the
    size. The output is `latency` samples behind the input.
    """

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self.frame_size = int(2 ** round(np.log2(sample_rate * FRAME_SECONDS)))
        self.hop = self.frame_size // OVERLAP
        self.latency = self.frame_size

        n = self.frame_size
        # The square root of a Hann window on the way in and again on the way out.
        # Their product is a Hann window, and Hann windows a quarter apart add up to
        # a constant, which is divided out here.
        hann = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(n) / n)
        self.window = np.sqrt(hann) / np.sqrt(OVERLAP / 2)

        # Where in the cepstrum a pitch would show, and how much of it the envelope keeps
        self.pitch_range = (round(sample_rate / PITCH_HZ_MAX), min(n // 2 - 1, round(sample_rate / PITCH_HZ_MIN)))
        self.keep_range = (round(sample_rate * ENVELOPE_SECONDS_MIN), round(sample_rate * ENVELOPE_SECONDS_MAX))
        self._lifters: dict[int, npt.NDArray[np.float64]] = {}

        self.bins = np.arange(n // 2 + 1, dtype=np.float64)
        self.max_gain = 10 ** (MAX_CHANGE_DB / 20)
        self.reset()

    def reset(self) -> None:
        """Forget everything heard so far."""
        n = self.frame_size
        self.recent = np.zeros(n)  # the last frame's worth of input
        self.mix = np.zeros(n)  # frames being added together on their way out
        self.pending = np.zeros(0)  # input that does not fill a hop yet
        self.ready = np.zeros(self.hop)  # output waiting to be collected
        self.active = False

    def lifter(self, keep: int) -> npt.NDArray[np.float64]:
        """Selects the first `keep` values of a cepstrum, and their mirror images."""
        lifter = self._lifters.get(keep)
        if lifter is None:
            lifter = np.zeros(self.frame_size)
            lifter[:keep] = 1.0
            lifter[self.frame_size - keep + 1 :] = 1.0
            self._lifters[keep] = lifter
        return lifter

    def envelope(self, magnitude: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """The broad outline of a magnitude spectrum."""
        n = self.frame_size
        log_magnitude = np.log(np.maximum(magnitude, FLOOR))
        cepstrum = np.fft.irfft(log_magnitude, n=n)

        # A pitch shows as a peak in the cepstrum at its period. Without one, as in
        # a hiss or a whisper, there are no pitch peaks to keep out of the envelope.
        low, high = self.pitch_range
        period = low + int(np.argmax(cepstrum[low:high]))
        if cepstrum[period] < PITCH_STRENGTH_MIN:
            period = high
        keep = int(np.clip(round(ENVELOPE_SHARE_OF_PERIOD * period), *self.keep_range))
        lifter = self.lifter(keep)

        envelope = np.fft.rfft(cepstrum * lifter).real
        for _ in range(ENVELOPE_PASSES):
            raised = np.maximum(log_magnitude, envelope)
            envelope = np.fft.rfft(np.fft.irfft(raised, n=n) * lifter).real
        return np.exp(envelope)

    def gains(self, magnitude: npt.NDArray[np.float64], ratio: float) -> npt.NDArray[np.float64]:
        """How much to scale each frequency to move the envelope by `ratio`."""
        envelope = self.envelope(magnitude)
        # The envelope wanted at a frequency is the one found at that frequency
        # divided by the ratio. Past the top of the spectrum the last value is used.
        moved = np.interp(self.bins / ratio, self.bins, envelope)
        return np.clip(moved / envelope, 1 / self.max_gain, self.max_gain)

    def process(self, data: npt.NDArray[np.floating], ratio: float) -> npt.NDArray[np.float32]:
        """Shift the formants of the next buffer. Above 1 moves them up."""
        self.active = True
        n = len(data)
        hop = self.hop
        pending = np.concatenate([self.pending, data.astype(np.float64)])
        produced = [self.ready]

        for start in range(0, len(pending) - hop + 1, hop):
            self.recent = np.concatenate([self.recent[hop:], pending[start : start + hop]])
            spectrum = np.fft.rfft(self.recent * self.window)
            spectrum *= self.gains(np.abs(spectrum), ratio)
            self.mix += np.fft.irfft(spectrum, n=self.frame_size) * self.window
            produced.append(self.mix[:hop].copy())
            self.mix = np.concatenate([self.mix[hop:], np.zeros(hop)])

        self.pending = pending[len(pending) - len(pending) % hop :]
        out = np.concatenate(produced)
        self.ready = out[n:]
        return out[:n].astype(np.float32)
