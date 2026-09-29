"""The main window: device lists, controls, presets, and start/stop."""

import json

import pytest
from PySide6.QtWidgets import QFileDialog

from openvchange.__main__ import MainWindow
from tests.fakes import FakePyAudio, device


@pytest.fixture
def window(qapp):
    w = MainWindow()
    yield w
    w.close()


def combo_items(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


# A preset saved by an earlier version: no "effects_enabled" key, values in slider units.
LEGACY_PRESET = {
    "gain": 5,
    "bass": 0,
    "treble": 0,
    "pitch": -23,
    "delay": 586,
    "high_pass_enabled": False,
    "high_pass_freq": 80,
    "low_pass_enabled": False,
    "low_pass_freq": 16000,
    "expander_enabled": False,
    "expander_threshold": 1,
    "expander_ratio": 20,
    "expander_attack": 5,
    "expander_release": 100,
    "compressor_enabled": True,
    "compressor_threshold": -10,
    "compressor_ratio": 114,
    "compressor_attack": 27,
    "compressor_release": 229,
    "compressor_makeup": 1,
    "deesser_enabled": True,
    "deesser_threshold": -2,
    "deesser_reduction": 12,
    "buffer_size": 4096,
    "pitch_voices": 6,
}


# --- devices -------------------------------------------------------------------


def test_device_lists_show_only_wasapi_devices_by_default(window):
    assert combo_items(window.input_combo) == ["Microphone (USB Audio)"]
    assert combo_items(window.output_combo) == ["Speakers (Realtek)", "CABLE Input (VB-Audio Virtual Cable)"]


def test_show_all_devices_lists_every_host_api(window):
    window.show_all_devices_checkbox.setChecked(True)
    assert combo_items(window.input_combo) == ["Microphone (MME)", "Microphone (USB Audio)"]
    assert len(combo_items(window.output_combo)) == 3


def test_device_lists_fall_back_to_everything_without_wasapi(qapp):
    FakePyAudio.host_apis = [{"index": 0, "name": "ALSA"}]
    FakePyAudio.devices = [device("Mic", 0, inputs=1, outputs=0), device("Out", 0, inputs=0, outputs=2)]
    w = MainWindow()
    assert combo_items(w.input_combo) == ["Mic"]
    assert combo_items(w.output_combo) == ["Out"]
    w.close()


def test_device_entries_carry_the_portaudio_index(window):
    assert window.input_combo.currentData() == 2
    assert window.output_combo.itemData(1) == 4


# --- controls ------------------------------------------------------------------


def test_sliders_drive_the_engine(window):
    engine = window.audio_processor

    window.gain_slider.setValue(6)
    window.bass_slider.setValue(-4)
    window.treble_slider.setValue(3)
    window.pitch_slider.setValue(-25)
    window.delay_slider.setValue(120)
    window.hp_checkbox.setChecked(True)
    window.hp_slider.setValue(150)
    window.lp_checkbox.setChecked(True)
    window.lp_slider.setValue(9000)

    assert engine.gain_target == pytest.approx(10 ** (6 / 20))
    assert engine.bass_gain == -4
    assert engine.treble_gain == 3
    assert engine.pitch_semitones == pytest.approx(-2.5)
    assert engine.delay_ms == 120
    assert engine.high_pass_enabled and engine.low_cut == 150
    assert engine.low_pass_enabled and engine.high_cut == 9000
    assert window.pitch_label.text() == "-2.5 st"


def test_dynamics_controls_drive_the_engine(window):
    engine = window.audio_processor

    window.expander_checkbox.setChecked(True)
    window.expander_threshold_slider.setValue(5)
    window.expander_ratio_slider.setValue(45)
    window.compressor_checkbox.setChecked(True)
    window.compressor_threshold_slider.setValue(-24)
    window.compressor_ratio_slider.setValue(80)
    window.compressor_makeup_slider.setValue(6)
    window.deesser_checkbox.setChecked(True)
    window.deesser_threshold_slider.setValue(-30)
    window.deesser_reduction_slider.setValue(9)

    assert engine.expander_enabled
    assert engine.expander_threshold == pytest.approx(0.05)
    assert engine.expander_ratio == pytest.approx(4.5)
    assert engine.compressor_enabled
    assert engine.compressor_threshold_db == -24
    assert engine.compressor_ratio == pytest.approx(8.0)
    assert engine.compressor_makeup_db == 6
    assert engine.deesser_enabled
    assert engine.deesser_threshold_db == -30
    assert engine.deesser_reduction_db == 9


def test_effect_sliders_are_disabled_until_their_effect_is_enabled(window):
    assert not window.hp_slider.isEnabled()
    assert not window.compressor_ratio_slider.isEnabled()
    window.hp_checkbox.setChecked(True)
    window.compressor_checkbox.setChecked(True)
    assert window.hp_slider.isEnabled()
    assert window.compressor_ratio_slider.isEnabled()


def test_effects_checkbox_bypasses_the_chain(window):
    window.effects_checkbox.setChecked(False)
    assert not window.audio_processor.effects_enabled
    assert window.effects_checkbox.text() == "Enable Effects"


def test_reset_restores_every_default(window):
    defaults = window.get_preset()
    window.apply_preset(LEGACY_PRESET)
    window.effects_checkbox.setChecked(False)
    assert window.get_preset() != defaults

    window.on_reset_defaults()

    assert window.get_preset() == defaults
    assert window.audio_processor.effects_enabled


# --- presets -------------------------------------------------------------------


def test_preset_round_trip(window):
    window.apply_preset(LEGACY_PRESET)
    saved = window.get_preset()

    window.on_reset_defaults()
    window.apply_preset(saved)

    assert window.get_preset() == saved


def test_legacy_preset_loads_and_reaches_the_engine(window):
    window.apply_preset(LEGACY_PRESET)
    engine = window.audio_processor

    assert {k: v for k, v in window.get_preset().items() if k != "effects_enabled"} == LEGACY_PRESET
    assert window.effects_checkbox.isChecked()
    assert engine.pitch_semitones == pytest.approx(-2.3)
    assert engine.delay_ms == 586
    assert engine.compressor_ratio == pytest.approx(11.4)
    assert engine.deesser_enabled
    assert engine.chunk_size == 4096
    assert engine.pitch_num_voices == 6


def test_partial_preset_changes_only_what_it_names(window):
    window.gain_slider.setValue(7)
    window.apply_preset({"pitch": 40})
    assert window.gain_slider.value() == 7
    assert window.pitch_slider.value() == 40


def test_save_and_load_preset_files(window, tmp_path, monkeypatch):
    path = tmp_path / "voice.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))

    window.apply_preset(LEGACY_PRESET)
    window.on_save_preset()
    assert json.loads(path.read_text()) == window.get_preset()
    assert window.status_label.text() == "Status: Preset saved"

    window.on_reset_defaults()
    window.on_load_preset()
    assert window.pitch_slider.value() == -23
    assert window.status_label.text() == "Status: Preset loaded"


def test_loading_a_file_that_is_not_json_reports_failure(window, tmp_path, monkeypatch):
    path = tmp_path / "broken.json"
    path.write_text("{ not json")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))

    window.on_load_preset()

    assert window.status_label.text() == "Status: Failed to load preset"


def test_cancelling_a_preset_dialog_changes_nothing(window, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    window.on_load_preset()
    window.on_save_preset()
    assert window.status_label.text() == "Status: Stopped"


# --- start and stop ------------------------------------------------------------


def test_start_and_stop_lock_and_unlock_the_stream_settings(window):
    window.on_start()

    assert window.audio_processor.running
    assert window.status_label.text() == "Status: Running"
    assert not window.start_button.isEnabled()
    assert window.stop_button.isEnabled()
    for widget in (window.input_combo, window.output_combo, window.buffer_size_combo, window.pitch_voices_spin):
        assert not widget.isEnabled()

    window.on_stop()

    assert not window.audio_processor.running
    assert window.status_label.text() == "Status: Stopped"
    assert window.start_button.isEnabled()
    assert not window.stop_button.isEnabled()
    for widget in (window.input_combo, window.output_combo, window.buffer_size_combo, window.pitch_voices_spin):
        assert widget.isEnabled()


def test_start_uses_the_selected_devices(window):
    window.output_combo.setCurrentIndex(1)
    window.on_start()
    stream = window.audio_processor.pa.streams[0]
    assert stream.kwargs["input_device_index"] == 2
    assert stream.kwargs["output_device_index"] == 4
    window.on_stop()


def test_start_without_devices_asks_for_them(qapp):
    FakePyAudio.devices = []
    w = MainWindow()
    w.on_start()
    assert w.status_label.text() == "Status: Please select both devices"
    assert not w.audio_processor.running
    w.close()


def test_level_meter_follows_the_engine(window):
    window.audio_processor.level_changed.emit(0.2)
    assert window.level_bar.value() == 60
    window.audio_processor.level_changed.emit(5.0)
    assert window.level_bar.value() == 100


def test_closing_the_window_stops_audio(window):
    window.on_start()
    engine = window.audio_processor
    stream = engine.pa.streams[0]

    window.close()

    assert not engine.running
    assert stream.closed
    assert engine.pa.terminated
