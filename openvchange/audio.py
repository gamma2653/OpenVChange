"""Audio processing module for OpenVChange."""

import numpy as np
import pyaudio
from scipy import signal
from PySide6.QtCore import QObject, Signal


class AudioProcessor(QObject):
    """Audio processor using callback-based streaming."""

    level_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.input_device = None
        self.output_device = None
        self.sample_rate = 44100
        self.chunk_size = 1024
        self.channels = 1
        self.stream = None

        # Filter states (preserved between chunks)
        self.filter_states = {}

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

        self.pa = pyaudio.PyAudio()

    def set_input_device(self, device_index):
        self.input_device = device_index

    def set_output_device(self, device_index):
        self.output_device = device_index

    def get_supported_sample_rate(self, device_index, is_input):
        """Find a supported sample rate for the device."""
        common_rates = [48000, 44100, 96000, 32000, 22050, 16000]
        device_info = self.pa.get_device_info_by_index(device_index)

        for rate in common_rates:
            try:
                if is_input:
                    supported = self.pa.is_format_supported(
                        rate,
                        input_device=device_index,
                        input_channels=self.channels,
                        input_format=pyaudio.paInt16,
                    )
                else:
                    supported = self.pa.is_format_supported(
                        rate,
                        output_device=device_index,
                        output_channels=self.channels,
                        output_format=pyaudio.paInt16,
                    )
                if supported:
                    return rate
            except ValueError:
                continue

        # Fallback to device default
        return int(device_info.get("defaultSampleRate", 44100))

    def find_common_sample_rate(self):
        """Find a sample rate supported by both input and output devices."""
        common_rates = [48000, 44100, 96000, 32000, 22050, 16000]

        for rate in common_rates:
            try:
                input_ok = self.pa.is_format_supported(
                    rate,
                    input_device=self.input_device,
                    input_channels=self.channels,
                    input_format=pyaudio.paInt16,
                )
                output_ok = self.pa.is_format_supported(
                    rate,
                    output_device=self.output_device,
                    output_channels=self.channels,
                    output_format=pyaudio.paInt16,
                )
                if input_ok and output_ok:
                    return rate
            except ValueError:
                continue

        # Fallback
        return 44100

    def set_gain(self, gain_db):
        self.gain_target = 10 ** (gain_db / 20)

    def set_low_cut(self, freq):
        self.low_cut = freq

    def set_high_cut(self, freq):
        self.high_cut = freq

    def set_bass(self, gain_db):
        self.bass_gain = gain_db

    def set_treble(self, gain_db):
        self.treble_gain = gain_db

    def set_chunk_size(self, size):
        """Set the audio buffer size (frames per buffer)."""
        self.chunk_size = size

    def set_pitch_num_voices(self, num):
        """Set the number of pitch shift voices and reinitialize arrays."""
        self.pitch_num_voices = num
        self.pitch_read_pos = [0.0] * self.pitch_num_voices
        self.pitch_fade_pos = [i / self.pitch_num_voices for i in range(self.pitch_num_voices)]

    def set_delay(self, ms):
        """Set delay in milliseconds (0 to 10000)."""
        self.delay_ms = ms

    def set_pitch(self, semitones):
        """Set pitch shift in semitones (-12 to +12)."""
        self.pitch_semitones = semitones

    # Expander setters
    def set_expander_threshold(self, percent):
        self.expander_threshold = percent / 100.0

    def set_expander_ratio(self, ratio):
        self.expander_ratio = ratio

    def set_expander_attack(self, ms):
        self.expander_attack_ms = ms

    def set_expander_release(self, ms):
        self.expander_release_ms = ms

    # Compressor setters
    def set_compressor_threshold(self, db):
        self.compressor_threshold_db = db

    def set_compressor_ratio(self, ratio):
        self.compressor_ratio = ratio

    def set_compressor_attack(self, ms):
        self.compressor_attack_ms = ms

    def set_compressor_release(self, ms):
        self.compressor_release_ms = ms

    def set_compressor_makeup(self, db):
        self.compressor_makeup_db = db

    # De-esser setters
    def set_deesser_threshold(self, db):
        self.deesser_threshold_db = db

    def set_deesser_reduction(self, db):
        self.deesser_reduction_db = db

    def apply_expander(self, data, rms):
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

    def apply_deesser(self, data):
        """Apply de-esser using bandpass sidechain detection."""
        if not self.deesser_enabled:
            return data

        # Create bandpass filter for sibilance detection (5-8 kHz)
        nyquist = self.sample_rate / 2
        low_freq = min(5000 / nyquist, 0.99)
        high_freq = min(8000 / nyquist, 0.99)

        if low_freq >= high_freq:
            return data

        b, a = signal.butter(2, [low_freq, high_freq], btype='band')  # type: ignore[attr-defined]
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

    def apply_compressor(self, data):
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

    def apply_pitch_shift(self, data):
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

    def make_shelf_filter(self, freq, gain_db, filter_type="low"):
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

    def apply_filter_with_state(self, b, a, data, filter_key):
        """Apply filter while preserving state between chunks."""
        if filter_key not in self.filter_states:
            self.filter_states[filter_key] = signal.lfilter_zi(b, a) * data[0]
        data, self.filter_states[filter_key] = signal.lfilter(b, a, data, zi=self.filter_states[filter_key])
        return data

    def apply_filters(self, audio_data):
        """Apply enabled filters to audio data."""
        data = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
        data = data / 32768.0  # Normalize to -1.0 to 1.0

        # Calculate input level for meter
        rms = np.sqrt(np.mean(data**2))
        self.level_changed.emit(rms)

        # Expander/Gate (smooth envelope-based)
        data = self.apply_expander(data, rms)

        # High-pass filter (remove low frequencies)
        if self.high_pass_enabled and self.low_cut > 20:
            nyquist = self.sample_rate / 2
            low = self.low_cut / nyquist
            if low < 1.0:
                b, a = signal.butter(2, low, btype="high")  # type: ignore[attr-defined]
                data = self.apply_filter_with_state(b, a, data, "highpass")
        elif "highpass" in self.filter_states:
            del self.filter_states["highpass"]

        # Low-pass filter (remove high frequencies)
        if self.low_pass_enabled and self.high_cut < (self.sample_rate / 2 - 100):
            nyquist = self.sample_rate / 2
            high = self.high_cut / nyquist
            if high < 1.0:
                b, a = signal.butter(2, high, btype="low")  # type: ignore[attr-defined]
                data = self.apply_filter_with_state(b, a, data, "lowpass")
        elif "lowpass" in self.filter_states:
            del self.filter_states["lowpass"]

        # Bass shelf filter
        if abs(self.bass_gain) > 0.5:
            b, a = self.make_shelf_filter(self.bass_freq, self.bass_gain, "low")
            data = self.apply_filter_with_state(b, a, data, "bass")
        elif "bass" in self.filter_states:
            del self.filter_states["bass"]

        # Treble shelf filter
        if abs(self.treble_gain) > 0.5:
            b, a = self.make_shelf_filter(self.treble_freq, self.treble_gain, "high")
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
            delay_samples = int(self.delay_ms * self.sample_rate / 1000)
            delay_samples = min(delay_samples, self.delay_buffer_size - 1)
            buf = self.delay_buffer
            buf_size = self.delay_buffer_size
            wp = self.delay_write_pos
            n = len(data)

            # Write current chunk into circular buffer and read delayed samples
            output = np.empty(n, dtype=np.float32)
            for i in range(n):
                buf[wp] = data[i]
                read_pos = (wp - delay_samples) % buf_size
                output[i] = buf[read_pos]
                wp = (wp + 1) % buf_size

            self.delay_write_pos = wp
            data = output

        # Apply gain (with per-sample smoothing to prevent clicks)
        smooth_coeff = self.param_smooth_coeff
        output = np.empty_like(data)
        for i in range(len(data)):
            self.gain_smoothed += (self.gain_target - self.gain_smoothed) * (1 - smooth_coeff)
            output[i] = data[i] * self.gain_smoothed
        data = output

        # Soft clipping using tanh for smoother limiting
        data = np.tanh(data)

        # Convert back to int16
        return (data * 32767).astype(np.int16).tobytes()

    def audio_callback(self, in_data, frame_count, time_info, status):
        """Combined callback for full-duplex audio processing."""
        if not self.running or in_data is None:
            return (b'\x00' * (frame_count * self.channels * 2), pyaudio.paContinue)

        try:
            processed = self.apply_filters(in_data)
            return (processed, pyaudio.paContinue)
        except Exception:
            return (in_data, pyaudio.paContinue)

    def start(self):
        """Start audio processing."""
        if self.input_device is None or self.output_device is None:
            return

        try:
            self.sample_rate = self.find_common_sample_rate()
            self.filter_states = {}
            self.delay_buffer = np.zeros(self.delay_buffer_size, dtype=np.float32)
            self.delay_write_pos = 0
            self.pitch_buffer = np.zeros(self.pitch_buffer_size, dtype=np.float32)
            self.pitch_write_pos = self.pitch_buffer_size // 2
            self.pitch_read_pos = [0.0] * self.pitch_num_voices
            self.pitch_fade_pos = [i / self.pitch_num_voices for i in range(self.pitch_num_voices)]

            # Reset dynamics processor states
            self.expander_envelope = 1.0
            self.compressor_envelope_db = -60.0
            self.deesser_envelope = 0.0
            self.gain_smoothed = self.gain_target

            # Use full-duplex stream for synchronized I/O
            self.stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                output=True,
                input_device_index=self.input_device,
                output_device_index=self.output_device,
                frames_per_buffer=self.chunk_size,
                stream_callback=self.audio_callback,
            )

            self.running = True
            self.stream.start_stream()

        except Exception as e:
            print(f"Audio error: {e}")
            self.running = False

    def stop(self):
        """Stop audio processing."""
        self.running = False

        if hasattr(self, 'stream') and self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
