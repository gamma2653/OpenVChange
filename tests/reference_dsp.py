"""The original, sample-by-sample implementations of the effects.

These are slow but obviously correct, and they define what the optimised versions in
`openvchange.dsp` must produce. Each function takes and returns its state explicitly.

The originals mixed float32 samples with Python floats, which NumPy 1 evaluates in double
precision. That is spelled out here with `float()`, so the reference means the same thing
under any NumPy version.
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
        output[i] = float(data[i]) * smoothed
    return output, smoothed


class PitchState:
    """State of the reference pitch shifter, as it is when a stream starts."""

    def __init__(self, voices: int = 4, window_size: int = 2048, buffer_size: int = 8192) -> None:
        self.window_size = window_size
        self.buffer_size = buffer_size
        self.voices = voices
        self.buffer = np.zeros(buffer_size, dtype=np.float32)
        self.write_pos = buffer_size // 2
        self.read_pos = [0.0] * voices
        self.fade_pos = [i / voices for i in range(voices)]


def pitch_shift(data: np.ndarray, semitones: float, state: PitchState) -> np.ndarray:
    """Delay-line pitch shifter with Hann-crossfaded voices. Updates `state` in place."""
    shift_factor = 2 ** (semitones / 12.0)
    buf_size = state.buffer_size
    fade_inc = 1.0 / state.window_size

    output = np.zeros(len(data), dtype=np.float32)

    for i in range(len(data)):
        state.buffer[state.write_pos] = data[i]

        mixed_sample = 0.0
        total_weight = 0.0

        for v in range(state.voices):
            idx = int(state.read_pos[v]) % buf_size
            frac = state.read_pos[v] - int(state.read_pos[v])
            sample = float(state.buffer[idx]) * (1 - frac) + float(state.buffer[(idx + 1) % buf_size]) * frac

            fade = 0.5 * (1.0 - np.cos(2.0 * np.pi * state.fade_pos[v]))

            mixed_sample += sample * fade
            total_weight += fade

            state.read_pos[v] += shift_factor

            if state.read_pos[v] >= buf_size:
                state.read_pos[v] -= buf_size
            elif state.read_pos[v] < 0:
                state.read_pos[v] += buf_size

            state.fade_pos[v] += fade_inc

            if state.fade_pos[v] >= 1.0:
                state.fade_pos[v] -= 1.0
                state.read_pos[v] = float((state.write_pos - buf_size // 2) % buf_size)

        if total_weight > 0.001:
            output[i] = mixed_sample / total_weight
        else:
            output[i] = 0.0

        state.write_pos = (state.write_pos + 1) % buf_size

    return output


def expander(
    data: np.ndarray,
    envelope: float,
    sample_rate: int,
    threshold: float,
    ratio: float,
    attack_ms: float,
    release_ms: float,
) -> tuple[np.ndarray, float]:
    """Downward expander acting on the level of each sample. Returns (output, envelope)."""
    attack_coeff = np.exp(-1.0 / (attack_ms * sample_rate / 1000))
    release_coeff = np.exp(-1.0 / (release_ms * sample_rate / 1000))

    output = np.empty_like(data)
    for i in range(len(data)):
        sample_level = float(abs(data[i]))

        if sample_level > threshold:
            target_gain = 1.0
        elif threshold > 0 and sample_level > 0:
            db_below = 20 * np.log10(threshold / sample_level)
            gain_reduction_db = db_below * (ratio - 1)
            target_gain = 10 ** (-gain_reduction_db / 20)
        else:
            target_gain = 0.0

        if target_gain < envelope:
            envelope = attack_coeff * envelope + (1 - attack_coeff) * target_gain
        else:
            envelope = release_coeff * envelope + (1 - release_coeff) * target_gain

        output[i] = float(data[i]) * envelope

    return output, float(envelope)


def deesser(
    data: np.ndarray,
    sidechain: np.ndarray,
    envelope: float,
    sample_rate: int,
    threshold_db: float,
    reduction_db: float,
) -> tuple[np.ndarray, float]:
    """Turns the signal down while the sidechain is loud. Returns (output, envelope)."""
    attack_coeff = np.exp(-1.0 / (1.0 * sample_rate / 1000))
    release_coeff = np.exp(-1.0 / (50.0 * sample_rate / 1000))

    threshold_linear = 10 ** (threshold_db / 20)
    reduction_linear = 10 ** (-reduction_db / 20)

    output = np.empty_like(data)
    for i in range(len(data)):
        sc_level = abs(sidechain[i])
        if sc_level > envelope:
            envelope = attack_coeff * envelope + (1 - attack_coeff) * sc_level
        else:
            envelope = release_coeff * envelope + (1 - release_coeff) * sc_level

        if envelope > threshold_linear:
            output[i] = float(data[i]) * reduction_linear
        else:
            output[i] = data[i]

    return output, float(envelope)


def compressor(
    data: np.ndarray,
    envelope_db: float,
    sample_rate: int,
    threshold_db: float,
    ratio: float,
    attack_ms: float,
    release_ms: float,
    makeup_db: float,
) -> tuple[np.ndarray, float]:
    """Compressor with a follower in the dB domain. Returns (output, envelope_db)."""
    attack_coeff = np.exp(-1.0 / (attack_ms * sample_rate / 1000))
    release_coeff = np.exp(-1.0 / (release_ms * sample_rate / 1000))
    makeup_linear = 10 ** (makeup_db / 20)

    output = np.empty_like(data)
    for i in range(len(data)):
        # The logarithm is taken in the precision of the input.
        sample_abs = max(abs(data[i]), 1e-10)
        sample_db = float(20 * np.log10(sample_abs))

        if sample_db > envelope_db:
            envelope_db = attack_coeff * envelope_db + (1 - attack_coeff) * sample_db
        else:
            envelope_db = release_coeff * envelope_db + (1 - release_coeff) * sample_db

        if envelope_db > threshold_db:
            overshoot_db = envelope_db - threshold_db
            gain_reduction_db = overshoot_db * (1 - 1 / ratio)
        else:
            gain_reduction_db = 0.0

        gain_linear = 10 ** (-gain_reduction_db / 20) * makeup_linear
        output[i] = float(data[i]) * gain_linear

    return output, float(envelope_db)
