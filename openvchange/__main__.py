"""Main entry point for OpenVChange audio routing application."""

import sys

import pyaudio
from PySide6.QtCore import Qt
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

from openvchange.audio import AudioProcessor


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenVChange - Virtual Audio Router")
        self.setMinimumSize(500, 520)

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
        self.show_all_devices_checkbox = QCheckBox("Show all devices")
        self.show_all_devices_checkbox.toggled.connect(self.on_show_all_devices_toggled)
        device_layout.addRow("Input Device:", self.input_combo)
        device_layout.addRow("Output Device:", self.output_combo)
        device_layout.addRow("", self.show_all_devices_checkbox)

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
        self.bass_slider.setRange(-128, 128)
        self.bass_slider.setValue(0)
        self.bass_slider.valueChanged.connect(self.on_bass_changed)
        bass_layout.addWidget(self.bass_slider)
        self.bass_label = QLabel("0 dB")
        self.bass_label.setMinimumWidth(70)
        bass_layout.addWidget(self.bass_label)
        filters_layout.addLayout(bass_layout)

        # Treble control
        treble_layout = QHBoxLayout()
        treble_layout.addWidget(QLabel("Treble:"))
        self.treble_slider = QSlider(Qt.Horizontal)
        self.treble_slider.setRange(-128, 128)
        self.treble_slider.setValue(0)
        self.treble_slider.valueChanged.connect(self.on_treble_changed)
        treble_layout.addWidget(self.treble_slider)
        self.treble_label = QLabel("0 dB")
        self.treble_label.setMinimumWidth(70)
        treble_layout.addWidget(self.treble_label)
        filters_layout.addLayout(treble_layout)

        # Pitch control
        pitch_layout = QHBoxLayout()
        pitch_layout.addWidget(QLabel("Pitch:"))
        self.pitch_slider = QSlider(Qt.Horizontal)
        self.pitch_slider.setRange(-120, 120)  # -12 to +12 semitones (x10 for precision)
        self.pitch_slider.setValue(0)
        self.pitch_slider.valueChanged.connect(self.on_pitch_changed)
        pitch_layout.addWidget(self.pitch_slider)
        self.pitch_label = QLabel("0 st")
        self.pitch_label.setMinimumWidth(70)
        pitch_layout.addWidget(self.pitch_label)
        filters_layout.addLayout(pitch_layout)

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

        self.reset_button = QPushButton("Reset to Defaults")
        self.reset_button.clicked.connect(self.on_reset_defaults)
        button_layout.addWidget(self.reset_button)

        layout.addLayout(button_layout)

        # Status label
        self.status_label = QLabel("Status: Stopped")
        layout.addWidget(self.status_label)

    def populate_devices(self):
        """Populate device combo boxes with available audio devices."""
        self.input_combo.clear()
        self.output_combo.clear()

        pa = pyaudio.PyAudio()
        show_all = self.show_all_devices_checkbox.isChecked()

        # Find WASAPI host API index (preferred for Windows)
        wasapi_index = None
        if not show_all:
            for i in range(pa.get_host_api_count()):
                host_info = pa.get_host_api_info_by_index(i)
                if "WASAPI" in host_info["name"]:
                    wasapi_index = i
                    break

        for i in range(pa.get_device_count()):
            device_info = pa.get_device_info_by_index(i)

            # Only show WASAPI devices if available and not showing all
            if wasapi_index is not None and device_info["hostApi"] != wasapi_index:
                continue

            name = device_info["name"]

            if device_info["maxInputChannels"] > 0:
                self.input_combo.addItem(name, i)

            if device_info["maxOutputChannels"] > 0:
                self.output_combo.addItem(name, i)

        pa.terminate()

    def on_show_all_devices_toggled(self, checked):
        """Handle show all devices checkbox toggle."""
        self.populate_devices()

    def on_gain_changed(self, value):
        self.gain_label.setText(f"{value} dB")
        self.audio_processor.set_gain(value)

    def on_bass_changed(self, value):
        self.bass_label.setText(f"{value} dB")
        self.audio_processor.set_bass(value)

    def on_treble_changed(self, value):
        self.treble_label.setText(f"{value} dB")
        self.audio_processor.set_treble(value)

    def on_pitch_changed(self, value):
        semitones = value / 10.0  # Convert from slider units to semitones
        self.pitch_label.setText(f"{semitones:.1f} st")
        self.audio_processor.set_pitch(semitones)

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

    def on_reset_defaults(self):
        """Reset all filter settings to their default values."""
        # Disable filters first
        self.hp_checkbox.setChecked(False)
        self.lp_checkbox.setChecked(False)
        self.ng_checkbox.setChecked(False)

        # Reset slider values
        self.gain_slider.setValue(0)
        self.bass_slider.setValue(0)
        self.treble_slider.setValue(0)
        self.pitch_slider.setValue(0)
        self.hp_slider.setValue(80)
        self.lp_slider.setValue(16000)
        self.ng_slider.setValue(1)

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
