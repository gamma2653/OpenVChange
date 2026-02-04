"""Audio processing module for OpenVChange."""

import numpy as np
import pyaudio
from scipy import signal
from PySide6.QtCore import QThread, Signal


class AudioProcessor(QThread):
    """Thread for processing audio with filters."""

    level_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.input_device = None
        self.output_device = None
        self.sample_rate = 44100
        self.chunk_size = 1024
        self.channels = 1

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
                data = signal.lfilter(b, a, data)

        # Low-pass filter (remove high frequencies)
        if self.low_pass_enabled and self.high_cut < (self.sample_rate / 2 - 100):
            nyquist = self.sample_rate / 2
            high = self.high_cut / nyquist
            if high < 1.0:
                b, a = signal.butter(2, high, btype="low")
                data = signal.lfilter(b, a, data)

        # Bass shelf filter
        if abs(self.bass_gain) > 0.5:
            b, a = self.make_shelf_filter(self.bass_freq, self.bass_gain, "low")
            data = signal.lfilter(b, a, data)

        # Treble shelf filter
        if abs(self.treble_gain) > 0.5:
            b, a = self.make_shelf_filter(self.treble_freq, self.treble_gain, "high")
            data = signal.lfilter(b, a, data)

        # Apply gain
        data = data * self.gain

        # Clip to prevent distortion
        data = np.clip(data, -1.0, 1.0)

        # Convert back to int16
        return (data * 32767).astype(np.int16).tobytes()

    def run(self):
        """Main audio processing loop."""
        if self.input_device is None or self.output_device is None:
            return

        try:
            input_stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.input_device,
                frames_per_buffer=self.chunk_size,
            )

            output_stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                output=True,
                output_device_index=self.output_device,
                frames_per_buffer=self.chunk_size,
            )

            self.running = True

            while self.running:
                audio_data = input_stream.read(self.chunk_size, exception_on_overflow=False)
                processed_data = self.apply_filters(audio_data)
                output_stream.write(processed_data)

            input_stream.stop_stream()
            input_stream.close()
            output_stream.stop_stream()
            output_stream.close()

        except Exception as e:
            print(f"Audio error: {e}")

    def stop(self):
        """Stop the audio processing thread."""
        self.running = False
        self.wait()
