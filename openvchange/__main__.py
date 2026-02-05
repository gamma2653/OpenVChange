"""Main entry point for OpenVChange audio routing application."""

import json
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
    QTabWidget,
    QSpinBox,
    QFileDialog,
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

        # Tab widget
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # ---- Main tab ----
        main_tab = QWidget()
        main_layout = QVBoxLayout(main_tab)

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
        main_layout.addWidget(device_group)

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

        # Delay control
        delay_layout = QHBoxLayout()
        delay_layout.addWidget(QLabel("Delay:"))
        self.delay_slider = QSlider(Qt.Horizontal)
        self.delay_slider.setRange(0, 10000)
        self.delay_slider.setValue(0)
        self.delay_slider.valueChanged.connect(self.on_delay_changed)
        delay_layout.addWidget(self.delay_slider)
        self.delay_label = QLabel("0 ms")
        self.delay_label.setMinimumWidth(70)
        delay_layout.addWidget(self.delay_label)
        filters_layout.addLayout(delay_layout)

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
        main_layout.addWidget(filters_group)

        # Level meter
        meter_group = QGroupBox("Input Level")
        meter_layout = QHBoxLayout()
        self.level_bar = QSlider(Qt.Horizontal)
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setEnabled(False)
        meter_layout.addWidget(self.level_bar)
        meter_group.setLayout(meter_layout)
        main_layout.addWidget(meter_group)

        self.tab_widget.addTab(main_tab, "Main")

        # ---- Advanced Settings tab ----
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)

        advanced_group = QGroupBox("Advanced Settings")
        advanced_form = QFormLayout()

        self.buffer_size_combo = QComboBox()
        for size in [128, 256, 512, 1024, 2048, 4096]:
            self.buffer_size_combo.addItem(str(size), size)
        self.buffer_size_combo.setCurrentIndex(3)  # Default: 1024
        self.buffer_size_combo.currentIndexChanged.connect(self.on_buffer_size_changed)
        advanced_form.addRow("Buffer Size:", self.buffer_size_combo)

        self.pitch_voices_spin = QSpinBox()
        self.pitch_voices_spin.setRange(1, 8)
        self.pitch_voices_spin.setValue(4)
        self.pitch_voices_spin.valueChanged.connect(self.on_pitch_voices_changed)
        advanced_form.addRow("Pitch Voices:", self.pitch_voices_spin)

        advanced_group.setLayout(advanced_form)
        advanced_layout.addWidget(advanced_group)

        note_label = QLabel("Note: Changes to these settings take effect when the audio stream is next started.")
        note_label.setWordWrap(True)
        advanced_layout.addWidget(note_label)

        advanced_layout.addStretch()

        self.tab_widget.addTab(advanced_tab, "Advanced Settings")

        # Control buttons (outside tabs)
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

        # Preset buttons
        preset_layout = QHBoxLayout()
        self.save_preset_button = QPushButton("Save Preset")
        self.save_preset_button.clicked.connect(self.on_save_preset)
        preset_layout.addWidget(self.save_preset_button)

        self.load_preset_button = QPushButton("Load Preset")
        self.load_preset_button.clicked.connect(self.on_load_preset)
        preset_layout.addWidget(self.load_preset_button)

        layout.addLayout(preset_layout)

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

    def on_delay_changed(self, value):
        self.delay_label.setText(f"{value} ms")
        self.audio_processor.set_delay(value)

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

    def on_buffer_size_changed(self, index):
        """Handle buffer size combo box change."""
        size = self.buffer_size_combo.currentData()
        if size is not None:
            self.audio_processor.set_chunk_size(size)

    def on_pitch_voices_changed(self, value):
        """Handle pitch voices spin box change."""
        self.audio_processor.set_pitch_num_voices(value)

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
        self.delay_slider.setValue(0)
        self.hp_slider.setValue(80)
        self.lp_slider.setValue(16000)
        self.ng_slider.setValue(1)

        # Reset advanced settings
        self.buffer_size_combo.setCurrentIndex(3)  # 1024
        self.pitch_voices_spin.setValue(4)

    def get_preset(self):
        """Collect current settings into a dict."""
        return {
            "gain": self.gain_slider.value(),
            "bass": self.bass_slider.value(),
            "treble": self.treble_slider.value(),
            "pitch": self.pitch_slider.value(),
            "delay": self.delay_slider.value(),
            "high_pass_enabled": self.hp_checkbox.isChecked(),
            "high_pass_freq": self.hp_slider.value(),
            "low_pass_enabled": self.lp_checkbox.isChecked(),
            "low_pass_freq": self.lp_slider.value(),
            "noise_gate_enabled": self.ng_checkbox.isChecked(),
            "noise_gate_threshold": self.ng_slider.value(),
            "buffer_size": self.buffer_size_combo.currentData(),
            "pitch_voices": self.pitch_voices_spin.value(),
        }

    def apply_preset(self, preset):
        """Apply a preset dict to the UI controls."""
        if "high_pass_enabled" in preset:
            self.hp_checkbox.setChecked(preset["high_pass_enabled"])
        if "low_pass_enabled" in preset:
            self.lp_checkbox.setChecked(preset["low_pass_enabled"])
        if "noise_gate_enabled" in preset:
            self.ng_checkbox.setChecked(preset["noise_gate_enabled"])

        if "gain" in preset:
            self.gain_slider.setValue(preset["gain"])
        if "bass" in preset:
            self.bass_slider.setValue(preset["bass"])
        if "treble" in preset:
            self.treble_slider.setValue(preset["treble"])
        if "pitch" in preset:
            self.pitch_slider.setValue(preset["pitch"])
        if "delay" in preset:
            self.delay_slider.setValue(preset["delay"])
        if "high_pass_freq" in preset:
            self.hp_slider.setValue(preset["high_pass_freq"])
        if "low_pass_freq" in preset:
            self.lp_slider.setValue(preset["low_pass_freq"])
        if "noise_gate_threshold" in preset:
            self.ng_slider.setValue(preset["noise_gate_threshold"])

        if "buffer_size" in preset:
            index = self.buffer_size_combo.findData(preset["buffer_size"])
            if index >= 0:
                self.buffer_size_combo.setCurrentIndex(index)
        if "pitch_voices" in preset:
            self.pitch_voices_spin.setValue(preset["pitch_voices"])

    def on_save_preset(self):
        """Save current settings to a JSON file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Preset", "", "JSON Files (*.json)"
        )
        if path:
            with open(path, "w") as f:
                json.dump(self.get_preset(), f, indent=2)
            self.status_label.setText(f"Status: Preset saved")

    def on_load_preset(self):
        """Load settings from a JSON file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Preset", "", "JSON Files (*.json)"
        )
        if path:
            try:
                with open(path, "r") as f:
                    preset = json.load(f)
                self.apply_preset(preset)
                self.status_label.setText(f"Status: Preset loaded")
            except (json.JSONDecodeError, OSError) as e:
                self.status_label.setText(f"Status: Failed to load preset")

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
        self.buffer_size_combo.setEnabled(False)
        self.pitch_voices_spin.setEnabled(False)
        self.status_label.setText("Status: Running")

    def on_stop(self):
        """Stop audio processing."""
        self.audio_processor.stop()

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.input_combo.setEnabled(True)
        self.output_combo.setEnabled(True)
        self.buffer_size_combo.setEnabled(True)
        self.pitch_voices_spin.setEnabled(True)
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
