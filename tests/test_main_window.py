"""The main window: device lists, controls, presets, and start/stop."""

import json

import pytest
from PySide6.QtWidgets import QFileDialog

from openvchange.__main__ import MainWindow
from openvchange.audio import Levels
from tests.fakes import WASAPI, FakePyAudio, device
from tests.helpers import sine, to_pcm


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


def test_show_all_devices_lists_every_host_api_and_names_it(window):
    window.show_all_devices_checkbox.setChecked(True)
    assert combo_items(window.input_combo) == [
        "Microphone (MME) [MME]",
        "Microphone (USB Audio) [Windows WASAPI]",
    ]
    assert len(combo_items(window.output_combo)) == 3


def test_changing_the_filter_keeps_the_selected_device(window):
    window.output_combo.setCurrentIndex(1)
    assert window.output_combo.currentText() == "CABLE Input (VB-Audio Virtual Cable)"

    window.show_all_devices_checkbox.setChecked(True)
    assert window.output_combo.currentText() == "CABLE Input (VB-Audio Virtual Cable) [Windows WASAPI]"
    assert window.output_combo.currentData() == 4

    window.show_all_devices_checkbox.setChecked(False)
    assert window.output_combo.currentText() == "CABLE Input (VB-Audio Virtual Cable)"


def test_the_window_uses_the_instance_the_engine_uses(window):
    assert len(FakePyAudio.instances) == 1
    window.show_all_devices_checkbox.setChecked(True)
    window.on_start()
    window.on_stop()
    assert len(FakePyAudio.instances) == 1


def plug_in_headset() -> None:
    """A headset appears, listed ahead of the devices that were already there."""
    FakePyAudio.devices = [
        device("Headset Microphone", WASAPI, inputs=1, outputs=0),
        device("Headset Earphone", WASAPI, inputs=0, outputs=2),
        *FakePyAudio.devices,
    ]


def test_a_device_plugged_in_later_is_not_listed_until_refresh(window):
    plug_in_headset()
    window.show_all_devices_checkbox.setChecked(True)
    window.show_all_devices_checkbox.setChecked(False)
    assert combo_items(window.input_combo) == ["Microphone (USB Audio)"]


def test_refresh_finds_a_device_plugged_in_later(window):
    plug_in_headset()

    window.refresh_devices_button.click()

    assert combo_items(window.input_combo) == ["Headset Microphone", "Microphone (USB Audio)"]
    assert combo_items(window.output_combo) == [
        "Headset Earphone",
        "Speakers (Realtek)",
        "CABLE Input (VB-Audio Virtual Cable)",
    ]
    assert window.status_label.text() == "Status: Found 5 devices"


def test_refresh_keeps_the_selection_even_though_its_index_moved(window):
    window.output_combo.setCurrentIndex(1)
    assert window.output_combo.currentData() == 4
    plug_in_headset()

    window.refresh_devices_button.click()

    assert window.input_combo.currentText() == "Microphone (USB Audio)"
    assert window.output_combo.currentText() == "CABLE Input (VB-Audio Virtual Cable)"
    assert window.output_combo.currentData() == 6


def test_start_after_refresh_opens_the_device_that_is_shown(window):
    window.output_combo.setCurrentIndex(1)
    plug_in_headset()
    window.refresh_devices_button.click()

    window.on_start()

    engine = window.audio_processor
    stream = engine.pa.streams[0]
    assert engine.pa.get_device_info_by_index(stream.kwargs["input_device_index"])["name"] == "Microphone (USB Audio)"
    assert engine.pa.get_device_info_by_index(stream.kwargs["output_device_index"])["name"] == (
        "CABLE Input (VB-Audio Virtual Cable)"
    )


def test_refresh_falls_back_to_the_first_device_when_the_selected_one_is_gone(window):
    window.output_combo.setCurrentIndex(1)
    FakePyAudio.devices = [d for d in FakePyAudio.devices if "CABLE" not in d["name"]]

    window.refresh_devices_button.click()

    assert combo_items(window.output_combo) == ["Speakers (Realtek)"]
    assert window.output_combo.currentText() == "Speakers (Realtek)"


def test_devices_cannot_be_changed_or_refreshed_while_running(window):
    window.on_start()
    assert not window.refresh_devices_button.isEnabled()
    assert not window.show_all_devices_checkbox.isEnabled()

    window.on_stop()
    assert window.refresh_devices_button.isEnabled()
    assert window.show_all_devices_checkbox.isEnabled()


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
    engine = window.audio_processor.effects

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
    engine = window.audio_processor.effects

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
    engine = window.audio_processor.effects

    assert {k: v for k, v in window.get_preset().items() if k in LEGACY_PRESET} == LEGACY_PRESET
    assert window.effects_checkbox.isChecked()
    assert engine.pitch_semitones == pytest.approx(-2.3)
    assert engine.delay_ms == 586
    assert engine.compressor_ratio == pytest.approx(11.4)
    assert engine.deesser_enabled
    assert window.audio_processor.chunk_size == 4096
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


def load_text(window, tmp_path, monkeypatch, text: str) -> str:
    """Load a preset file with the given content and return the status line."""
    path = tmp_path / "preset.json"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(path), ""))
    window.on_load_preset()
    return window.status_label.text()


def test_loading_a_file_that_is_not_json_reports_failure(window, tmp_path, monkeypatch):
    status = load_text(window, tmp_path, monkeypatch, '{\n  "gain": 3,\n  not json')
    assert status == "Status: Could not load preset: the file is not valid JSON (line 3)"


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("[1, 2, 3]", "the file does not contain a preset"),
        ('"gain"', "the file does not contain a preset"),
        ('{"gain": "loud"}', "'gain' must be a whole number, not the text \"loud\""),
        ('{"gain": 2.5}', "'gain' must be a whole number, not 2.5"),
        ('{"gain": true}', "'gain' must be a whole number, not true"),
        ('{"gain": null}', "'gain' must be a whole number, not empty"),
        ('{"pitch": [1]}', "'pitch' must be a whole number, not a list"),
        ('{"buffer_size": "big"}', "'buffer_size' must be a whole number, not the text \"big\""),
        ('{"compressor_enabled": 1}', "'compressor_enabled' must be true or false, not 1"),
        ('{"effects_enabled": "yes"}', "'effects_enabled' must be true or false, not the text \"yes\""),
    ],
)
def test_preset_with_a_wrong_value_is_refused_and_nothing_is_applied(window, tmp_path, monkeypatch, text, problem):
    before = window.get_preset()
    # A valid setting alongside the bad one must not be applied either.
    text = text if not text.startswith("{") else '{"treble": 9, ' + text[1:]

    status = load_text(window, tmp_path, monkeypatch, text)

    assert status == f"Status: Could not load preset: {problem}"
    assert window.get_preset() == before


def test_out_of_range_values_are_brought_into_range_and_mentioned(window, tmp_path, monkeypatch):
    status = load_text(window, tmp_path, monkeypatch, '{"gain": 500, "pitch": -999, "treble": 4}')

    assert window.gain_slider.value() == 100
    assert window.pitch_slider.value() == -120
    assert window.treble_slider.value() == 4
    assert status == (
        "Status: Preset loaded ('gain' was changed from 500 to 100 to fit its range; "
        "'pitch' was changed from -999 to -120 to fit its range)"
    )


def test_unknown_buffer_size_is_left_unchanged_and_mentioned(window, tmp_path, monkeypatch):
    status = load_text(window, tmp_path, monkeypatch, '{"buffer_size": 1000, "gain": 2}')

    assert window.buffer_size_combo.currentData() == 1024
    assert window.gain_slider.value() == 2
    assert "'buffer_size' was left unchanged: 1000 is not one of 128, 256, 512, 1024, 2048, 4096" in status


def test_whole_numbers_written_as_decimals_are_accepted(window, tmp_path, monkeypatch):
    status = load_text(window, tmp_path, monkeypatch, '{"gain": 6.0}')
    assert status == "Status: Preset loaded"
    assert window.gain_slider.value() == 6


def test_settings_from_a_newer_version_are_ignored(window, tmp_path, monkeypatch):
    status = load_text(window, tmp_path, monkeypatch, '{"gain": 3, "reverb_size": 40, "future": {"a": 1}}')
    assert status == "Status: Preset loaded"
    assert window.gain_slider.value() == 3


def test_loading_a_missing_file_reports_failure(window, tmp_path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(tmp_path / "gone.json"), ""))
    window.on_load_preset()
    assert window.status_label.text() == (
        "Status: Could not load preset: the file could not be read (no such file or directory)"
    )


def test_saving_to_a_place_that_cannot_be_written_reports_failure(window, tmp_path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(tmp_path / "missing" / "p.json"), ""))
    window.on_save_preset()
    assert window.status_label.text() == (
        "Status: Could not save preset: the file could not be written (no such file or directory)"
    )


def test_preset_loaded_while_running_does_not_touch_the_running_stream(window, tmp_path, monkeypatch):
    window.on_start()
    engine = window.audio_processor
    voices_before = engine.effects.pitch_read_pos

    status = load_text(window, tmp_path, monkeypatch, json.dumps(LEGACY_PRESET))

    # The controls show what the preset asks for...
    assert window.buffer_size_combo.currentData() == 4096
    assert window.pitch_voices_spin.value() == 6
    # ...but the running engine keeps what it started with.
    assert engine.chunk_size == 1024
    assert engine.effects.pitch_num_voices == 4
    assert engine.effects.pitch_read_pos is voices_before
    assert status == "Status: Preset loaded (buffer size and pitch voices take effect at the next start)"
    # Everything else applies at once.
    assert engine.effects.pitch_semitones == pytest.approx(-2.3)


def test_stream_settings_from_a_preset_take_effect_at_the_next_start(window, tmp_path, monkeypatch):
    window.on_start()
    load_text(window, tmp_path, monkeypatch, json.dumps(LEGACY_PRESET))

    window.on_stop()
    assert window.audio_processor.chunk_size == 4096
    assert window.effects.pitch_num_voices == 6

    window.on_start()
    assert window.audio_processor.pa.streams[-1].kwargs["frames_per_buffer"] == 4096
    assert len(window.effects.pitch_read_pos) == 6


def test_preset_loaded_while_running_says_nothing_if_stream_settings_are_unchanged(window, tmp_path, monkeypatch):
    window.on_start()
    status = load_text(window, tmp_path, monkeypatch, '{"gain": 4, "buffer_size": 1024, "pitch_voices": 4}')
    assert status == "Status: Preset loaded"


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


def test_failed_start_is_shown_and_leaves_the_window_ready_to_retry(window):
    FakePyAudio.open_error = OSError(-9996, "Invalid input device (no default output device)")

    window.on_start()

    assert window.status_label.text() == (
        "Status: Could not start audio: Invalid input device (no default output device)"
    )
    assert not window.audio_processor.running
    assert window.start_button.isEnabled()
    assert not window.stop_button.isEnabled()
    assert window.input_combo.isEnabled()

    FakePyAudio.open_error = None
    window.on_start()
    assert window.status_label.text() == "Status: Running"


def test_processing_failure_stops_the_stream_and_is_shown(window):
    window.on_start()
    stream = window.audio_processor.pa.streams[0]

    def broken(data):
        raise RuntimeError("filter blew up")

    window.audio_processor.effects.process = broken
    out = stream.feed(b"\x01\x02" * 1024)

    assert out == b"\x00" * 2048
    assert window.status_label.text() == "Status: Stopped after an audio error: filter blew up"
    assert not window.audio_processor.running
    assert stream.closed
    assert window.start_button.isEnabled()
    assert not window.stop_button.isEnabled()


def test_meters_follow_the_engine(window):
    window.audio_processor.levels_changed.emit(
        Levels(input_db=-12.4, output_db=-3.0, input_clipped=False, output_clipped=True, seconds=0.03)
    )

    assert window.input_meter.level_db == pytest.approx(-12.4)
    assert window.output_meter.level_db == pytest.approx(-3.0)
    assert not window.input_meter.clipped
    assert window.output_meter.clipped
    assert window.input_level_label.text() == "-12 dB"
    assert window.output_level_label.text() == "-3 dB"


def test_meters_show_silence_when_nothing_is_running(window):
    assert window.input_level_label.text() == "< -60 dB"
    window.on_start()
    window.audio_processor.levels_changed.emit(
        Levels(input_db=-5.0, output_db=-1.0, input_clipped=True, output_clipped=True, seconds=0.03)
    )

    window.on_stop()

    for meter in (window.input_meter, window.output_meter):
        assert meter.level_db == meter.FLOOR_DB
        assert meter.peak_db == meter.FLOOR_DB
        assert not meter.clipped
    assert window.input_level_label.text() == "< -60 dB"
    assert window.output_level_label.text() == "< -60 dB"


def test_meters_are_driven_by_real_audio(window):
    window.gain_slider.setValue(20)
    window.on_start()
    stream = window.audio_processor.pa.streams[0]
    pcm = to_pcm(sine(1000.0, 0.5, seconds=0.2))

    for start in range(0, 8 * 1024, 1024):
        stream.feed(pcm[start : start + 1024].tobytes())

    assert window.input_meter.level_db == pytest.approx(-6.02, abs=0.05)
    assert not window.input_meter.clipped
    assert window.output_meter.clipped
    assert window.input_level_label.text() == "-6 dB"


def test_closing_the_window_stops_audio(window):
    window.on_start()
    engine = window.audio_processor
    pa = engine.pa
    stream = pa.streams[0]

    window.close()

    assert not engine.running
    assert stream.closed
    assert pa.terminated
