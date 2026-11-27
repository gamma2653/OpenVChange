"""Main entry point for OpenVChange audio routing application."""

import logging
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from openvchange import __version__, presets, resources, settings
from openvchange.audio import AudioProcessor, AudioStartError
from openvchange.builtin_presets import BUILT_IN, NEUTRAL, SESSION_DEFAULTS
from openvchange.hotkey import HotkeyError
from openvchange.route_panel import DEVICE_IDENTITY_ROLE, RoutePanel

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window: a tab per route, and what applies to all of them."""

    def __init__(self, settings_path=None):
        super().__init__()
        self.settings_path = settings_path or settings.default_path()
        self.closed = False
        self.setWindowTitle("OpenVChange - Virtual Audio Router")
        self.setMinimumWidth(500)  # the height follows from what is in the window

        self.audio_processor = AudioProcessor()
        self.audio_processor.levels_changed.connect(self.update_level_meters)
        self.audio_processor.error_occurred.connect(self.on_audio_error)

        # One panel per route of the engine, in the same order.
        self.routes = []
        self.show_all_devices = False

        self.init_ui()
        self.add_route_panel(self.audio_processor.routes[0])
        self.restore_settings()

    def init_ui(self):
        """Initialize the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # A tab per route, each with tabs of its own
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.tabCloseRequested.connect(self.remove_route)
        self.tabs.currentChanged.connect(self.on_route_shown)
        self.add_route_button = QPushButton("Add Route")
        self.add_route_button.setToolTip("Another way through the app, starting as a copy of the route shown")
        self.add_route_button.clicked.connect(self.add_route)
        self.tabs.setCornerWidget(self.add_route_button, Qt.Corner.TopRightCorner)
        layout.addWidget(self.tabs)

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

    # --- routes --------------------------------------------------------------------

    @property
    def route(self):
        """The panel of the route whose tab is shown."""
        return self.tabs.currentWidget()

    def add_route_panel(self, route):
        """A tab for a route of the engine."""
        panel = RoutePanel(self.audio_processor, route)
        panel.status.connect(self.status_label.setText)
        panel.controls_changed.connect(self.on_controls_changed)
        panel.show_all_toggled.connect(self.set_show_all_devices)
        panel.refresh_requested.connect(self.on_refresh_devices)
        panel.shortcut_owner = lambda sequence: self.shortcut_owner(sequence, panel)
        panel.populate_devices(self.devices(), self.show_all_devices)
        self.routes.append(panel)
        self.tabs.addTab(panel, "")
        self.name_routes()
        return panel

    def add_route(self):
        """Add a route like the one shown, to an output no route uses yet, and show it."""
        model = self.route
        panel = self.add_route_panel(self.audio_processor.add_route())
        panel.apply_preset(model.get_preset())
        panel.input.restore(model.input.identity(), model.input.channel.currentData())
        taken = {other.output.identity() for other in self.routes if other is not panel}
        for index in range(panel.output.device.count()):
            if panel.output.device.itemData(index, DEVICE_IDENTITY_ROLE) not in taken:
                panel.output.device.setCurrentIndex(index)
                break
        self.tabs.setCurrentWidget(panel)

    def remove_route(self, index):
        """Remove a route, unless it is the last one."""
        if len(self.routes) == 1:
            return
        panel = self.routes.pop(index)
        self.audio_processor.remove_route(panel.route)
        self.tabs.removeTab(index)
        panel.close_shortcut()
        panel.deleteLater()
        self.name_routes()

    def name_routes(self):
        """Number the tabs, and let only a route that is not the last be closed."""
        for index, panel in enumerate(self.routes):
            self.tabs.setTabText(index, f"Route {index + 1}")
            for side in (QTabBar.ButtonPosition.RightSide, QTabBar.ButtonPosition.LeftSide):
                button = self.tabs.tabBar().tabButton(index, side)
                if button is not None:
                    button.setVisible(len(self.routes) > 1)
                    button.setEnabled(not self.audio_processor.running)

    def on_route_shown(self, index):
        self.show_matching_builtin_preset()

    def shortcut_owner(self, sequence, asking):
        """Which other route uses a shortcut, by name, or None."""
        for index, panel in enumerate(self.routes):
            if panel is not asking and panel.hotkey.sequence == sequence:
                return f"route {index + 1}"
        return None

    # --- devices -------------------------------------------------------------------

    def devices(self):
        return self.audio_processor.list_devices(all_host_apis=self.show_all_devices)

    def populate_devices(self):
        """Fill the device lists of every route, keeping each selection where it still exists."""
        devices = self.devices()
        for panel in self.routes:
            panel.populate_devices(devices, self.show_all_devices)

    def set_show_all_devices(self, checked):
        """The device filter is one setting for every route."""
        self.show_all_devices = checked
        self.populate_devices()

    def on_refresh_devices(self):
        """Look for devices that were plugged in or removed since the lists were built."""
        self.audio_processor.refresh_devices()
        self.populate_devices()
        devices = self.devices()
        found = sum(d.is_input for d in devices) + sum(d.is_output for d in devices)
        self.status_label.setText(f"Status: Found {found} devices")

    # --- presets -------------------------------------------------------------------

    def on_controls_changed(self):
        if self.sender() is self.route:
            self.show_matching_builtin_preset()

    def on_reset_defaults(self):
        """Reset all filter settings of the route shown to their default values."""
        self.route.apply_preset({**NEUTRAL, **SESSION_DEFAULTS})

    def on_builtin_preset_chosen(self, index):
        """Apply the built-in preset picked from the list to the route shown."""
        name = self.preset_combo.itemText(index)
        self.route.apply_preset(BUILT_IN[name])
        self.status_label.setText(f"Status: Preset applied: {name}")

    def show_matching_builtin_preset(self):
        """Show in the list which built-in preset the route shown matches, if any."""
        if self.route is None:
            return
        current = self.route.get_preset()
        for index in range(self.preset_combo.count()):
            wanted = BUILT_IN[self.preset_combo.itemText(index)]
            if all(current[name] == value for name, value in wanted.items()):
                self.preset_combo.setCurrentIndex(index)
                return
        self.preset_combo.setCurrentIndex(-1)

    def on_save_preset(self):
        """Save the settings of the route shown to a JSON file."""
        path, _ = QFileDialog.getSaveFileName(self, "Save Preset", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            presets.save(path, self.route.get_preset())
        except presets.PresetError as e:
            self.status_label.setText(f"Status: Could not save preset: {e}")
            return
        self.status_label.setText("Status: Preset saved")

    def on_load_preset(self):
        """Load settings from a JSON file into the route shown."""
        path, _ = QFileDialog.getOpenFileName(self, "Load Preset", "", "JSON Files (*.json)")
        if not path:
            return
        panel = self.route
        stream_settings = panel.stream_settings()
        try:
            notes = panel.apply_preset(presets.load(path))
        except presets.PresetError as e:
            self.status_label.setText(f"Status: Could not load preset: {e}")
            return

        if self.audio_processor.running and panel.stream_settings() != stream_settings:
            notes.append("buffer size and pitch voices take effect at the next start")
        status = "Status: Preset loaded"
        if notes:
            status += f" ({'; '.join(notes)})"
        self.status_label.setText(status)
        self.status_label.setToolTip(status)

    # --- running -------------------------------------------------------------------

    def update_level_meters(self, levels):
        """Pass new levels from the engine to the route they belong to."""
        if levels.route < len(self.routes):
            self.routes[levels.route].update_levels(levels)

    def on_start(self):
        """Start audio processing."""
        for index, panel in enumerate(self.routes):
            if not panel.apply_devices():
                self.status_label.setText(f"Status: Please select both devices for route {index + 1}")
                return
            panel.apply_stream_settings()
        try:
            self.audio_processor.start()
        except AudioStartError as e:
            self.status_label.setText(f"Status: Could not start audio: {e}")
            return

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.set_locked(True)
        self.status_label.setText("Status: Running")

    def on_stop(self):
        """Stop audio processing."""
        self.audio_processor.stop()

        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.set_locked(False)
        for panel in self.routes:
            panel.apply_stream_settings()
            panel.reset_level_meters()
        self.status_label.setText("Status: Stopped")

    def set_locked(self, locked):
        """Lock what cannot change while audio is running: devices, stream settings, the routes."""
        for panel in self.routes:
            panel.set_locked(locked)
        self.add_route_button.setEnabled(not locked)
        self.name_routes()

    def on_audio_error(self, message):
        """Stop after the engine has failed, and say why."""
        self.on_stop()
        self.status_label.setText(f"Status: Stopped after an audio error: {message}")

    # --- settings ------------------------------------------------------------------

    def restore_settings(self):
        """Bring back the devices and settings from the last session, where possible."""
        panel = self.route
        try:
            saved = settings.load(self.settings_path)
            if not saved:
                return
            show_all = saved.get("show_all_devices", False)
            if not isinstance(show_all, bool):
                raise settings.SettingsError("the file is damaged")
            notes = panel.apply_preset(saved.get("preset", {}))
        except (settings.SettingsError, presets.PresetError) as e:
            logger.warning("Could not restore settings from %s: %s", self.settings_path, e)
            self.status_label.setText(f"Status: Your saved settings could not be restored: {e}")
            return

        self.set_show_all_devices(show_all)
        shortcut = saved.get("effects_shortcut")
        if isinstance(shortcut, str) and shortcut:
            wanted = QKeySequence.fromString(shortcut, QKeySequence.SequenceFormat.PortableText)
            try:
                panel.set_shortcut(wanted)
            except HotkeyError as e:
                notes.append(f"the shortcut {shortcut} cannot be used: {e}")
        missing = [
            kind
            for kind, picker in (("input", panel.input), ("output", panel.output))
            if saved.get(f"{kind}_device") is not None and not picker.select(saved[f"{kind}_device"])
        ]
        if missing:
            notes.append(f"the {' and '.join(missing)} device used last time was not found")
        if notes:
            status = f"Status: Stopped ({'; '.join(notes)})"
            self.status_label.setText(status)
            self.status_label.setToolTip(status)

    def save_settings(self):
        """Remember the devices and settings for the next session."""
        panel = self.routes[0]
        data = {
            "version": 1,
            "input_device": panel.input.identity(),
            "output_device": panel.output.identity(),
            "show_all_devices": self.show_all_devices,
            "effects_shortcut": panel.hotkey.sequence.toString(QKeySequence.SequenceFormat.PortableText),
            "preset": panel.get_preset(),
        }
        try:
            settings.save(self.settings_path, data)
        except settings.SettingsError as e:
            # Closing must not fail because of this, and there is nobody left to tell.
            logger.warning("Could not save settings to %s: %s", self.settings_path, e)

    def closeEvent(self, event):
        """Handle window close event."""
        if not self.closed:
            self.closed = True
            self.save_settings()
        for panel in self.routes:
            panel.close_shortcut()
        self.audio_processor.shut_down()
        event.accept()


def application_icon():
    """The icon for the windows and the taskbar."""
    icon = QIcon()
    for path in (resources.ICON_ICO, resources.ICON_PNG):
        if path.exists():
            icon.addFile(str(path))
    return icon


def identify_to_windows():
    """Tell Windows that this is an application of its own.

    Run from source, the process is python.exe, and the taskbar would otherwise show the
    Python icon and group the window with other Python programs.
    """
    if sys.platform != "win32":
        return
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OpenVChange")


def main():
    """Application entry point."""
    identify_to_windows()
    app = QApplication(sys.argv)
    app.setApplicationName("OpenVChange")
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setWindowIcon(application_icon())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
