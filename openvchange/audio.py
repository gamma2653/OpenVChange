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
        self.gain = 1.0
        self.low_cut = 80
        self.high_cut = 16000
        self.noise_gate_threshold = 0.01
        self.noise_gate_enabled = False
        self.low_pass_enabled = False
        self.high_pass_enabled = False

        # Bass and treble (in dB, 0 = no change)
        self.bass_gain = 0.0
        self.treble_gain = 0.0
        self.bass_freq = 250
        self.treble_freq = 4000

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
        self.gain = 10 ** (gain_db / 20)

    def set_low_cut(self, freq):
        self.low_cut = freq

    def set_high_cut(self, freq):
        self.high_cut = freq

    def set_noise_gate_threshold(self, threshold):
        self.noise_gate_threshold = threshold / 100.0

    def set_bass(self, gain_db):
        self.bass_gain = gain_db

    def set_treble(self, gain_db):
        self.treble_gain = gain_db

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

        # Noise gate
        if self.noise_gate_enabled:
            if rms < self.noise_gate_threshold:
                data = data * 0.0

        # High-pass filter (remove low frequencies)
        if self.high_pass_enabled and self.low_cut > 20:
            nyquist = self.sample_rate / 2
            low = self.low_cut / nyquist
            if low < 1.0:
                b, a = signal.butter(2, low, btype="high")
                data = self.apply_filter_with_state(b, a, data, "highpass")
        elif "highpass" in self.filter_states:
            del self.filter_states["highpass"]

        # Low-pass filter (remove high frequencies)
        if self.low_pass_enabled and self.high_cut < (self.sample_rate / 2 - 100):
            nyquist = self.sample_rate / 2
            high = self.high_cut / nyquist
            if high < 1.0:
                b, a = signal.butter(2, high, btype="low")
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

        # Apply gain
        data = data * self.gain

        # Clip to prevent distortion
        data = np.clip(data, -1.0, 1.0)

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
