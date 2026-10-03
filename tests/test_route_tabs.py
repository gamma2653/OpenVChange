"""Routes in the window: a tab each, with devices, effects, meters, and settings of its own."""

import json

import pytest
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QFileDialog, QTabBar

from openvchange.__main__ import MainWindow
from openvchange.audio import Levels
from tests.fakes import WASAPI, device
from tests.helpers import sine, to_pcm

MIC, LINE_IN, SPEAKERS, CABLE, MATRIX = range(5)


@pytest.fixture(autouse=True)
def devices(fake_pyaudio):
    fake_pyaudio.devices = [
        device("Microphone", WASAPI, inputs=1, outputs=0),
        device("Line In", WASAPI, inputs=2, outputs=0),
        device("Speakers", WASAPI, inputs=0, outputs=2),
        device("Cable", WASAPI, inputs=0, outputs=2),
        device("Matrix", WASAPI, inputs=0, outputs=8, all_channels_only=True),
    ]


@pytest.fixture
def window(qapp):
    w = MainWindow()
    yield w
    w.close()


def items(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def tab_titles(window) -> list[str]:
    return [window.tabs.tabText(i) for i in range(window.tabs.count())]


def close_button(window, index):
    bar = window.tabs.tabBar()
    return bar.tabButton(index, QTabBar.ButtonPosition.RightSide) or bar.tabButton(
        index, QTabBar.ButtonPosition.LeftSide
    )


def wiring(window) -> list[tuple[str, str]]:
    return [(panel.input.device.currentText(), panel.output.device.currentText()) for panel in window.routes]


def keys(text: str) -> QKeySequence:
    return QKeySequence.fromString(text, QKeySequence.SequenceFormat.PortableText)


# --- tabs ---------------------------------------------------------------------------


def test_the_window_starts_with_one_route_tab_holding_the_three_tabs(window):
    assert tab_titles(window) == ["Route 1"]
    assert window.route is window.routes[0]
    assert [window.route.tabs.tabText(i) for i in range(window.route.tabs.count())] == [
        "Main",
        "Dynamics",
        "Advanced Settings",
    ]
    assert wiring(window) == [("Microphone", "Speakers")]
    assert not close_button(window, 0).isVisible()  # the last route cannot be removed


def test_adding_a_route_adds_a_tab_and_shows_it(window):
    window.add_route_button.click()
    window.add_route_button.click()

    assert tab_titles(window) == ["Route 1", "Route 2", "Route 3"]
    assert window.tabs.currentIndex() == 2
    assert window.route is window.routes[2]
    assert len(window.audio_processor.routes) == 3
    assert window.routes[2].route is window.audio_processor.routes[2]
    assert all(close_button(window, i).isVisibleTo(window.tabs) for i in range(3))


def test_a_new_route_takes_the_same_input_to_an_output_not_in_use(window):
    window.route.input.device.setCurrentIndex(1)
    window.route.input.channel.setCurrentIndex(2)

    window.add_route_button.click()
    window.add_route_button.click()

    assert wiring(window) == [("Line In", "Speakers"), ("Line In", "Cable"), ("Line In", "Matrix")]
    assert window.routes[1].input.channel.currentText() == "Ch 2"


def test_closing_a_tab_removes_its_route_and_renumbers_the_rest(window):
    for _ in range(2):
        window.add_route_button.click()
    window.tabs.setCurrentIndex(1)
    kept = [window.audio_processor.routes[0], window.audio_processor.routes[2]]
    gone = window.routes[1]

    window.tabs.tabCloseRequested.emit(1)

    assert tab_titles(window) == ["Route 1", "Route 2"]
    assert window.audio_processor.routes == kept
    assert [panel.route for panel in window.routes] == kept
    assert gone not in window.routes
    assert window.route.route in kept


def test_the_last_route_cannot_be_closed(window):
    window.tabs.tabCloseRequested.emit(0)
    assert tab_titles(window) == ["Route 1"]
    assert len(window.audio_processor.routes) == 1


def test_channels_of_the_selected_device_are_offered(window):
    panel = window.route

    # One channel leaves nothing to choose.
    assert items(panel.input.channel) == ["All"]
    assert not panel.input.channel.isEnabled()
    assert items(panel.output.channel) == ["All", "Ch 1", "Ch 2"]

    panel.input.device.setCurrentIndex(1)
    panel.output.device.setCurrentIndex(2)

    assert items(panel.input.channel) == ["All", "Ch 1", "Ch 2"]
    assert panel.input.channel.isEnabled()
    assert items(panel.output.channel) == ["All"] + [f"Ch {n}" for n in range(1, 9)]


def test_a_chosen_channel_is_kept_when_the_next_device_has_it_too(window):
    output = window.route.output
    output.channel.setCurrentIndex(2)

    output.device.setCurrentIndex(2)
    assert output.channel.currentText() == "Ch 2"

    output.channel.setCurrentIndex(8)
    output.device.setCurrentIndex(0)
    assert output.channel.currentText() == "All"


def test_show_all_devices_is_one_setting_for_every_route(window, fake_pyaudio):
    fake_pyaudio.devices = [device("Old Mic", 0, inputs=1, outputs=0), *fake_pyaudio.devices]
    window.on_refresh_devices()
    window.add_route_button.click()

    window.routes[1].show_all_devices_checkbox.setChecked(True)

    assert window.show_all_devices
    assert window.routes[0].show_all_devices_checkbox.isChecked()
    assert items(window.routes[0].input.device) == [
        "Old Mic [MME]",
        "Microphone [Windows WASAPI]",
        "Line In [Windows WASAPI]",
    ]
    assert items(window.routes[1].input.device) == items(window.routes[0].input.device)


def test_refresh_from_any_route_keeps_the_devices_of_every_route(window, fake_pyaudio):
    window.add_route_button.click()
    window.routes[1].input.device.setCurrentIndex(1)
    fake_pyaudio.devices = [device("Headset", WASAPI, inputs=1, outputs=2), *fake_pyaudio.devices]

    window.routes[1].refresh_devices_button.click()

    assert wiring(window) == [("Microphone", "Speakers"), ("Line In", "Cable")]
    assert window.routes[1].output.device.currentData() == CABLE + 1
    assert window.status_label.text() == "Status: Found 7 devices"


# --- effects and settings per route -------------------------------------------------


def test_each_route_has_controls_and_effects_of_its_own(window):
    window.route.gain_slider.setValue(6)
    window.route.compressor_checkbox.setChecked(True)

    window.add_route_button.click()
    window.route.pitch_slider.setValue(-30)
    window.route.compressor_checkbox.setChecked(False)

    first, second = window.routes
    assert first.gain_slider.value() == second.gain_slider.value() == 6  # copied when added
    assert first.compressor_checkbox.isChecked() and not second.compressor_checkbox.isChecked()
    assert first.pitch_slider.value() == 0 and second.pitch_slider.value() == -30
    assert first.effects.gain_target == second.effects.gain_target == pytest.approx(10 ** (6 / 20))
    assert first.effects.compressor_enabled and not second.effects.compressor_enabled
    assert first.effects.pitch_semitones == 0.0 and second.effects.pitch_semitones == -3.0
    assert first.effects is window.audio_processor.routes[0].effects
    assert second.effects is window.audio_processor.routes[1].effects


def test_a_new_route_starts_as_a_copy_of_the_route_shown(window):
    window.route.apply_preset({"gain": 12, "delay": 300, "high_pass_enabled": True, "effects_enabled": False})
    window.route.buffer_size_combo.setCurrentIndex(1)
    window.route.pitch_voices_spin.setValue(6)

    window.add_route_button.click()

    new = window.audio_processor.routes[1]
    assert new.effects.gain_target == pytest.approx(10 ** (12 / 20))
    assert new.effects.delay_ms == 300
    assert new.effects.high_pass_enabled
    assert not new.effects_enabled
    assert new.chunk_size == 256
    assert new.effects.pitch_num_voices == 6
    assert window.route.buffer_size_combo.currentData() == 256


def test_advanced_settings_belong_to_each_route(window):
    window.add_route_button.click()
    window.route.buffer_size_combo.setCurrentIndex(5)
    window.route.pitch_voices_spin.setValue(2)

    first, second = window.audio_processor.routes
    assert first.chunk_size == 1024 and second.chunk_size == 4096
    assert first.effects.pitch_num_voices == 4 and second.effects.pitch_num_voices == 2
    assert window.routes[0].buffer_size_combo.currentData() == 1024


def test_each_route_can_have_a_shortcut_of_its_own(window):
    window.add_route_button.click()
    window.routes[0].hotkey_edit.setKeySequence(keys("Ctrl+Alt+1"))
    window.routes[0].hotkey_edit.editingFinished.emit()
    window.routes[1].hotkey_edit.setKeySequence(keys("Ctrl+Alt+2"))
    window.routes[1].hotkey_edit.editingFinished.emit()

    assert window.routes[0].hotkey.hotkey_id != window.routes[1].hotkey.hotkey_id
    window.routes[1].hotkey.pressed.emit()

    first, second = window.audio_processor.routes
    assert first.effects_enabled and not second.effects_enabled
    assert window.routes[0].effects_checkbox.isChecked()
    assert not window.routes[1].effects_checkbox.isChecked()


def test_a_shortcut_another_route_uses_is_refused(window):
    window.routes[0].set_shortcut(keys("Ctrl+Alt+1"))
    window.add_route_button.click()

    window.route.hotkey_edit.setKeySequence(keys("Ctrl+Alt+1"))
    window.route.hotkey_edit.editingFinished.emit()

    assert window.status_label.text() == "Status: Ctrl+Alt+1 cannot be used: route 1 already uses it"
    assert window.route.hotkey.sequence.isEmpty()
    assert window.route.hotkey_edit.keySequence().isEmpty()


def test_closing_a_tab_gives_its_shortcut_back(window):
    window.add_route_button.click()
    window.route.set_shortcut(keys("Ctrl+Alt+2"))
    backend = window.route.hotkey.backend
    assert backend.registered

    window.tabs.tabCloseRequested.emit(1)

    assert backend.registered == {}


def test_presets_act_on_the_route_shown(window, tmp_path, monkeypatch):
    path = tmp_path / "preset.json"
    path.write_text(json.dumps({"gain": 9, "pitch": 40}))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    window.add_route_button.click()

    window.on_load_preset()
    assert window.routes[0].gain_slider.value() == 0
    assert window.audio_processor.routes[1].effects.pitch_semitones == 4.0

    window.tabs.setCurrentIndex(0)
    window.on_reset_defaults()
    window.preset_combo.setCurrentIndex(window.preset_combo.findText("Chipmunk"))
    window.preset_combo.activated.emit(window.preset_combo.currentIndex())
    assert window.routes[0].pitch_slider.value() > 0
    assert window.routes[1].pitch_slider.value() == 40


def test_the_preset_list_follows_the_route_shown(window):
    window.add_route_button.click()
    window.route.pitch_slider.setValue(40)
    assert window.preset_combo.currentIndex() == -1

    window.tabs.setCurrentIndex(0)
    assert window.preset_combo.currentText() == "Neutral"

    window.routes[1].pitch_slider.setValue(0)  # a change on a route not shown
    assert window.preset_combo.currentText() == "Neutral"
    window.tabs.setCurrentIndex(1)
    assert window.preset_combo.currentText() == "Neutral"


def test_meters_go_to_the_route_the_levels_belong_to(window):
    window.add_route_button.click()
    quiet = Levels(input_db=-30.0, output_db=-30.0, input_clipped=False, output_clipped=False, seconds=0.03, route=0)
    loud = Levels(input_db=-3.0, output_db=-3.0, input_clipped=False, output_clipped=False, seconds=0.03, route=1)

    window.audio_processor.levels_changed.emit(quiet)
    window.audio_processor.levels_changed.emit(loud)

    assert window.routes[0].input_meter.level_db == pytest.approx(-30.0)
    assert window.routes[1].input_meter.level_db == pytest.approx(-3.0)


# --- start and stop -----------------------------------------------------------------


def test_start_passes_every_route_to_the_engine(window):
    window.add_route_button.click()
    window.route.input.device.setCurrentIndex(1)
    window.route.input.channel.setCurrentIndex(2)
    window.route.output.channel.setCurrentIndex(1)
    window.route.buffer_size_combo.setCurrentIndex(1)

    window.on_start()

    engine = window.audio_processor
    assert window.status_label.text() == "Status: Running"
    assert [(r.input_device, r.input_channel) for r in engine.routes] == [(MIC, None), (LINE_IN, 1)]
    assert [(r.output_device, r.output_channel) for r in engine.routes] == [(SPEAKERS, None), (CABLE, 0)]
    assert len(engine.streams) == 4
    inputs = {s.kwargs["input_device_index"]: s for s in engine.streams if s.kwargs["input"]}
    outputs = {s.kwargs["output_device_index"]: s for s in engine.streams if s.kwargs["output"]}
    assert inputs[LINE_IN].kwargs["channels"] == 2
    assert inputs[LINE_IN].kwargs["frames_per_buffer"] == 256
    assert outputs[CABLE].kwargs["frames_per_buffer"] == 256
    assert inputs[MIC].kwargs["frames_per_buffer"] == 1024


def test_routes_are_locked_while_running_but_their_effects_can_be_changed(window):
    window.add_route_button.click()

    window.on_start()

    locked = [window.add_route_button]
    for panel in window.routes:
        locked += [
            panel.input.device,
            panel.input.channel,
            panel.output.device,
            panel.output.channel,
            panel.show_all_devices_checkbox,
            panel.refresh_devices_button,
            panel.buffer_size_combo,
            panel.pitch_voices_spin,
        ]
    assert not any(widget.isEnabled() for widget in locked)
    assert not any(close_button(window, i).isEnabled() for i in range(2))

    window.tabs.setCurrentIndex(0)
    window.route.gain_slider.setValue(-6)
    assert window.audio_processor.routes[0].effects.gain_target == pytest.approx(10 ** (-6 / 20))

    window.on_stop()
    mono = {panel.input.channel for panel in window.routes}  # the microphone has one channel
    assert all(widget.isEnabled() for widget in locked if widget not in mono)
    assert not any(widget.isEnabled() for widget in mono)
    assert all(close_button(window, i).isEnabled() for i in range(2))


def test_start_names_the_route_that_lacks_a_device(qapp, fake_pyaudio):
    w = MainWindow()
    w.add_route_button.click()
    fake_pyaudio.devices = [device("Microphone", WASAPI, inputs=1, outputs=0)]
    w.on_refresh_devices()

    w.on_start()

    assert w.status_label.text() == "Status: Please select both devices for route 1"
    assert not w.audio_processor.running
    w.close()


def test_audio_of_two_routes_reaches_an_output_through_the_window(window):
    window.add_route_button.click()
    window.route.input.device.setCurrentIndex(1)
    window.route.output.device.setCurrentIndex(0)
    window.on_start()
    engine = window.audio_processor
    microphone, line_in = (
        next(s for s in engine.streams if s.kwargs["input_device_index"] == d) for d in (MIC, LINE_IN)
    )
    speakers = next(s for s in engine.streams if s.kwargs["output_device_index"] == SPEAKERS)
    pcm = to_pcm(sine(300.0, 0.25, seconds=0.5))

    heard = b""
    for start in range(0, 8 * 1024, 1024):
        microphone.feed(pcm[start : start + 1024].tobytes())
        line_in.feed(pcm[start : start + 1024].tobytes())
        heard += speakers.pull(1024)

    assert any(heard)
    assert all(panel.input_meter.level_db == pytest.approx(-12.04, abs=0.05) for panel in window.routes)


def test_a_failure_while_several_streams_run_stops_them_all(window):
    window.add_route_button.click()
    window.on_start()
    engine = window.audio_processor
    streams = list(engine.streams)

    def broken(data):
        raise RuntimeError("filter blew up")

    engine.routes[0].effects.process = broken
    next(s for s in streams if s.kwargs["input"]).feed(b"\x01\x02" * 1024)

    assert window.status_label.text() == "Status: Stopped after an audio error: filter blew up"
    assert all(s.closed for s in streams)
    assert window.add_route_button.isEnabled()
