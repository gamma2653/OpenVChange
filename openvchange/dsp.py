"""Signal processing for OpenVChange.

Everything here works on float32 NumPy arrays and knows nothing about Qt or audio
devices, so it can be tested and reused on its own. It needs NumPy and nothing else.
"""

import math

import numpy as np
import numpy.typing as npt

from openvchange import filters
from openvchange.formant import FormantShifter


def follow(
    levels: list[float], state: float, rising: float, falling: float
) -> tuple[npt.NDArray[np.float64], float]:
    """Follow `levels` with a one-pole filter that reacts at different speeds up and down.

    `rising` is the coefficient used while the input is above the follower, `falling`
    while it is below. Closer to 1 is slower, and 0 follows the input at once. Returns
    the follower per sample and its final value.

    Each value depends on the one before, so this cannot be done on whole arrays. It
    runs on plain Python floats, which is several times faster than looping over NumPy
    scalars, and everything around it is vectorised.
    """
    rising_in = 1 - rising
    falling_in = 1 - falling
    state = float(state)
    out = []
    append = out.append
    for level in levels:
        if level > state:
            state = rising * state + rising_in * level
        else:
            state = falling * state + falling_in * level
        append(state)
    return np.array(out, dtype=np.float64), state


def time_coefficient(time_ms: float, sample_rate: int) -> float:
    """One-pole coefficient that covers about 63% of a step in `time_ms`."""
    return math.exp(-1.0 / (time_ms * sample_rate / 1000))


# How long the expander remembers a peak. Long enough to bridge the gap between the
# peaks of a low note, short enough that the gate still starts closing promptly.
EXPANDER_DETECTOR_RELEASE_MS = 50.0

# The de-esser works on the band from 5 to 8 kHz, where "s" and "sh" sounds sit.
DEESSER_CENTER_HZ = math.sqrt(5000.0 * 8000.0)
DEESSER_Q = DEESSER_CENTER_HZ / (8000.0 - 5000.0)
DEESSER_ATTACK_MS = 1.0
DEESSER_RELEASE_MS = 50.0

# Formant shifts smaller than this, about a twentieth of a semitone, are skipped.
FORMANT_RATIO_MIN = 0.003

# Gain of a fully closed gate. Low enough to be inaudible, and finite so that the
# gate takes the same time to open however long it has been closed.
EXPANDER_FLOOR_DB = -80.0


class EffectsChain:
    """The effects, in the order the signal passes through them.

    Expander, high-pass, low-pass, bass shelf, treble shelf, de-esser, compressor,
    pitch shift, formant shift, delay, gain, soft clip.

    State is carried between calls to `process`, so audio can be fed in buffers of any
    size without clicks.
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        self.sample_rate = sample_rate

        # The filters in use, by name, each with the settings it was designed for.
        # A filter is dropped when it is switched off, so that it starts afresh.
        self.filter_states = {}

        # Highest level that reached the soft clipper in the last buffer. At 1.0 and
        # above the signal would have clipped outright without it.
        self.peak_before_clipping = 0.0

        # Filter parameters
        self.low_cut = 80
        self.high_cut = 16000
        self.low_pass_enabled = False
        self.high_pass_enabled = False

        # Bass and treble (in dB, 0 = no change)
        self.bass_gain = 0.0
        self.treble_gain = 0.0
        self.bass_freq = 250
        self.treble_freq = 4000

        # Delay (in milliseconds, 0 = no delay)
        self.delay_ms = 0
        self.delay_buffer_size = 480000  # ~10s at 48kHz
        self.delay_buffer = np.zeros(self.delay_buffer_size, dtype=np.float32)
        self.delay_write_pos = 0

        # Expander/Gate (replaces simple noise gate)
        self.expander_enabled = False
        self.expander_threshold = 0.01  # Linear (0-1)
        self.expander_ratio = 2.0  # 2:1 = soft, 10:1 = hard gate
        self.expander_attack_ms = 5.0  # How fast the gate opens
        self.expander_release_ms = 100.0  # How fast it closes
        self.expander_level = 0.0  # Detected signal level
        self.expander_gain_db = 0.0  # Current gain

        # Compressor
        self.compressor_enabled = False
        self.compressor_threshold_db = -10.0  # dB
        self.compressor_ratio = 4.0  # 4:1
        self.compressor_attack_ms = 10.0
        self.compressor_release_ms = 100.0
        self.compressor_makeup_db = 0.0
        self.compressor_envelope_db = -60.0  # Envelope in dB

        # De-esser
        self.deesser_enabled = False
        self.deesser_threshold_db = -20.0
        self.deesser_reduction_db = 6.0
        self.deesser_envelope = 0.0

        # Parameter smoothing
        self.gain_target = 1.0
        self.gain_smoothed = 1.0
        self.param_smooth_coeff = 0.995  # Per-sample smoothing

        # Pitch shift (in semitones, 0 = no change)
        self.pitch_semitones = 0.0
        self.pitch_window_size = 2048
        self.pitch_buffer_size = 8192
        self.pitch_buffer = np.zeros(self.pitch_buffer_size, dtype=np.float32)
        self.pitch_write_pos = 0
        # Use 4 overlapping read pointers for smoother output
        self.pitch_num_voices = 4
        self.pitch_read_pos = [0.0] * self.pitch_num_voices
        self.pitch_fade_pos = [i / self.pitch_num_voices for i in range(self.pitch_num_voices)]

        # Formants (in semitones). At 0 they are left where the pitch shifter puts
        # them, which is shifted along with the pitch. With `formant_preserve` they
        # are first moved back to where they were in the original voice.
        self.formant_semitones = 0.0
        self.formant_preserve = False
        self.formant_shifter = FormantShifter(sample_rate)

    def set_sample_rate(self, sample_rate: int) -> None:
        if sample_rate != self.sample_rate:
            self.formant_shifter = FormantShifter(sample_rate)
        self.sample_rate = sample_rate

    def reset(self) -> None:
        """Return to a clean state, as when a stream starts. Settings are kept."""
        self.reset_effect_states()
        self.delay_buffer = np.zeros(self.delay_buffer_size, dtype=np.float32)
        self.delay_write_pos = 0
        self.pitch_buffer = np.zeros(self.pitch_buffer_size, dtype=np.float32)
        self.pitch_write_pos = self.pitch_buffer_size // 2
        self.pitch_read_pos = [0.0] * self.pitch_num_voices
        self.pitch_fade_pos = [i / self.pitch_num_voices for i in range(self.pitch_num_voices)]

    def reset_effect_states(self) -> None:
        """Clear filter/envelope state so the chain restarts cleanly."""
        self.filter_states = {}
        self.formant_shifter.reset()
        self.expander_level = 0.0
        self.expander_gain_db = 0.0
        self.compressor_envelope_db = -60.0
        self.deesser_envelope = 0.0
        self.gain_smoothed = self.gain_target

    def set_gain(self, gain_db: float) -> None:
        self.gain_target = 10 ** (gain_db / 20)

    def set_low_cut(self, freq: float) -> None:
        self.low_cut = freq

    def set_high_cut(self, freq: float) -> None:
        self.high_cut = freq

    def set_bass(self, gain_db: float) -> None:
        self.bass_gain = gain_db

    def set_treble(self, gain_db: float) -> None:
        self.treble_gain = gain_db

    def set_high_pass_enabled(self, enabled: bool) -> None:
        self.high_pass_enabled = enabled

    def set_low_pass_enabled(self, enabled: bool) -> None:
        self.low_pass_enabled = enabled

    def set_expander_enabled(self, enabled: bool) -> None:
        self.expander_enabled = enabled

    def set_compressor_enabled(self, enabled: bool) -> None:
        self.compressor_enabled = enabled

    def set_deesser_enabled(self, enabled: bool) -> None:
        self.deesser_enabled = enabled

    def set_pitch_num_voices(self, num: int) -> None:
        """Set the number of pitch shift voices and reinitialize arrays."""
        self.pitch_num_voices = num
        self.pitch_read_pos = [0.0] * self.pitch_num_voices
        self.pitch_fade_pos = [i / self.pitch_num_voices for i in range(self.pitch_num_voices)]

    def set_delay(self, ms: float) -> None:
        """Set delay in milliseconds (0 to 10000)."""
        self.delay_ms = ms

    def set_formant(self, semitones: float) -> None:
        """Set formant shift in semitones (-12 to +12)."""
        self.formant_semitones = semitones

    def set_formant_preserve(self, enabled: bool) -> None:
        """Keep the formants of the original voice when the pitch is shifted."""
        self.formant_preserve = enabled

    def formant_ratio(self) -> float:
        """How far the formant shifter has to move the formants it is given."""
        semitones = self.formant_semitones
        if self.formant_preserve and abs(self.pitch_semitones) >= 0.1:
            # Undo what the pitch shifter did to them.
            semitones -= self.pitch_semitones
        return 2 ** (semitones / 12.0)

    def set_pitch(self, semitones: float) -> None:
        """Set pitch shift in semitones (-12 to +12)."""
        self.pitch_semitones = semitones

    # Expander setters
    def set_expander_threshold(self, percent: float) -> None:
        self.expander_threshold = percent / 100.0

    def set_expander_ratio(self, ratio: float) -> None:
        self.expander_ratio = ratio

    def set_expander_attack(self, ms: float) -> None:
        self.expander_attack_ms = ms

    def set_expander_release(self, ms: float) -> None:
        self.expander_release_ms = ms

    # Compressor setters
    def set_compressor_threshold(self, db: float) -> None:
        self.compressor_threshold_db = db

    def set_compressor_ratio(self, ratio: float) -> None:
        self.compressor_ratio = ratio

    def set_compressor_attack(self, ms: float) -> None:
        self.compressor_attack_ms = ms

    def set_compressor_release(self, ms: float) -> None:
        self.compressor_release_ms = ms

    def set_compressor_makeup(self, db: float) -> None:
        self.compressor_makeup_db = db

    # De-esser setters
    def set_deesser_threshold(self, db: float) -> None:
        self.deesser_threshold_db = db

    def set_deesser_reduction(self, db: float) -> None:
        self.deesser_reduction_db = db

    def apply_expander(self, data: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Turn the signal down while it is quieter than the threshold.

        The level is measured by a peak detector, not read off single samples, so a
        signal above the threshold passes unchanged even as its waveform crosses zero.
        The gain then opens at the attack speed and closes at the release speed.
        """
        if not self.expander_enabled:
            return data

        threshold = self.expander_threshold
        ratio = self.expander_ratio
        samples = data.astype(np.float64)

        # Level detector: jumps to each new peak, then decays.
        level, self.expander_level = follow(
            np.abs(samples).tolist(),
            self.expander_level,
            rising=0.0,
            falling=time_coefficient(EXPANDER_DETECTOR_RELEASE_MS, self.sample_rate),
        )

        # Below the threshold the gain falls with the distance in dB, scaled by the
        # ratio (2:1 turns 1 dB below into 2 dB below), down to the floor. Silence
        # closes the gate fully, and a threshold of zero leaves nothing below it.
        target_db = np.full(len(samples), EXPANDER_FLOOR_DB)
        target_db[level >= threshold] = 0.0
        below = (level < threshold) & (level > 0)
        db_below = 20 * np.log10(threshold / level[below])
        target_db[below] = np.maximum(-db_below * (ratio - 1), EXPANDER_FLOOR_DB)

        # Smooth the gain in dB, which is how loudness is heard: opening uses the
        # attack, closing the release.
        gain_db, self.expander_gain_db = follow(
            target_db.tolist(),
            self.expander_gain_db,
            rising=time_coefficient(self.expander_attack_ms, self.sample_rate),
            falling=time_coefficient(self.expander_release_ms, self.sample_rate),
        )
        return (samples * 10 ** (gain_db / 20)).astype(data.dtype)

    def apply_deesser(self, data: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Turn down the sibilant band, and only that band, while it is too loud.

        The band is limited to the threshold: it is turned down by as much as it
        exceeds the threshold, up to the reduction setting. Everything outside the
        band passes unchanged.
        """
        if not self.deesser_enabled:
            return data
        if DEESSER_CENTER_HZ >= 0.45 * self.sample_rate:
            return data  # the band does not fit below half the sample rate

        samples = data.astype(np.float64)
        band = self.filtered("deesser_band", samples, filters.bandpass, DEESSER_CENTER_HZ, DEESSER_Q)

        # How loud the band is
        envelope, self.deesser_envelope = follow(
            np.abs(band).tolist(),
            self.deesser_envelope,
            rising=time_coefficient(DEESSER_ATTACK_MS, self.sample_rate),
            falling=time_coefficient(DEESSER_RELEASE_MS, self.sample_rate),
        )

        # The reduction follows the envelope, so it moves as smoothly as the envelope.
        envelope_db = 20 * np.log10(np.maximum(envelope, 1e-10))
        reduction_db = np.clip(envelope_db - self.deesser_threshold_db, 0.0, self.deesser_reduction_db)
        band_gain = 10 ** (-reduction_db / 20)

        # Take away the share of the band that has to go. The filter never turns the
        # phase by more than a quarter cycle, so this can only reduce, never boost.
        return (samples - (1 - band_gain) * band).astype(data.dtype)

    def apply_compressor(self, data: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Apply dynamic range compression with attack/release."""
        if not self.compressor_enabled:
            return data

        attack_coeff = time_coefficient(self.compressor_attack_ms, self.sample_rate)
        release_coeff = time_coefficient(self.compressor_release_ms, self.sample_rate)

        threshold_db = self.compressor_threshold_db
        ratio = self.compressor_ratio
        makeup_linear = 10 ** (self.compressor_makeup_db / 20)

        # Convert to dB in the precision of the input, with a floor to avoid log(0)
        level = np.abs(data)
        silent = level < 1e-10
        level_db = (20 * np.log10(np.where(silent, 1.0, level).astype(data.dtype))).astype(np.float64)
        level_db[silent] = -200.0

        # Envelope follower in dB domain
        envelope_db, self.compressor_envelope_db = follow(
            level_db.tolist(), self.compressor_envelope_db, rising=attack_coeff, falling=release_coeff
        )

        # Calculate gain reduction
        gain_reduction_db = np.where(envelope_db > threshold_db, (envelope_db - threshold_db) * (1 - 1 / ratio), 0.0)

        # Apply gain reduction and makeup
        gain_linear = 10 ** (-gain_reduction_db / 20) * makeup_linear
        return (data.astype(np.float64) * gain_linear).astype(data.dtype)

    def apply_pitch_shift(self, data: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Apply pitch shift using multi-pointer delay line with crossfade.

        Multiple read pointers traverse a circular buffer at the shifted rate.
        Each pointer has an independent fade phase that controls its amplitude.
        When the fade of a pointer reaches zero, it resets to a new position.
        More pointers = smoother sound with less artifacts.
        """
        if abs(self.pitch_semitones) < 0.1:
            return data

        samples = data.astype(np.float32)
        output = np.empty(len(samples), dtype=np.float32)
        # A piece must fit in the buffer, or it would overwrite what it still has to read.
        piece_size = self.pitch_buffer_size
        for start in range(0, len(samples), piece_size):
            piece = samples[start : start + piece_size]
            output[start : start + len(piece)] = self._pitch_shift_piece(piece)
        return output

    def _pitch_shift_piece(self, piece: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        n = len(piece)
        size = self.pitch_buffer_size
        buf = self.pitch_buffer
        write_start = self.pitch_write_pos
        shift_factor = 2 ** (self.pitch_semitones / 12.0)
        fade_inc = 1.0 / self.pitch_window_size

        # Write the whole piece first, keeping what it overwrites: a voice reading a
        # slot before its sample has been written must still see the old content.
        written = (write_start + np.arange(n)) % size
        overwritten = buf[written].copy()
        buf[written] = piece
        sample_index = np.arange(n)

        mixed = np.zeros(n, dtype=np.float64)
        total_weight = np.zeros(n, dtype=np.float64)
        for v in range(self.pitch_num_voices):
            positions, fades = self._pitch_voice_path(v, n, write_start, shift_factor, fade_inc)

            # Read with linear interpolation
            whole = positions.astype(np.int64)
            frac = positions - whole
            idx = whole % size
            sample = self._pitch_read(idx, sample_index, write_start, overwritten) * (1 - frac) + (
                self._pitch_read((idx + 1) % size, sample_index, write_start, overwritten) * frac
            )

            # Hann window for crossfade
            fade = 0.5 * (1.0 - np.cos(2.0 * np.pi * fades))
            mixed += sample * fade
            total_weight += fade

        self.pitch_write_pos = (write_start + n) % size
        audible = total_weight > 0.001
        return np.where(audible, mixed / np.where(audible, total_weight, 1.0), 0.0).astype(np.float32)

    def _pitch_read(
        self,
        idx: npt.NDArray[np.int64],
        sample_index: npt.NDArray[np.int64],
        write_start: int,
        overwritten: npt.NDArray[np.float32],
    ) -> npt.NDArray[np.float64]:
        """Buffer content at `idx` as each sample would have seen it."""
        values = self.pitch_buffer[idx].astype(np.float64)
        # Slots this piece wrote to, counted from its first sample.
        slot = (idx - write_start) % self.pitch_buffer_size
        not_yet_written = (slot < len(overwritten)) & (slot > sample_index)
        values[not_yet_written] = overwritten[slot[not_yet_written]]
        return values

    def _pitch_voice_path(
        self, v: int, n: int, write_start: int, shift_factor: float, fade_inc: float
    ) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
        """Read position and fade phase of one voice for each of the next `n` samples.

        Both advance by repeated addition, which `np.add.accumulate` reproduces exactly.
        The run is cut wherever the read position wraps or the fade completes a cycle.
        """
        size = self.pitch_buffer_size
        positions = np.empty(n, dtype=np.float64)
        fades = np.empty(n, dtype=np.float64)
        read_pos = self.pitch_read_pos[v]
        fade_pos = self.pitch_fade_pos[v]

        done = 0
        while done < n:
            remaining = n - done
            steps = np.empty(remaining + 1, dtype=np.float64)
            steps[0] = read_pos
            steps[1:] = shift_factor
            run_positions = np.add.accumulate(steps)
            steps[0] = fade_pos
            steps[1:] = fade_inc
            run_fades = np.add.accumulate(steps)

            # Element k + 1 is the state after sample k. Find the first sample that
            # ends with a wrap or a completed fade.
            event = (run_positions[1:] >= size) | (run_positions[1:] < 0) | (run_fades[1:] >= 1.0)
            count = int(np.argmax(event)) + 1 if event.any() else remaining

            positions[done : done + count] = run_positions[:count]
            fades[done : done + count] = run_fades[:count]
            read_pos = float(run_positions[count])
            fade_pos = float(run_fades[count])

            # Wrap read position
            if read_pos >= size:
                read_pos -= size
            elif read_pos < 0:
                read_pos += size

            # Reset when fade cycle completes
            if fade_pos >= 1.0:
                fade_pos -= 1.0
                write_pos = (write_start + done + count - 1) % size
                read_pos = float((write_pos - size // 2) % size)

            done += count

        self.pitch_read_pos[v] = read_pos
        self.pitch_fade_pos[v] = fade_pos
        return positions, fades

    def apply_formant_shift(self, data: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Move the formants, unless they are to stay where they are.

        While it is in use this adds `formant_shifter.latency` samples of delay.
        """
        ratio = self.formant_ratio()
        if abs(ratio - 1.0) < FORMANT_RATIO_MIN:
            if self.formant_shifter.active:
                self.formant_shifter.reset()
            return data
        return self.formant_shifter.process(data, ratio)

    def apply_delay(self, data: npt.NDArray[np.floating]) -> npt.NDArray[np.float32]:
        """Delay the signal through a circular buffer."""
        size = self.delay_buffer_size
        delay_samples = min(int(self.delay_ms * self.sample_rate / 1000), size - 1)
        buf = self.delay_buffer
        write_pos = self.delay_write_pos
        samples = data.astype(np.float32)
        output = np.empty(len(samples), dtype=np.float32)

        # Work in pieces no longer than the buffer, so a piece never overwrites itself.
        for start in range(0, len(samples), size):
            piece = samples[start : start + size]
            n = len(piece)
            out = output[start : start + n]

            # The first `delay_samples` outputs are older than this piece, so read them
            # before the piece is written. The rest come from the piece itself.
            from_buffer = min(n, delay_samples)
            out[:from_buffer] = buf[(write_pos - delay_samples + np.arange(from_buffer)) % size]
            out[from_buffer:] = piece[: n - from_buffer]

            buf[(write_pos + np.arange(n)) % size] = piece
            write_pos = (write_pos + n) % size

        self.delay_write_pos = write_pos
        return output

    def apply_gain(self, data: npt.NDArray[np.floating]) -> npt.NDArray[np.floating]:
        """Apply the output gain, gliding towards a new setting instead of jumping."""
        target = self.gain_target
        gain = self.gain_smoothed
        step = 1 - self.param_smooth_coeff
        n = len(data)

        # Follow the glide sample by sample until it stops moving, which it has
        # already done unless the gain was changed a moment ago.
        gains = None
        for i in range(n):
            moved = gain + (target - gain) * step
            if moved == gain:
                break
            if gains is None:
                gains = np.empty(n, dtype=np.float64)
            gain = moved
            gains[i] = gain
        else:
            i = n
        self.gain_smoothed = gain

        # Multiply in double precision and round once, whatever the input type.
        samples = data.astype(np.float64)
        if gains is None:
            return (samples * gain).astype(data.dtype)
        gains[i:] = gain
        return (samples * gains).astype(data.dtype)

    def filtered(self, name: str, data: npt.NDArray[np.floating], design, freq: float, *params: float) -> npt.NDArray[np.float64]:
        """Run `data` through the filter called `name`.

        `design` is one of the functions in `filters`. The filter is designed again
        only when its settings or the sample rate change, and it keeps its state from
        buffer to buffer and across a redesign, so neither causes a click.
        """
        settings = (design, freq, self.sample_rate, *params)
        state = self.filter_states.get(name)
        if state is None:
            biquad = filters.Biquad(design(freq, self.sample_rate, *params), float(data[0]))
            self.filter_states[name] = (settings, biquad)
        elif state[0] != settings:
            biquad = state[1]
            biquad.set_coefficients(design(freq, self.sample_rate, *params))
            self.filter_states[name] = (settings, biquad)
        else:
            biquad = state[1]
        return biquad.process(data)

    def process(self, data: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        """Run one buffer of samples in [-1, 1] through the chain."""
        if len(data) == 0:
            return data

        # Expander/Gate (smooth envelope-based)
        data = self.apply_expander(data)

        # High-pass filter (remove low frequencies)
        if self.high_pass_enabled and self.low_cut > 20:
            if self.low_cut < self.sample_rate / 2:
                data = self.filtered("highpass", data, filters.highpass, self.low_cut)
        else:
            self.filter_states.pop("highpass", None)

        # Low-pass filter (remove high frequencies)
        if self.low_pass_enabled and self.high_cut < (self.sample_rate / 2 - 100):
            data = self.filtered("lowpass", data, filters.lowpass, self.high_cut)
        else:
            self.filter_states.pop("lowpass", None)

        # Bass shelf filter
        if abs(self.bass_gain) > 0.5:
            data = self.filtered("bass", data, filters.shelf, self.bass_freq, self.bass_gain, False)
        else:
            self.filter_states.pop("bass", None)

        # Treble shelf filter
        if abs(self.treble_gain) > 0.5:
            data = self.filtered("treble", data, filters.shelf, self.treble_freq, self.treble_gain, True)
        else:
            self.filter_states.pop("treble", None)

        # De-esser (before compressor)
        data = self.apply_deesser(data)

        # Compressor
        data = self.apply_compressor(data)

        # Apply pitch shift
        if abs(self.pitch_semitones) >= 0.1:
            data = self.apply_pitch_shift(data)

        # Apply formant shift
        data = self.apply_formant_shift(data)

        # Apply delay
        if self.delay_ms > 0:
            data = self.apply_delay(data)

        # Apply gain (smoothed to prevent clicks)
        data = self.apply_gain(data)

        # Soft clipping using tanh for smoother limiting
        self.peak_before_clipping = float(np.max(np.abs(data)))
        return np.tanh(data)
