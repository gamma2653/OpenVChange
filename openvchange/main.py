"""Main entry point for OpenVChange audio routing application."""

import sys
import numpy as np
import pyaudio
from scipy import signal
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QComboBox,
    QLabel,
    QSlider,
    QPushButton,
    QCheckBox,
    QFormLayout,
)


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


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenVChange - Virtual Audio Router")
        self.setMinimumSize(500, 480)

        self.audio_processor = AudioProcessor()
        self.audio_processor.level_changed.connect(self.update_level_meter)

        self.init_ui()
        self.populate_devices()

    def init_ui(self):
        """Initialize the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Device selection group
        device_group = QGroupBox("Audio Devices")
        device_layout = QFormLayout()

        self.input_combo = QComboBox()
        self.output_combo = QComboBox()
        device_layout.addRow("Input Device:", self.input_combo)
        device_layout.addRow("Output Device:", self.output_combo)

        device_group.setLayout(device_layout)
        layout.addWidget(device_group)

        # Filters group
        filters_group = QGroupBox("Filters")
        filters_layout = QVBoxLayout()

        # Gain control
        gain_layout = QHBoxLayout()
        gain_layout.addWidget(QLabel("Gain:"))
        self.gain_slider = QSlider(Qt.Horizontal)
        self.gain_slider.setRange(-20, 20)
        self.gain_slider.setValue(0)
        self.gain_slider.valueChanged.connect(self.on_gain_changed)
        gain_layout.addWidget(self.gain_slider)
        self.gain_label = QLabel("0 dB")
        self.gain_label.setMinimumWidth(50)
        gain_layout.addWidget(self.gain_label)
        filters_layout.addLayout(gain_layout)

        # Bass control
        bass_layout = QHBoxLayout()
        bass_layout.addWidget(QLabel("Bass:"))
        self.bass_slider = QSlider(Qt.Horizontal)
        self.bass_slider.setRange(-12, 12)
        self.bass_slider.setValue(0)
        self.bass_slider.valueChanged.connect(self.on_bass_changed)
        bass_layout.addWidget(self.bass_slider)
        self.bass_label = QLabel("0 dB")
        self.bass_label.setMinimumWidth(50)
        bass_layout.addWidget(self.bass_label)
        filters_layout.addLayout(bass_layout)

        # Treble control
        treble_layout = QHBoxLayout()
        treble_layout.addWidget(QLabel("Treble:"))
        self.treble_slider = QSlider(Qt.Horizontal)
        self.treble_slider.setRange(-12, 12)
        self.treble_slider.setValue(0)
        self.treble_slider.valueChanged.connect(self.on_treble_changed)
        treble_layout.addWidget(self.treble_slider)
        self.treble_label = QLabel("0 dB")
        self.treble_label.setMinimumWidth(50)
        treble_layout.addWidget(self.treble_label)
        filters_layout.addLayout(treble_layout)

        # High-pass filter
        hp_layout = QHBoxLayout()
        self.hp_checkbox = QCheckBox("High-Pass Filter:")
        self.hp_checkbox.toggled.connect(self.on_hp_toggled)
        hp_layout.addWidget(self.hp_checkbox)
        self.hp_slider = QSlider(Qt.Horizontal)
        self.hp_slider.setRange(20, 500)
        self.hp_slider.setValue(80)
        self.hp_slider.setEnabled(False)
        self.hp_slider.valueChanged.connect(self.on_hp_changed)
        hp_layout.addWidget(self.hp_slider)
        self.hp_label = QLabel("80 Hz")
        self.hp_label.setMinimumWidth(60)
        hp_layout.addWidget(self.hp_label)
        filters_layout.addLayout(hp_layout)

        # Low-pass filter
        lp_layout = QHBoxLayout()
        self.lp_checkbox = QCheckBox("Low-Pass Filter:")
        self.lp_checkbox.toggled.connect(self.on_lp_toggled)
        lp_layout.addWidget(self.lp_checkbox)
        self.lp_slider = QSlider(Qt.Horizontal)
        self.lp_slider.setRange(1000, 20000)
        self.lp_slider.setValue(16000)
        self.lp_slider.setEnabled(False)
        self.lp_slider.valueChanged.connect(self.on_lp_changed)
        lp_layout.addWidget(self.lp_slider)
        self.lp_label = QLabel("16000 Hz")
        self.lp_label.setMinimumWidth(60)
        lp_layout.addWidget(self.lp_label)
        filters_layout.addLayout(lp_layout)

        # Noise gate
        ng_layout = QHBoxLayout()
        self.ng_checkbox = QCheckBox("Noise Gate:")
        self.ng_checkbox.toggled.connect(self.on_ng_toggled)
        ng_layout.addWidget(self.ng_checkbox)
        self.ng_slider = QSlider(Qt.Horizontal)
        self.ng_slider.setRange(0, 20)
        self.ng_slider.setValue(1)
        self.ng_slider.setEnabled(False)
        self.ng_slider.valueChanged.connect(self.on_ng_changed)
        ng_layout.addWidget(self.ng_slider)
        self.ng_label = QLabel("1%")
        self.ng_label.setMinimumWidth(60)
        ng_layout.addWidget(self.ng_label)
        filters_layout.addLayout(ng_layout)

        filters_group.setLayout(filters_layout)
        layout.addWidget(filters_group)

        # Level meter
        meter_group = QGroupBox("Input Level")
        meter_layout = QHBoxLayout()
        self.level_bar = QSlider(Qt.Horizontal)
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setEnabled(False)
        meter_layout.addWidget(self.level_bar)
        meter_group.setLayout(meter_layout)
        layout.addWidget(meter_group)

        # Control buttons
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self.on_start)
        button_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("Stop")
        self.stop_button.clicked.connect(self.on_stop)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.stop_button)

        layout.addLayout(button_layout)

        # Status label
        self.status_label = QLabel("Status: Stopped")
        layout.addWidget(self.status_label)

    def populate_devices(self):
        """Populate device combo boxes with available audio devices."""
        pa = pyaudio.PyAudio()

        for i in range(pa.get_device_count()):
            device_info = pa.get_device_info_by_index(i)
            name = device_info["name"]

            if device_info["maxInputChannels"] > 0:
                self.input_combo.addItem(name, i)

            if device_info["maxOutputChannels"] > 0:
                self.output_combo.addItem(name, i)

        pa.terminate()

    def on_gain_changed(self, value):
        self.gain_label.setText(f"{value} dB")
        self.audio_processor.set_gain(value)

    def on_bass_changed(self, value):
        self.bass_label.setText(f"{value} dB")
        self.audio_processor.set_bass(value)

    def on_treble_changed(self, value):
        self.treble_label.setText(f"{value} dB")
        self.audio_processor.set_treble(value)

    def on_hp_toggled(self, checked):
        self.hp_slider.setEnabled(checked)
        self.audio_processor.high_pass_enabled = checked

    def on_hp_changed(self, value):
        self.hp_label.setText(f"{value} Hz")
        self.audio_processor.set_low_cut(value)

    def on_lp_toggled(self, checked):
        self.lp_slider.setEnabled(checked)
        self.audio_processor.low_pass_enabled = checked

    def on_lp_changed(self, value):
        self.lp_label.setText(f"{value} Hz")
        self.audio_processor.set_high_cut(value)

    def on_ng_toggled(self, checked):
        self.ng_slider.setEnabled(checked)
        self.audio_processor.noise_gate_enabled = checked

    def on_ng_changed(self, value):
        self.ng_label.setText(f"{value}%")
        self.audio_processor.set_noise_gate_threshold(value)

    def update_level_meter(self, level):
        """Update the input level meter."""
        db_level = int(min(100, max(0, (level * 100) * 3)))
        self.level_bar.setValue(db_level)

    def on_start(self):
        """Start audio processing."""
        input_device = self.input_combo.currentData()
        output_device = self.output_combo.currentData()

        if input_device is None or output_device is None:
            self.status_label.setText("Status: Please select both devices")
            return

        self.audio_processor.set_input_device(input_device)
        self.audio_processor.set_output_device(output_device)
        self.audio_processor.start()

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.input_combo.setEnabled(False)
        self.output_combo.setEnabled(False)
        self.status_label.setText("Status: Running")

    def on_stop(self):
        """Stop audio processing."""
        self.audio_processor.stop()

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.input_combo.setEnabled(True)
        self.output_combo.setEnabled(True)
        self.status_label.setText("Status: Stopped")
        self.level_bar.setValue(0)

    def closeEvent(self, event):
        """Handle window close event."""
        self.audio_processor.stop()
        self.audio_processor.pa.terminate()
        event.accept()


def main():
    """Application entry point."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
