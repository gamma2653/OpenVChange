"""Main entry point for OpenVChange audio routing application."""

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from openvchange import presets, settings
from openvchange.audio import AudioProcessor, AudioStartError
from openvchange.builtin_presets import BUILT_IN, NEUTRAL, SESSION_DEFAULTS
from openvchange.widgets import LevelMeter

logger = logging.getLogger(__name__)

# Where each entry of a device list keeps the name and host API of its device.
DEVICE_IDENTITY_ROLE = Qt.ItemDataRole.UserRole + 1


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, settings_path=None):
        super().__init__()
        self.settings_path = settings_path or settings.default_path()
        self.closed = False
        self.setWindowTitle("OpenVChange - Virtual Audio Router")
        self.setMinimumSize(500, 580)

        self.audio_processor = AudioProcessor()
        self.audio_processor.levels_changed.connect(self.update_level_meters)
        self.audio_processor.error_occurred.connect(self.on_audio_error)
        self.effects = self.audio_processor.effects

        self.init_ui()
        self.watch_preset_controls()
        self.populate_devices()
        self.restore_settings()

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
        self.refresh_devices_button = QPushButton("Refresh")
        self.refresh_devices_button.setToolTip("Look for devices that were plugged in or removed")
        self.refresh_devices_button.clicked.connect(self.on_refresh_devices)
        device_options = QHBoxLayout()
        device_options.addWidget(self.show_all_devices_checkbox)
        device_options.addStretch()
        device_options.addWidget(self.refresh_devices_button)
        device_layout.addRow("Input Device:", self.input_combo)
        device_layout.addRow("Output Device:", self.output_combo)
        device_layout.addRow("", device_options)

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

        # Level meters
        meter_group = QGroupBox("Levels")
        meter_layout = QFormLayout()
        self.input_meter = LevelMeter()
        self.output_meter = LevelMeter()
        self.input_level_label = QLabel()
        self.output_level_label = QLabel()
        for name, meter, label in (
            ("Input:", self.input_meter, self.input_level_label),
            ("Output:", self.output_meter, self.output_level_label),
        ):
            label.setMinimumWidth(70)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            label.setText(meter.readout())
            row = QHBoxLayout()
            row.addWidget(meter)
            row.addWidget(label)
            meter_layout.addRow(name, row)
        self.output_meter.setToolTip(
            "Peak level in dB below full scale. The red light means the output is being "
            "pushed past full scale and is distorting. Turn the gain down."
        )
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

        # Presets: the ones that come with the app, and the user's own files
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(BUILT_IN))
        self.preset_combo.setPlaceholderText("Custom")
        self.preset_combo.setToolTip("Presets that come with OpenVChange. Shows Custom once you change a setting.")
        self.preset_combo.activated.connect(self.on_builtin_preset_chosen)
        preset_layout.addWidget(self.preset_combo, stretch=1)

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
        """Fill the device lists, keeping the current selection where it still exists."""
        show_all = self.show_all_devices_checkbox.isChecked()
        devices = self.audio_processor.list_devices(all_host_apis=show_all)

        for combo, wanted in ((self.input_combo, "is_input"), (self.output_combo, "is_output")):
            selected = combo.currentData(DEVICE_IDENTITY_ROLE)
            combo.clear()
            for device in devices:
                if not getattr(device, wanted):
                    continue
                # The same hardware appears once per host API, so say which one this is.
                label = f"{device.name} [{device.host_api}]" if show_all else device.name
                combo.addItem(label, device.index)
                combo.setItemData(combo.count() - 1, device.identity, DEVICE_IDENTITY_ROLE)
            if selected is not None:
                index = combo.findData(selected, DEVICE_IDENTITY_ROLE)
                if index >= 0:
                    combo.setCurrentIndex(index)

    def on_show_all_devices_toggled(self, checked):
        """Handle show all devices checkbox toggle."""
        self.populate_devices()

    def on_refresh_devices(self):
        """Look for devices that were plugged in or removed since the list was built."""
        self.audio_processor.refresh_devices()
        self.populate_devices()
        found = self.input_combo.count() + self.output_combo.count()
        self.status_label.setText(f"Status: Found {found} devices")

    def on_effects_toggled(self, checked):
        self.audio_processor.set_effects_enabled(checked)

    def on_gain_changed(self, value):
        self.gain_label.setText(f"{value} dB")
        self.effects.set_gain(value)

    def on_bass_changed(self, value):
        self.bass_label.setText(f"{value} dB")
        self.effects.set_bass(value)

    def on_treble_changed(self, value):
        self.treble_label.setText(f"{value} dB")
        self.effects.set_treble(value)

    def on_pitch_changed(self, value):
        semitones = value / 10.0  # Convert from slider units to semitones
        self.pitch_label.setText(f"{semitones:.1f} st")
        self.effects.set_pitch(semitones)

    def on_delay_changed(self, value):
        self.delay_label.setText(f"{value} ms")
        self.effects.set_delay(value)

    def on_hp_toggled(self, checked):
        self.hp_slider.setEnabled(checked)
        self.effects.set_high_pass_enabled(checked)

    def on_hp_changed(self, value):
        self.hp_label.setText(f"{value} Hz")
        self.effects.set_low_cut(value)

    def on_lp_toggled(self, checked):
        self.lp_slider.setEnabled(checked)
        self.effects.set_low_pass_enabled(checked)

    def on_lp_changed(self, value):
        self.lp_label.setText(f"{value} Hz")
        self.effects.set_high_cut(value)

    def on_expander_toggled(self, checked):
        self.expander_threshold_slider.setEnabled(checked)
        self.expander_ratio_slider.setEnabled(checked)
        self.expander_attack_slider.setEnabled(checked)
        self.expander_release_slider.setEnabled(checked)
        self.effects.set_expander_enabled(checked)

    def on_expander_threshold_changed(self, value):
        self.expander_threshold_label.setText(f"{value}%")
        self.effects.set_expander_threshold(value)

    def on_expander_ratio_changed(self, value):
        ratio = value / 10.0
        self.expander_ratio_label.setText(f"{ratio:.1f}:1")
        self.effects.set_expander_ratio(ratio)

    def on_expander_attack_changed(self, value):
        self.expander_attack_label.setText(f"{value} ms")
        self.effects.set_expander_attack(value)

    def on_expander_release_changed(self, value):
        self.expander_release_label.setText(f"{value} ms")
        self.effects.set_expander_release(value)

    def on_compressor_toggled(self, checked):
        self.compressor_threshold_slider.setEnabled(checked)
        self.compressor_ratio_slider.setEnabled(checked)
        self.compressor_attack_slider.setEnabled(checked)
        self.compressor_release_slider.setEnabled(checked)
        self.compressor_makeup_slider.setEnabled(checked)
        self.effects.set_compressor_enabled(checked)

    def on_compressor_threshold_changed(self, value):
        self.compressor_threshold_label.setText(f"{value} dB")
        self.effects.set_compressor_threshold(value)

    def on_compressor_ratio_changed(self, value):
        ratio = value / 10.0
        self.compressor_ratio_label.setText(f"{ratio:.1f}:1")
        self.effects.set_compressor_ratio(ratio)

    def on_compressor_attack_changed(self, value):
        self.compressor_attack_label.setText(f"{value} ms")
        self.effects.set_compressor_attack(value)

    def on_compressor_release_changed(self, value):
        self.compressor_release_label.setText(f"{value} ms")
        self.effects.set_compressor_release(value)

    def on_compressor_makeup_changed(self, value):
        self.compressor_makeup_label.setText(f"{value} dB")
        self.effects.set_compressor_makeup(value)

    def on_deesser_toggled(self, checked):
        self.deesser_threshold_slider.setEnabled(checked)
        self.deesser_reduction_slider.setEnabled(checked)
        self.effects.set_deesser_enabled(checked)

    def on_deesser_threshold_changed(self, value):
        self.deesser_threshold_label.setText(f"{value} dB")
        self.effects.set_deesser_threshold(value)

    def on_deesser_reduction_changed(self, value):
        self.deesser_reduction_label.setText(f"{value} dB")
        self.effects.set_deesser_reduction(value)

    def on_buffer_size_changed(self, index):
        """Handle buffer size combo box change."""
        self.apply_stream_settings()

    def on_pitch_voices_changed(self, value):
        """Handle pitch voices spin box change."""
        self.apply_stream_settings()

    def stream_settings(self):
        """The settings that are fixed for as long as a stream runs."""
        return (self.buffer_size_combo.currentData(), self.pitch_voices_spin.value())

    def apply_stream_settings(self):
        """Pass the stream settings to the engine, unless it is running.

        The engine reads them while it processes, so they must not change under it. The
        controls are locked while it runs, but a preset can still change them. They are
        applied again at each start.
        """
        if self.audio_processor.running:
            return
        buffer_size, voices = self.stream_settings()
        if buffer_size is not None:
            self.audio_processor.set_chunk_size(buffer_size)
        self.effects.set_pitch_num_voices(voices)

    def on_reset_defaults(self):
        """Reset all filter settings to their default values."""
        self.apply_preset({**NEUTRAL, **SESSION_DEFAULTS})

    def on_builtin_preset_chosen(self, index):
        """Apply the built-in preset picked from the list."""
        name = self.preset_combo.itemText(index)
        self.apply_preset(BUILT_IN[name])
        self.status_label.setText(f"Status: Preset applied: {name}")

    def show_matching_builtin_preset(self):
        """Show in the list which built-in preset the controls match, if any."""
        current = self.get_preset()
        for index in range(self.preset_combo.count()):
            wanted = BUILT_IN[self.preset_combo.itemText(index)]
            if all(current[name] == value for name, value in wanted.items()):
                self.preset_combo.setCurrentIndex(index)
                return
        self.preset_combo.setCurrentIndex(-1)

    def watch_preset_controls(self):
        """Keep the preset list in step with the controls, however they are changed."""
        for name, control in self.preset_controls().items():
            if name not in NEUTRAL:
                continue
            changed = control.toggled if isinstance(control, QCheckBox) else control.valueChanged
            changed.connect(self.show_matching_builtin_preset)
        self.show_matching_builtin_preset()

    def preset_controls(self):
        """The controls a preset covers, by the name each has in a preset file."""
        return {
            "effects_enabled": self.effects_checkbox,
            "gain": self.gain_slider,
            "bass": self.bass_slider,
            "treble": self.treble_slider,
            "pitch": self.pitch_slider,
            "delay": self.delay_slider,
            "high_pass_enabled": self.hp_checkbox,
            "high_pass_freq": self.hp_slider,
            "low_pass_enabled": self.lp_checkbox,
            "low_pass_freq": self.lp_slider,
            # Expander
            "expander_enabled": self.expander_checkbox,
            "expander_threshold": self.expander_threshold_slider,
            "expander_ratio": self.expander_ratio_slider,
            "expander_attack": self.expander_attack_slider,
            "expander_release": self.expander_release_slider,
            # Compressor
            "compressor_enabled": self.compressor_checkbox,
            "compressor_threshold": self.compressor_threshold_slider,
            "compressor_ratio": self.compressor_ratio_slider,
            "compressor_attack": self.compressor_attack_slider,
            "compressor_release": self.compressor_release_slider,
            "compressor_makeup": self.compressor_makeup_slider,
            # De-esser
            "deesser_enabled": self.deesser_checkbox,
            "deesser_threshold": self.deesser_threshold_slider,
            "deesser_reduction": self.deesser_reduction_slider,
            # Advanced
            "buffer_size": self.buffer_size_combo,
            "pitch_voices": self.pitch_voices_spin,
        }

    def preset_fields(self):
        """What each control accepts, for checking a preset before it is applied."""
        fields = {}
        for name, control in self.preset_controls().items():
            if isinstance(control, QCheckBox):
                fields[name] = presets.Toggle()
            elif isinstance(control, QComboBox):
                fields[name] = presets.Choice(tuple(control.itemData(i) for i in range(control.count())))
            else:
                fields[name] = presets.Number(control.minimum(), control.maximum())
        return fields

    def get_preset(self):
        """Collect current settings into a dict."""
        preset = {}
        for name, control in self.preset_controls().items():
            if isinstance(control, QCheckBox):
                preset[name] = control.isChecked()
            elif isinstance(control, QComboBox):
                preset[name] = control.currentData()
            else:
                preset[name] = control.value()
        return preset

    def apply_preset(self, preset):
        """Apply a preset to the controls.

        The preset is checked first, and nothing is applied if it is not usable. Returns
        a note for each value that was changed or left out. Raises PresetError.
        """
        values, notes = presets.check(preset, self.preset_fields())
        controls = self.preset_controls()
        for name, value in values.items():
            control = controls[name]
            if isinstance(control, QCheckBox):
                control.setChecked(value)
            elif isinstance(control, QComboBox):
                control.setCurrentIndex(control.findData(value))
            else:
                control.setValue(value)
        return notes

    def on_save_preset(self):
        """Save current settings to a JSON file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Preset", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            presets.save(path, self.get_preset())
        except presets.PresetError as e:
            self.status_label.setText(f"Status: Could not save preset: {e}")
            return
        self.status_label.setText("Status: Preset saved")

    def on_load_preset(self):
        """Load settings from a JSON file."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Preset", "", "JSON Files (*.json)"
        )
        if not path:
            return
        stream_settings = self.stream_settings()
        try:
            notes = self.apply_preset(presets.load(path))
        except presets.PresetError as e:
            self.status_label.setText(f"Status: Could not load preset: {e}")
            return

        if self.audio_processor.running and self.stream_settings() != stream_settings:
            notes.append("buffer size and pitch voices take effect at the next start")
        status = "Status: Preset loaded"
        if notes:
            status += f" ({'; '.join(notes)})"
        self.status_label.setText(status)
        self.status_label.setToolTip(status)

    def update_level_meters(self, levels):
        """Show new levels from the engine."""
        self.input_meter.update_level(levels.input_db, levels.input_clipped, levels.seconds)
        self.output_meter.update_level(levels.output_db, levels.output_clipped, levels.seconds)
        self.input_level_label.setText(self.input_meter.readout())
        self.output_level_label.setText(self.output_meter.readout())

    def reset_level_meters(self):
        """Show silence, as when nothing is running."""
        for meter, label in (
            (self.input_meter, self.input_level_label),
            (self.output_meter, self.output_level_label),
        ):
            meter.reset()
            label.setText(meter.readout())

    def on_start(self):
        """Start audio processing."""
        input_device = self.input_combo.currentData()
        output_device = self.output_combo.currentData()

        if input_device is None or output_device is None:
            self.status_label.setText("Status: Please select both devices")
            return

        self.audio_processor.set_input_device(input_device)
        self.audio_processor.set_output_device(output_device)
        self.apply_stream_settings()
        try:
            self.audio_processor.start()
        except AudioStartError as e:
            self.status_label.setText(f"Status: Could not start audio: {e}")
            return

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.input_combo.setEnabled(False)
        self.output_combo.setEnabled(False)
        self.show_all_devices_checkbox.setEnabled(False)
        self.refresh_devices_button.setEnabled(False)
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
        self.show_all_devices_checkbox.setEnabled(True)
        self.refresh_devices_button.setEnabled(True)
        self.buffer_size_combo.setEnabled(True)
        self.pitch_voices_spin.setEnabled(True)
        self.apply_stream_settings()
        self.status_label.setText("Status: Stopped")
        self.reset_level_meters()

    def restore_settings(self):
        """Bring back the devices and settings from the last session, where possible."""
        try:
            saved = settings.load(self.settings_path)
            if not saved:
                return
            show_all = saved.get("show_all_devices", False)
            if not isinstance(show_all, bool):
                raise settings.SettingsError("the file is damaged")
            notes = self.apply_preset(saved.get("preset", {}))
        except (settings.SettingsError, presets.PresetError) as e:
            logger.warning("Could not restore settings from %s: %s", self.settings_path, e)
            self.status_label.setText(f"Status: Your saved settings could not be restored: {e}")
            return

        self.show_all_devices_checkbox.setChecked(show_all)
        missing = [
            kind
            for kind, combo in (("input", self.input_combo), ("output", self.output_combo))
            if not self.select_device(combo, saved.get(f"{kind}_device"))
        ]
        if missing:
            notes.append(f"the {' and '.join(missing)} device used last time was not found")
        if notes:
            status = f"Status: Stopped ({'; '.join(notes)})"
            self.status_label.setText(status)
            self.status_label.setToolTip(status)

    def select_device(self, combo, identity):
        """Select the device with this identity. Returns False if one was asked for but is gone."""
        if identity is None:
            return True
        index = combo.findData(identity, DEVICE_IDENTITY_ROLE) if isinstance(identity, str) else -1
        if index < 0:
            return False
        combo.setCurrentIndex(index)
        return True

    def save_settings(self):
        """Remember the devices and settings for the next session."""
        data = {
            "version": 1,
            "input_device": self.input_combo.currentData(DEVICE_IDENTITY_ROLE),
            "output_device": self.output_combo.currentData(DEVICE_IDENTITY_ROLE),
            "show_all_devices": self.show_all_devices_checkbox.isChecked(),
            "preset": self.get_preset(),
        }
        try:
            settings.save(self.settings_path, data)
        except settings.SettingsError as e:
            # Closing must not fail because of this, and there is nobody left to tell.
            logger.warning("Could not save settings to %s: %s", self.settings_path, e)

    def on_audio_error(self, message):
        """Stop after the engine has failed, and say why."""
        self.on_stop()
        self.status_label.setText(f"Status: Stopped after an audio error: {message}")

    def closeEvent(self, event):
        """Handle window close event."""
        if not self.closed:
            self.closed = True
            self.save_settings()
        self.audio_processor.shut_down()
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
