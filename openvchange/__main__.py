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
        self.setMinimumSize(500, 580)

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

        # Master effects toggle
        self.effects_checkbox = QCheckBox("Enable Effects")
        self.effects_checkbox.setChecked(True)
        self.effects_checkbox.toggled.connect(self.on_effects_toggled)
        filters_layout.addWidget(self.effects_checkbox)

        # Gain control
        gain_layout = QHBoxLayout()
        gain_layout.addWidget(QLabel("Gain:"))
        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(-100, 100)
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
        self.bass_slider = QSlider(Qt.Orientation.Horizontal)
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
        self.treble_slider = QSlider(Qt.Orientation.Horizontal)
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
        self.pitch_slider = QSlider(Qt.Orientation.Horizontal)
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
        self.delay_slider = QSlider(Qt.Orientation.Horizontal)
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
        self.hp_slider = QSlider(Qt.Orientation.Horizontal)
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
        self.lp_slider = QSlider(Qt.Orientation.Horizontal)
        self.lp_slider.setRange(1000, 20000)
        self.lp_slider.setValue(16000)
        self.lp_slider.setEnabled(False)
        self.lp_slider.valueChanged.connect(self.on_lp_changed)
        lp_layout.addWidget(self.lp_slider)
        self.lp_label = QLabel("16000 Hz")
        self.lp_label.setMinimumWidth(60)
        lp_layout.addWidget(self.lp_label)
        filters_layout.addLayout(lp_layout)

        filters_group.setLayout(filters_layout)
        main_layout.addWidget(filters_group)

        # Level meter
        meter_group = QGroupBox("Input Level")
        meter_layout = QHBoxLayout()
        self.level_bar = QSlider(Qt.Orientation.Horizontal)
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setEnabled(False)
        meter_layout.addWidget(self.level_bar)
        meter_group.setLayout(meter_layout)
        main_layout.addWidget(meter_group)

        self.tab_widget.addTab(main_tab, "Main")

        # ---- Dynamics tab ----
        dynamics_tab = QWidget()
        dynamics_layout = QVBoxLayout(dynamics_tab)

        # Expander/Gate group
        expander_group = QGroupBox("Expander/Gate")
        expander_form = QFormLayout()

        self.expander_checkbox = QCheckBox("Enable")
        self.expander_checkbox.toggled.connect(self.on_expander_toggled)
        expander_form.addRow("", self.expander_checkbox)

        self.expander_threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.expander_threshold_slider.setRange(0, 20)
        self.expander_threshold_slider.setValue(1)
        self.expander_threshold_slider.setEnabled(False)
        self.expander_threshold_slider.valueChanged.connect(self.on_expander_threshold_changed)
        self.expander_threshold_label = QLabel("1%")
        threshold_layout = QHBoxLayout()
        threshold_layout.addWidget(self.expander_threshold_slider)
        threshold_layout.addWidget(self.expander_threshold_label)
        expander_form.addRow("Threshold:", threshold_layout)

        self.expander_ratio_slider = QSlider(Qt.Orientation.Horizontal)
        self.expander_ratio_slider.setRange(15, 100)  # 1.5:1 to 10:1 (x10)
        self.expander_ratio_slider.setValue(20)
        self.expander_ratio_slider.setEnabled(False)
        self.expander_ratio_slider.valueChanged.connect(self.on_expander_ratio_changed)
        self.expander_ratio_label = QLabel("2.0:1")
        ratio_layout = QHBoxLayout()
        ratio_layout.addWidget(self.expander_ratio_slider)
        ratio_layout.addWidget(self.expander_ratio_label)
        expander_form.addRow("Ratio:", ratio_layout)

        self.expander_attack_slider = QSlider(Qt.Orientation.Horizontal)
        self.expander_attack_slider.setRange(1, 50)
        self.expander_attack_slider.setValue(5)
        self.expander_attack_slider.setEnabled(False)
        self.expander_attack_slider.valueChanged.connect(self.on_expander_attack_changed)
        self.expander_attack_label = QLabel("5 ms")
        attack_layout = QHBoxLayout()
        attack_layout.addWidget(self.expander_attack_slider)
        attack_layout.addWidget(self.expander_attack_label)
        expander_form.addRow("Attack:", attack_layout)

        self.expander_release_slider = QSlider(Qt.Orientation.Horizontal)
        self.expander_release_slider.setRange(20, 500)
        self.expander_release_slider.setValue(100)
        self.expander_release_slider.setEnabled(False)
        self.expander_release_slider.valueChanged.connect(self.on_expander_release_changed)
        self.expander_release_label = QLabel("100 ms")
        release_layout = QHBoxLayout()
        release_layout.addWidget(self.expander_release_slider)
        release_layout.addWidget(self.expander_release_label)
        expander_form.addRow("Release:", release_layout)

        expander_group.setLayout(expander_form)
        dynamics_layout.addWidget(expander_group)

        # Compressor group
        compressor_group = QGroupBox("Compressor")
        compressor_form = QFormLayout()

        self.compressor_checkbox = QCheckBox("Enable")
        self.compressor_checkbox.toggled.connect(self.on_compressor_toggled)
        compressor_form.addRow("", self.compressor_checkbox)

        self.compressor_threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.compressor_threshold_slider.setRange(-40, 0)
        self.compressor_threshold_slider.setValue(-10)
        self.compressor_threshold_slider.setEnabled(False)
        self.compressor_threshold_slider.valueChanged.connect(self.on_compressor_threshold_changed)
        self.compressor_threshold_label = QLabel("-10 dB")
        comp_thresh_layout = QHBoxLayout()
        comp_thresh_layout.addWidget(self.compressor_threshold_slider)
        comp_thresh_layout.addWidget(self.compressor_threshold_label)
        compressor_form.addRow("Threshold:", comp_thresh_layout)

        self.compressor_ratio_slider = QSlider(Qt.Orientation.Horizontal)
        self.compressor_ratio_slider.setRange(10, 200)  # 1:1 to 20:1 (x10)
        self.compressor_ratio_slider.setValue(40)
        self.compressor_ratio_slider.setEnabled(False)
        self.compressor_ratio_slider.valueChanged.connect(self.on_compressor_ratio_changed)
        self.compressor_ratio_label = QLabel("4.0:1")
        comp_ratio_layout = QHBoxLayout()
        comp_ratio_layout.addWidget(self.compressor_ratio_slider)
        comp_ratio_layout.addWidget(self.compressor_ratio_label)
        compressor_form.addRow("Ratio:", comp_ratio_layout)

        self.compressor_attack_slider = QSlider(Qt.Orientation.Horizontal)
        self.compressor_attack_slider.setRange(1, 100)
        self.compressor_attack_slider.setValue(10)
        self.compressor_attack_slider.setEnabled(False)
        self.compressor_attack_slider.valueChanged.connect(self.on_compressor_attack_changed)
        self.compressor_attack_label = QLabel("10 ms")
        comp_attack_layout = QHBoxLayout()
        comp_attack_layout.addWidget(self.compressor_attack_slider)
        comp_attack_layout.addWidget(self.compressor_attack_label)
        compressor_form.addRow("Attack:", comp_attack_layout)

        self.compressor_release_slider = QSlider(Qt.Orientation.Horizontal)
        self.compressor_release_slider.setRange(10, 1000)
        self.compressor_release_slider.setValue(100)
        self.compressor_release_slider.setEnabled(False)
        self.compressor_release_slider.valueChanged.connect(self.on_compressor_release_changed)
        self.compressor_release_label = QLabel("100 ms")
        comp_release_layout = QHBoxLayout()
        comp_release_layout.addWidget(self.compressor_release_slider)
        comp_release_layout.addWidget(self.compressor_release_label)
        compressor_form.addRow("Release:", comp_release_layout)

        self.compressor_makeup_slider = QSlider(Qt.Orientation.Horizontal)
        self.compressor_makeup_slider.setRange(0, 24)
        self.compressor_makeup_slider.setValue(0)
        self.compressor_makeup_slider.setEnabled(False)
        self.compressor_makeup_slider.valueChanged.connect(self.on_compressor_makeup_changed)
        self.compressor_makeup_label = QLabel("0 dB")
        comp_makeup_layout = QHBoxLayout()
        comp_makeup_layout.addWidget(self.compressor_makeup_slider)
        comp_makeup_layout.addWidget(self.compressor_makeup_label)
        compressor_form.addRow("Makeup:", comp_makeup_layout)

        compressor_group.setLayout(compressor_form)
        dynamics_layout.addWidget(compressor_group)

        # De-esser group
        deesser_group = QGroupBox("De-esser")
        deesser_form = QFormLayout()

        self.deesser_checkbox = QCheckBox("Enable")
        self.deesser_checkbox.toggled.connect(self.on_deesser_toggled)
        deesser_form.addRow("", self.deesser_checkbox)

        self.deesser_threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.deesser_threshold_slider.setRange(-40, 0)
        self.deesser_threshold_slider.setValue(-20)
        self.deesser_threshold_slider.setEnabled(False)
        self.deesser_threshold_slider.valueChanged.connect(self.on_deesser_threshold_changed)
        self.deesser_threshold_label = QLabel("-20 dB")
        deesser_thresh_layout = QHBoxLayout()
        deesser_thresh_layout.addWidget(self.deesser_threshold_slider)
        deesser_thresh_layout.addWidget(self.deesser_threshold_label)
        deesser_form.addRow("Threshold:", deesser_thresh_layout)

        self.deesser_reduction_slider = QSlider(Qt.Orientation.Horizontal)
        self.deesser_reduction_slider.setRange(0, 12)
        self.deesser_reduction_slider.setValue(6)
        self.deesser_reduction_slider.setEnabled(False)
        self.deesser_reduction_slider.valueChanged.connect(self.on_deesser_reduction_changed)
        self.deesser_reduction_label = QLabel("6 dB")
        deesser_red_layout = QHBoxLayout()
        deesser_red_layout.addWidget(self.deesser_reduction_slider)
        deesser_red_layout.addWidget(self.deesser_reduction_label)
        deesser_form.addRow("Reduction:", deesser_red_layout)

        deesser_group.setLayout(deesser_form)
        dynamics_layout.addWidget(deesser_group)

        dynamics_layout.addStretch()
        self.tab_widget.addTab(dynamics_tab, "Dynamics")

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
                if "WASAPI" in str(host_info["name"]):
                    wasapi_index = i
                    break

        for i in range(pa.get_device_count()):
            device_info = pa.get_device_info_by_index(i)

            # Only show WASAPI devices if available and not showing all
            if wasapi_index is not None and int(device_info["hostApi"]) != wasapi_index:
                continue

            name = str(device_info["name"])

            if int(device_info["maxInputChannels"]) > 0:
                self.input_combo.addItem(name, i)

            if int(device_info["maxOutputChannels"]) > 0:
                self.output_combo.addItem(name, i)

        pa.terminate()

    def on_show_all_devices_toggled(self, checked):
        """Handle show all devices checkbox toggle."""
        self.populate_devices()

    def on_effects_toggled(self, checked):
        self.audio_processor.set_effects_enabled(checked)

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

    def on_expander_toggled(self, checked):
        self.expander_threshold_slider.setEnabled(checked)
        self.expander_ratio_slider.setEnabled(checked)
        self.expander_attack_slider.setEnabled(checked)
        self.expander_release_slider.setEnabled(checked)
        self.audio_processor.expander_enabled = checked

    def on_expander_threshold_changed(self, value):
        self.expander_threshold_label.setText(f"{value}%")
        self.audio_processor.set_expander_threshold(value)

    def on_expander_ratio_changed(self, value):
        ratio = value / 10.0
        self.expander_ratio_label.setText(f"{ratio:.1f}:1")
        self.audio_processor.set_expander_ratio(ratio)

    def on_expander_attack_changed(self, value):
        self.expander_attack_label.setText(f"{value} ms")
        self.audio_processor.set_expander_attack(value)

    def on_expander_release_changed(self, value):
        self.expander_release_label.setText(f"{value} ms")
        self.audio_processor.set_expander_release(value)

    def on_compressor_toggled(self, checked):
        self.compressor_threshold_slider.setEnabled(checked)
        self.compressor_ratio_slider.setEnabled(checked)
        self.compressor_attack_slider.setEnabled(checked)
        self.compressor_release_slider.setEnabled(checked)
        self.compressor_makeup_slider.setEnabled(checked)
        self.audio_processor.compressor_enabled = checked

    def on_compressor_threshold_changed(self, value):
        self.compressor_threshold_label.setText(f"{value} dB")
        self.audio_processor.set_compressor_threshold(value)

    def on_compressor_ratio_changed(self, value):
        ratio = value / 10.0
        self.compressor_ratio_label.setText(f"{ratio:.1f}:1")
        self.audio_processor.set_compressor_ratio(ratio)

    def on_compressor_attack_changed(self, value):
        self.compressor_attack_label.setText(f"{value} ms")
        self.audio_processor.set_compressor_attack(value)

    def on_compressor_release_changed(self, value):
        self.compressor_release_label.setText(f"{value} ms")
        self.audio_processor.set_compressor_release(value)

    def on_compressor_makeup_changed(self, value):
        self.compressor_makeup_label.setText(f"{value} dB")
        self.audio_processor.set_compressor_makeup(value)

    def on_deesser_toggled(self, checked):
        self.deesser_threshold_slider.setEnabled(checked)
        self.deesser_reduction_slider.setEnabled(checked)
        self.audio_processor.deesser_enabled = checked

    def on_deesser_threshold_changed(self, value):
        self.deesser_threshold_label.setText(f"{value} dB")
        self.audio_processor.set_deesser_threshold(value)

    def on_deesser_reduction_changed(self, value):
        self.deesser_reduction_label.setText(f"{value} dB")
        self.audio_processor.set_deesser_reduction(value)

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
        # Effects on, filters disabled
        self.effects_checkbox.setChecked(True)
        self.hp_checkbox.setChecked(False)
        self.lp_checkbox.setChecked(False)
        self.expander_checkbox.setChecked(False)
        self.compressor_checkbox.setChecked(False)
        self.deesser_checkbox.setChecked(False)

        # Reset slider values
        self.gain_slider.setValue(0)
        self.bass_slider.setValue(0)
        self.treble_slider.setValue(0)
        self.pitch_slider.setValue(0)
        self.delay_slider.setValue(0)
        self.hp_slider.setValue(80)
        self.lp_slider.setValue(16000)

        # Reset expander
        self.expander_threshold_slider.setValue(1)
        self.expander_ratio_slider.setValue(20)
        self.expander_attack_slider.setValue(5)
        self.expander_release_slider.setValue(100)

        # Reset compressor
        self.compressor_threshold_slider.setValue(-10)
        self.compressor_ratio_slider.setValue(40)
        self.compressor_attack_slider.setValue(10)
        self.compressor_release_slider.setValue(100)
        self.compressor_makeup_slider.setValue(0)

        # Reset de-esser
        self.deesser_threshold_slider.setValue(-20)
        self.deesser_reduction_slider.setValue(6)

        # Reset advanced settings
        self.buffer_size_combo.setCurrentIndex(3)  # 1024
        self.pitch_voices_spin.setValue(4)

    def get_preset(self):
        """Collect current settings into a dict."""
        return {
            "effects_enabled": self.effects_checkbox.isChecked(),
            "gain": self.gain_slider.value(),
            "bass": self.bass_slider.value(),
            "treble": self.treble_slider.value(),
            "pitch": self.pitch_slider.value(),
            "delay": self.delay_slider.value(),
            "high_pass_enabled": self.hp_checkbox.isChecked(),
            "high_pass_freq": self.hp_slider.value(),
            "low_pass_enabled": self.lp_checkbox.isChecked(),
            "low_pass_freq": self.lp_slider.value(),
            # Expander
            "expander_enabled": self.expander_checkbox.isChecked(),
            "expander_threshold": self.expander_threshold_slider.value(),
            "expander_ratio": self.expander_ratio_slider.value(),
            "expander_attack": self.expander_attack_slider.value(),
            "expander_release": self.expander_release_slider.value(),
            # Compressor
            "compressor_enabled": self.compressor_checkbox.isChecked(),
            "compressor_threshold": self.compressor_threshold_slider.value(),
            "compressor_ratio": self.compressor_ratio_slider.value(),
            "compressor_attack": self.compressor_attack_slider.value(),
            "compressor_release": self.compressor_release_slider.value(),
            "compressor_makeup": self.compressor_makeup_slider.value(),
            # De-esser
            "deesser_enabled": self.deesser_checkbox.isChecked(),
            "deesser_threshold": self.deesser_threshold_slider.value(),
            "deesser_reduction": self.deesser_reduction_slider.value(),
            # Advanced
            "buffer_size": self.buffer_size_combo.currentData(),
            "pitch_voices": self.pitch_voices_spin.value(),
        }

    def apply_preset(self, preset):
        """Apply a preset dict to the UI controls."""
        # Checkboxes first
        if "effects_enabled" in preset:
            self.effects_checkbox.setChecked(preset["effects_enabled"])
        if "high_pass_enabled" in preset:
            self.hp_checkbox.setChecked(preset["high_pass_enabled"])
        if "low_pass_enabled" in preset:
            self.lp_checkbox.setChecked(preset["low_pass_enabled"])
        if "expander_enabled" in preset:
            self.expander_checkbox.setChecked(preset["expander_enabled"])
        if "compressor_enabled" in preset:
            self.compressor_checkbox.setChecked(preset["compressor_enabled"])
        if "deesser_enabled" in preset:
            self.deesser_checkbox.setChecked(preset["deesser_enabled"])

        # Main sliders
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

        # Expander
        if "expander_threshold" in preset:
            self.expander_threshold_slider.setValue(preset["expander_threshold"])
        if "expander_ratio" in preset:
            self.expander_ratio_slider.setValue(preset["expander_ratio"])
        if "expander_attack" in preset:
            self.expander_attack_slider.setValue(preset["expander_attack"])
        if "expander_release" in preset:
            self.expander_release_slider.setValue(preset["expander_release"])

        # Compressor
        if "compressor_threshold" in preset:
            self.compressor_threshold_slider.setValue(preset["compressor_threshold"])
        if "compressor_ratio" in preset:
            self.compressor_ratio_slider.setValue(preset["compressor_ratio"])
        if "compressor_attack" in preset:
            self.compressor_attack_slider.setValue(preset["compressor_attack"])
        if "compressor_release" in preset:
            self.compressor_release_slider.setValue(preset["compressor_release"])
        if "compressor_makeup" in preset:
            self.compressor_makeup_slider.setValue(preset["compressor_makeup"])

        # De-esser
        if "deesser_threshold" in preset:
            self.deesser_threshold_slider.setValue(preset["deesser_threshold"])
        if "deesser_reduction" in preset:
            self.deesser_reduction_slider.setValue(preset["deesser_reduction"])

        # Advanced
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
