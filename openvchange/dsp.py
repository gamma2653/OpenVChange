"""Signal processing for OpenVChange.

Everything here works on float32 NumPy arrays and knows nothing about Qt or audio
devices, so it can be tested and reused on its own.
"""

import numpy as np
import numpy.typing as npt
from scipy import signal


class EffectsChain:
    """The effects, in the order the signal passes through them.

    Expander, high-pass, low-pass, bass shelf, treble shelf, de-esser, compressor,
    pitch shift, delay, gain, soft clip.

    State is carried between calls to `process`, so audio can be fed in buffers of any
    size without clicks.
    """

    def __init__(self, sample_rate: int = 44100) -> None:
        self.sample_rate = sample_rate

        # Filter states (preserved between chunks)
        self.filter_states = {}

        # Filter coefficients, redesigned only when the settings behind them change
        self._coefficients = {}

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
        self.expander_attack_ms = 5.0  # Fast attack
        self.expander_release_ms = 100.0  # Slow release
        self.expander_envelope = 1.0  # Current gain envelope

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

    def set_sample_rate(self, sample_rate: int) -> None:
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
        self.expander_envelope = 1.0
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

    def apply_expander(self, data: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        """Apply smooth expander/gate with envelope follower."""
        if not self.expander_enabled:
            return data

        # Calculate attack/release coefficients
        attack_coeff = np.exp(-1.0 / (self.expander_attack_ms * self.sample_rate / 1000))
        release_coeff = np.exp(-1.0 / (self.expander_release_ms * self.sample_rate / 1000))

        threshold = self.expander_threshold
        ratio = self.expander_ratio

        output = np.empty_like(data)
        for i in range(len(data)):
            # Envelope follower - track signal level
            sample_level = abs(data[i])

            # Determine target gain based on level vs threshold
            if sample_level > threshold:
                target_gain = 1.0
            else:
                # Below threshold: reduce gain proportionally based on ratio
                if threshold > 0 and sample_level > 0:
                    # How many dB below threshold
                    db_below = 20 * np.log10(threshold / sample_level)
                    # Expand by ratio (e.g., 2:1 means 1dB below becomes 2dB below)
                    gain_reduction_db = db_below * (ratio - 1)
                    target_gain = 10 ** (-gain_reduction_db / 20)
                else:
                    target_gain = 0.0

            # Smooth envelope with attack/release
            if target_gain < self.expander_envelope:
                # Signal dropping - use attack (fast response)
                self.expander_envelope = attack_coeff * self.expander_envelope + (1 - attack_coeff) * target_gain
            else:
                # Signal rising - use release (slow response)
                self.expander_envelope = release_coeff * self.expander_envelope + (1 - release_coeff) * target_gain

            output[i] = data[i] * self.expander_envelope

        return output

    def apply_deesser(self, data: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        """Apply de-esser using bandpass sidechain detection."""
        if not self.deesser_enabled:
            return data

        # Create bandpass filter for sibilance detection (5-8 kHz)
        nyquist = self.sample_rate / 2
        low_freq = min(5000 / nyquist, 0.99)
        high_freq = min(8000 / nyquist, 0.99)

        if low_freq >= high_freq:
            return data

        b, a = self.coefficients("deesser_sidechain", "bandpass", low_freq, high_freq)
        sidechain = self.apply_filter_with_state(b, a, data.copy(), "deesser_sidechain")

        # Fast envelope follower for sidechain
        attack_coeff = np.exp(-1.0 / (1.0 * self.sample_rate / 1000))  # 1ms attack
        release_coeff = np.exp(-1.0 / (50.0 * self.sample_rate / 1000))  # 50ms release

        threshold_linear = 10 ** (self.deesser_threshold_db / 20)
        reduction_linear = 10 ** (-self.deesser_reduction_db / 20)

        output = np.empty_like(data)
        for i in range(len(data)):
            # Track sidechain envelope
            sc_level = abs(sidechain[i])
            if sc_level > self.deesser_envelope:
                self.deesser_envelope = attack_coeff * self.deesser_envelope + (1 - attack_coeff) * sc_level
            else:
                self.deesser_envelope = release_coeff * self.deesser_envelope + (1 - release_coeff) * sc_level

            # Apply gain reduction when sidechain exceeds threshold
            if self.deesser_envelope > threshold_linear:
                output[i] = data[i] * reduction_linear
            else:
                output[i] = data[i]

        return output

    def apply_compressor(self, data: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        """Apply dynamic range compression with attack/release."""
        if not self.compressor_enabled:
            return data

        # Calculate attack/release coefficients
        attack_coeff = np.exp(-1.0 / (self.compressor_attack_ms * self.sample_rate / 1000))
        release_coeff = np.exp(-1.0 / (self.compressor_release_ms * self.sample_rate / 1000))

        threshold_db = self.compressor_threshold_db
        ratio = self.compressor_ratio
        makeup_linear = 10 ** (self.compressor_makeup_db / 20)

        output = np.empty_like(data)
        for i in range(len(data)):
            # Convert to dB (with floor to avoid log(0))
            sample_abs = max(abs(data[i]), 1e-10)
            sample_db = 20 * np.log10(sample_abs)

            # Envelope follower in dB domain
            if sample_db > self.compressor_envelope_db:
                self.compressor_envelope_db = attack_coeff * self.compressor_envelope_db + (1 - attack_coeff) * sample_db
            else:
                self.compressor_envelope_db = release_coeff * self.compressor_envelope_db + (1 - release_coeff) * sample_db

            # Calculate gain reduction
            if self.compressor_envelope_db > threshold_db:
                overshoot_db = self.compressor_envelope_db - threshold_db
                gain_reduction_db = overshoot_db * (1 - 1 / ratio)
            else:
                gain_reduction_db = 0.0

            # Apply gain reduction and makeup
            gain_linear = 10 ** (-gain_reduction_db / 20) * makeup_linear
            output[i] = data[i] * gain_linear

        return output

    def apply_pitch_shift(self, data: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        """Apply pitch shift using multi-pointer delay line with crossfade.

        Multiple read pointers traverse a circular buffer at the shifted rate.
        Each pointer has an independent fade phase that controls its amplitude.
        When a pointer's fade reaches zero, it resets to a new position.
        More pointers = smoother sound with less artifacts.
        """
        if abs(self.pitch_semitones) < 0.1:
            return data

        shift_factor = 2 ** (self.pitch_semitones / 12.0)
        window_size = self.pitch_window_size
        buf_size = self.pitch_buffer_size
        num_voices = self.pitch_num_voices

        # Fade phase increment per sample
        fade_inc = 1.0 / window_size

        output = np.zeros(len(data), dtype=np.float32)

        for i in range(len(data)):
            # Write input to circular buffer
            self.pitch_buffer[self.pitch_write_pos] = data[i]

            # Process all voices
            mixed_sample = 0.0
            total_weight = 0.0

            for v in range(num_voices):
                # Read with linear interpolation
                idx = int(self.pitch_read_pos[v]) % buf_size
                frac = self.pitch_read_pos[v] - int(self.pitch_read_pos[v])
                sample = (self.pitch_buffer[idx] * (1 - frac) +
                         self.pitch_buffer[(idx + 1) % buf_size] * frac)

                # Hann window for crossfade
                fade = 0.5 * (1.0 - np.cos(2.0 * np.pi * self.pitch_fade_pos[v]))

                mixed_sample += sample * fade
                total_weight += fade

                # Advance read position at shifted rate
                self.pitch_read_pos[v] += shift_factor

                # Wrap read position
                if self.pitch_read_pos[v] >= buf_size:
                    self.pitch_read_pos[v] -= buf_size
                elif self.pitch_read_pos[v] < 0:
                    self.pitch_read_pos[v] += buf_size

                # Advance fade position
                self.pitch_fade_pos[v] += fade_inc

                # Reset when fade cycle completes
                if self.pitch_fade_pos[v] >= 1.0:
                    self.pitch_fade_pos[v] -= 1.0
                    self.pitch_read_pos[v] = float((self.pitch_write_pos - buf_size // 2) % buf_size)

            # Output mixed sample
            if total_weight > 0.001:
                output[i] = mixed_sample / total_weight
            else:
                output[i] = 0.0

            # Advance write position
            self.pitch_write_pos = (self.pitch_write_pos + 1) % buf_size

        return output

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

    def make_shelf_filter(self, freq: float, gain_db: float, filter_type: str = "low") -> tuple[npt.NDArray[np.floating], npt.NDArray[np.floating]]:
        """Create a shelf filter using biquad coefficients.

        Based on Robert Bristow-Johnson's Audio EQ Cookbook.
        filter_type: 'low' for low shelf, 'high' for high shelf
        """
        A = 10 ** (gain_db / 40)
        w0 = 2 * np.pi * freq / self.sample_rate
        cos_w0 = np.cos(w0)
        sin_w0 = np.sin(w0)
        alpha = sin_w0 / 2 * np.sqrt((A + 1/A) * (1/0.7 - 1) + 2)

        if filter_type == "low":
            b0 = A * ((A + 1) - (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha)
            b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
            b2 = A * ((A + 1) - (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha)
            a0 = (A + 1) + (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha
            a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
            a2 = (A + 1) + (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha
        else:  # high shelf
            b0 = A * ((A + 1) + (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha)
            b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
            b2 = A * ((A + 1) + (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha)
            a0 = (A + 1) - (A - 1) * cos_w0 + 2 * np.sqrt(A) * alpha
            a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
            a2 = (A + 1) - (A - 1) * cos_w0 - 2 * np.sqrt(A) * alpha

        b = np.array([b0/a0, b1/a0, b2/a0])
        a = np.array([1, a1/a0, a2/a0])
        return b, a

    def coefficients(self, name: str, kind: str, *params: float) -> tuple[npt.NDArray[np.floating], npt.NDArray[np.floating]]:
        """Coefficients for the filter called `name`, designed again only when `params` change.

        kind: 'highpass', 'lowpass' or 'bandpass' (Butterworth, frequencies as a fraction
        of Nyquist), or 'lowshelf' or 'highshelf' (frequency in Hz, gain in dB).
        """
        key = (kind, self.sample_rate, *params)
        cached = self._coefficients.get(name)
        if cached is not None and cached[0] == key:
            return cached[1], cached[2]

        if kind == "lowshelf":
            b, a = self.make_shelf_filter(params[0], params[1], "low")
        elif kind == "highshelf":
            b, a = self.make_shelf_filter(params[0], params[1], "high")
        elif kind == "bandpass":
            b, a = signal.butter(2, list(params), btype="band")  # type: ignore[attr-defined]
        else:
            b, a = signal.butter(2, params[0], btype=kind)  # type: ignore[attr-defined]

        self._coefficients[name] = (key, b, a)
        return b, a

    def apply_filter_with_state(self, b: npt.NDArray[np.floating], a: npt.NDArray[np.floating], data: npt.NDArray[np.float32], filter_key: str) -> npt.NDArray[np.float32]:
        """Apply filter while preserving state between chunks."""
        if filter_key not in self.filter_states:
            self.filter_states[filter_key] = signal.lfilter_zi(b, a) * data[0]
        data, self.filter_states[filter_key] = signal.lfilter(b, a, data, zi=self.filter_states[filter_key])
        return data

    def process(self, data: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        """Run one buffer of samples in [-1, 1] through the chain."""
        # Expander/Gate (smooth envelope-based)
        data = self.apply_expander(data)

        # High-pass filter (remove low frequencies)
        if self.high_pass_enabled and self.low_cut > 20:
            nyquist = self.sample_rate / 2
            low = self.low_cut / nyquist
            if low < 1.0:
                b, a = self.coefficients("highpass", "highpass", low)
                data = self.apply_filter_with_state(b, a, data, "highpass")
        elif "highpass" in self.filter_states:
            del self.filter_states["highpass"]

        # Low-pass filter (remove high frequencies)
        if self.low_pass_enabled and self.high_cut < (self.sample_rate / 2 - 100):
            nyquist = self.sample_rate / 2
            high = self.high_cut / nyquist
            if high < 1.0:
                b, a = self.coefficients("lowpass", "lowpass", high)
                data = self.apply_filter_with_state(b, a, data, "lowpass")
        elif "lowpass" in self.filter_states:
            del self.filter_states["lowpass"]

        # Bass shelf filter
        if abs(self.bass_gain) > 0.5:
            b, a = self.coefficients("bass", "lowshelf", self.bass_freq, self.bass_gain)
            data = self.apply_filter_with_state(b, a, data, "bass")
        elif "bass" in self.filter_states:
            del self.filter_states["bass"]

        # Treble shelf filter
        if abs(self.treble_gain) > 0.5:
            b, a = self.coefficients("treble", "highshelf", self.treble_freq, self.treble_gain)
            data = self.apply_filter_with_state(b, a, data, "treble")
        elif "treble" in self.filter_states:
            del self.filter_states["treble"]

        # De-esser (before compressor)
        data = self.apply_deesser(data)

        # Compressor
        data = self.apply_compressor(data)

        # Apply pitch shift
        if abs(self.pitch_semitones) >= 0.1:
            data = self.apply_pitch_shift(data)

        # Apply delay
        if self.delay_ms > 0:
            data = self.apply_delay(data)

        # Apply gain (smoothed to prevent clicks)
        data = self.apply_gain(data)

        # Soft clipping using tanh for smoother limiting
        return np.tanh(data)
