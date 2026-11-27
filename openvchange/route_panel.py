"""One route in the window: its devices, its effects, its meters, and its stream settings."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from openvchange import __version__, presets
from openvchange.audio import AudioProcessor, Device, Levels, Route
from openvchange.hotkey import GlobalHotkey, HotkeyError
from openvchange.widgets import LevelMeter

# Where each entry of a device list keeps the name and host API of its device, and how
# many channels it has in the direction the list is for.
DEVICE_IDENTITY_ROLE = Qt.ItemDataRole.UserRole + 1
DEVICE_CHANNELS_ROLE = Qt.ItemDataRole.UserRole + 2


class DevicePicker:
    """A device list and, next to it, the list of the channels of the chosen device."""

    def __init__(self, lists_inputs: bool) -> None:
        self.lists_inputs = lists_inputs

        self.device = QComboBox()
        self.device.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.device.currentIndexChanged.connect(self.fill_channels)

        self.channel = QComboBox()
        self.channel.setFixedWidth(64)
        self.channel.setToolTip(
            "The channel of the device to take. All takes every channel, mixed."
            if lists_inputs
            else "The channel of the device to play on. All plays on every channel."
        )

        self.row = QHBoxLayout()
        self.row.addWidget(self.device, stretch=1)
        self.row.addWidget(self.channel)
        self.fill_channels()

    def fill_devices(self, devices: list[Device], name_host_api: bool) -> None:
        """List the devices, keeping the current selection where it still exists."""
        selected = self.identity()
        self.device.blockSignals(True)
        self.device.clear()
        for device in devices:
            channels = device.input_channels if self.lists_inputs else device.output_channels
            if channels <= 0:
                continue
            # The same hardware appears once per host API, so say which one this is.
            label = f"{device.name} [{device.host_api}]" if name_host_api else device.name
            self.device.addItem(label, device.index)
            self.device.setItemData(self.device.count() - 1, device.identity, DEVICE_IDENTITY_ROLE)
            self.device.setItemData(self.device.count() - 1, channels, DEVICE_CHANNELS_ROLE)
        if selected is not None:
            self.select(selected)
        self.device.blockSignals(False)
        self.fill_channels()

    def fill_channels(self) -> None:
        """List the channels of the selected device, keeping the current one if it has it."""
        selected = self.channel.currentData()
        count = self.device.currentData(DEVICE_CHANNELS_ROLE) or 0
        self.channel.clear()
        self.channel.addItem("All", None)
        if count > 1:
            for channel in range(count):
                self.channel.addItem(f"Ch {channel + 1}", channel)
        self.channel.setCurrentIndex(max(0, self.channel.findData(selected)))
        self.channel.setEnabled(self.device.isEnabled() and count > 1)

    def identity(self) -> str | None:
        """The name and host API of the selected device, which survive a refresh."""
        return self.device.currentData(DEVICE_IDENTITY_ROLE)

    def select(self, identity: object) -> bool:
        """Select the device with this identity. Returns False if it is not listed."""
        index = self.device.findData(identity, DEVICE_IDENTITY_ROLE) if isinstance(identity, str) else -1
        if index < 0:
            return False
        self.device.setCurrentIndex(index)
        return True

    def restore(self, identity: object, channel: int | None) -> bool:
        """Select a device and a channel that were saved. Returns False if either is gone."""
        if identity is None:
            return True  # nothing was selected when it was saved
        if not self.select(identity):
            return False
        index = 0 if channel is None else self.channel.findData(channel)
        self.channel.setCurrentIndex(max(index, 0))
        return index >= 0

    def set_enabled(self, enabled: bool) -> None:
        self.device.setEnabled(enabled)
        self.channel.setEnabled(enabled and self.channel.count() > 1)


class RoutePanel(QWidget):
    """The tabs of one route: Main, Dynamics, and Advanced Settings.

    Every control acts on the route's own effects chain, and the meters show its own
    levels. The window keeps one panel per route of the engine.
    """

    # Something for the status line.
    status = Signal(str)

    # A control that a preset covers changed, however it was changed.
    controls_changed = Signal()

    # The device filter and the refresh button concern every route, so the window
    # handles them.
    show_all_toggled = Signal(bool)
    refresh_requested = Signal()

    def __init__(self, engine: AudioProcessor, route: Route, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.route = route
        self.effects = route.effects

        # Lets the effects be switched while another application has the focus
        self.hotkey = GlobalHotkey(parent=self)

        # Set by the window: who else uses a shortcut, so that two routes do not fight
        # over one.
        self.shortcut_owner: Callable[[QKeySequence], str | None] = lambda sequence: None

        self.init_ui()
        self.hotkey.pressed.connect(self.effects_checkbox.toggle)
        self.watch_preset_controls()
        self.push_settings()

    def init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # ---- Main tab ----
        main_tab = QWidget()
        main_layout = QVBoxLayout(main_tab)

        # Device selection group
        device_group = QGroupBox("Audio Devices")
        device_layout = QFormLayout()

        self.input = DevicePicker(lists_inputs=True)
        self.output = DevicePicker(lists_inputs=False)
        self.show_all_devices_checkbox = QCheckBox("Show all devices")
        self.show_all_devices_checkbox.toggled.connect(self.show_all_toggled)
        self.refresh_devices_button = QPushButton("Refresh")
        self.refresh_devices_button.setToolTip("Look for devices that were plugged in or removed")
        self.refresh_devices_button.clicked.connect(self.refresh_requested)
        device_options = QHBoxLayout()
        device_options.addWidget(self.show_all_devices_checkbox)
        device_options.addStretch()
        device_options.addWidget(self.refresh_devices_button)
        device_layout.addRow("Input Device:", self.input.row)
        device_layout.addRow("Output Device:", self.output.row)
        device_layout.addRow("", device_options)

        device_group.setLayout(device_layout)
        main_layout.addWidget(device_group)

        # Filters group
        filters_group = self.filters_group = QGroupBox("Filters")
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

        # Formant control
        formant_layout = QHBoxLayout()
        formant_layout.addWidget(QLabel("Formant:"))
        self.formant_slider = QSlider(Qt.Orientation.Horizontal)
        self.formant_slider.setRange(-120, 120)  # -12 to +12 semitones (x10 for precision)
        self.formant_slider.setValue(0)
        self.formant_slider.setToolTip(
            "Moves the resonances of the voice without changing its pitch. Down sounds like "
            "a larger person, up like a smaller one. Adds about 20 ms of delay while in use."
        )
        self.formant_slider.valueChanged.connect(self.on_formant_changed)
        formant_layout.addWidget(self.formant_slider)
        self.formant_label = QLabel("0.0 st")
        self.formant_label.setMinimumWidth(70)
        formant_layout.addWidget(self.formant_label)
        filters_layout.addLayout(formant_layout)

        self.formant_preserve_checkbox = QCheckBox("Keep formants when shifting pitch")
        self.formant_preserve_checkbox.setToolTip(
            "Shifting the pitch also shifts the resonances of the voice, which is what makes "
            "it sound like a tape played at the wrong speed. This moves them back."
        )
        self.formant_preserve_checkbox.toggled.connect(self.on_formant_preserve_toggled)
        filters_layout.addWidget(self.formant_preserve_checkbox)

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

        self.tabs.addTab(main_tab, "Main")

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
        self.tabs.addTab(dynamics_tab, "Dynamics")

        # ---- Advanced Settings tab ----
        advanced_tab = QWidget()
        advanced_layout = QVBoxLayout(advanced_tab)

        advanced_group = QGroupBox("Advanced Settings")
        advanced_form = QFormLayout()

        self.buffer_size_combo = QComboBox()
        for size in [128, 256, 512, 1024, 2048, 4096]:
            self.buffer_size_combo.addItem(str(size), size)
        self.buffer_size_combo.setCurrentIndex(3)  # Default: 1024
        self.buffer_size_combo.setToolTip(
            "Smaller buffers shorten the delay and raise the risk of dropouts. A device that "
            "another route uses with a larger buffer is opened with the larger one."
        )
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

        # Shortcut
        shortcut_group = QGroupBox("Shortcut")
        shortcut_form = QFormLayout()
        self.hotkey_edit = QKeySequenceEdit()
        self.hotkey_edit.setMaximumSequenceLength(1)
        self.hotkey_edit.setClearButtonEnabled(True)
        self.hotkey_edit.editingFinished.connect(self.on_hotkey_edited)
        shortcut_form.addRow("Toggle effects:", self.hotkey_edit)
        shortcut_group.setLayout(shortcut_form)
        advanced_layout.addWidget(shortcut_group)

        shortcut_note = QLabel(
            "Switches the effects of this route on and off from anywhere, also while a game "
            "or another application has the focus. Click the field and press the keys to use, "
            "for example Ctrl+Shift+F9."
            if self.hotkey.supported
            else "Shortcuts that work in other applications are only available on Windows."
        )
        shortcut_note.setWordWrap(True)
        advanced_layout.addWidget(shortcut_note)
        self.hotkey_edit.setEnabled(self.hotkey.supported)

        advanced_layout.addStretch()

        self.version_label = QLabel(f"OpenVChange {__version__}")
        self.version_label.setEnabled(False)
        self.version_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        advanced_layout.addWidget(self.version_label)

        self.tabs.addTab(advanced_tab, "Advanced Settings")

    # --- devices -------------------------------------------------------------------

    def populate_devices(self, devices: list[Device], show_all: bool) -> None:
        """Fill the device lists, keeping the current selection where it still exists."""
        self.show_all_devices_checkbox.blockSignals(True)
        self.show_all_devices_checkbox.setChecked(show_all)
        self.show_all_devices_checkbox.blockSignals(False)
        self.input.fill_devices(devices, name_host_api=show_all)
        self.output.fill_devices(devices, name_host_api=show_all)

    def apply_devices(self) -> bool:
        """Tell the route which devices and channels are chosen. False if one is missing."""
        self.route.input_device = self.input.device.currentData()
        self.route.input_channel = self.input.channel.currentData()
        self.route.output_device = self.output.device.currentData()
        self.route.output_channel = self.output.channel.currentData()
        return self.route.input_device is not None and self.route.output_device is not None

    def set_locked(self, locked: bool) -> None:
        """Lock what cannot change while audio is running."""
        self.input.set_enabled(not locked)
        self.output.set_enabled(not locked)
        for widget in (
            self.show_all_devices_checkbox,
            self.refresh_devices_button,
            self.buffer_size_combo,
            self.pitch_voices_spin,
        ):
            widget.setEnabled(not locked)

    # --- effects -------------------------------------------------------------------

    def on_effects_toggled(self, checked):
        self.route.effects_enabled = checked

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

    def on_formant_changed(self, value):
        semitones = value / 10.0  # Convert from slider units to semitones
        self.formant_label.setText(f"{semitones:.1f} st")
        self.effects.set_formant(semitones)

    def on_formant_preserve_toggled(self, checked):
        self.effects.set_formant_preserve(checked)

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

    # --- stream settings -----------------------------------------------------------

    def on_buffer_size_changed(self, index):
        self.apply_stream_settings()

    def on_pitch_voices_changed(self, value):
        self.apply_stream_settings()

    def stream_settings(self):
        """The settings that are fixed for as long as a stream runs."""
        return (self.buffer_size_combo.currentData(), self.pitch_voices_spin.value())

    def apply_stream_settings(self):
        """Pass the stream settings to the route, unless audio is running.

        The engine reads them while it processes, so they must not change under it. The
        controls are locked while it runs, but a preset can still change them. They are
        applied again at each start.
        """
        if self.engine.running:
            return
        buffer_size, voices = self.stream_settings()
        if buffer_size is not None:
            self.route.chunk_size = buffer_size
        self.effects.set_pitch_num_voices(voices)

    # --- presets -------------------------------------------------------------------

    def watch_preset_controls(self):
        """Report every change of a control that a preset covers."""
        for control in self.preset_controls().values():
            if isinstance(control, QCheckBox):
                control.toggled.connect(self.controls_changed)
            elif isinstance(control, QComboBox):
                control.currentIndexChanged.connect(self.controls_changed)
            else:
                control.valueChanged.connect(self.controls_changed)

    def push_settings(self):
        """Give the route every setting as the controls show it.

        A control only reports a value that changes, and the route may not have been
        told what the controls show.
        """
        for control in self.preset_controls().values():
            if isinstance(control, QCheckBox):
                control.toggled.emit(control.isChecked())
            elif isinstance(control, QComboBox):
                control.currentIndexChanged.emit(control.currentIndex())
            else:
                control.valueChanged.emit(control.value())

    def preset_controls(self):
        """The controls a preset covers, by the name each has in a preset file."""
        return {
            "effects_enabled": self.effects_checkbox,
            "gain": self.gain_slider,
            "bass": self.bass_slider,
            "treble": self.treble_slider,
            "pitch": self.pitch_slider,
            "formant": self.formant_slider,
            "formant_preserve": self.formant_preserve_checkbox,
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

    # --- meters --------------------------------------------------------------------

    def update_levels(self, levels: Levels) -> None:
        """Show new levels from the engine."""
        self.input_meter.update_level(levels.input_db, levels.input_clipped, levels.seconds)
        self.output_meter.update_level(levels.output_db, levels.output_clipped, levels.seconds)
        self.input_level_label.setText(self.input_meter.readout())
        self.output_level_label.setText(self.output_meter.readout())

    def reset_level_meters(self) -> None:
        """Show silence, as when nothing is running."""
        for meter, label in (
            (self.input_meter, self.input_level_label),
            (self.output_meter, self.output_level_label),
        ):
            meter.reset()
            label.setText(meter.readout())

    # --- the shortcut --------------------------------------------------------------

    def on_hotkey_edited(self):
        """Use the shortcut that was just entered, or say why it cannot be used."""
        wanted = self.hotkey_edit.keySequence()
        if wanted == self.hotkey.sequence:
            return
        try:
            self.set_shortcut(wanted)
        except HotkeyError as e:
            self.status.emit(f"Status: {describe_shortcut(wanted)} cannot be used: {e}")
            self.hotkey_edit.setKeySequence(self.hotkey.sequence)
            return
        if wanted.isEmpty():
            self.status.emit("Status: Shortcut removed")
        else:
            self.status.emit(f"Status: {describe_shortcut(wanted)} now switches the effects")

    def set_shortcut(self, sequence: QKeySequence) -> None:
        """Use this shortcut. Raises HotkeyError, also when another route has it."""
        owner = None if sequence.isEmpty() else self.shortcut_owner(sequence)
        if owner is not None:
            raise HotkeyError(f"{owner} already uses it")
        self.hotkey.set_sequence(sequence)
        self.hotkey_edit.setKeySequence(self.hotkey.sequence)

    def close_shortcut(self) -> None:
        """Give the shortcut back to the system."""
        self.hotkey.close()


def describe_shortcut(sequence: QKeySequence) -> str:
    """A shortcut as the user would write it."""
    return sequence.toString(QKeySequence.SequenceFormat.NativeText) or "An empty shortcut"
