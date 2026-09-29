"""Settings remembered between launches."""

import json
import sys

import pytest

from openvchange import settings
from openvchange.__main__ import MainWindow
from openvchange.settings import SettingsError
from tests.fakes import WASAPI, FakePyAudio, device

# --- the file ------------------------------------------------------------------


def test_missing_file_means_no_settings(tmp_path):
    assert settings.load(tmp_path / "nothing.json") == {}


def test_save_creates_the_folder_and_round_trips(tmp_path):
    path = tmp_path / "a" / "b" / "settings.json"
    settings.save(path, {"version": 1, "preset": {"gain": 3}})
    assert settings.load(path) == {"version": 1, "preset": {"gain": 3}}
    assert [p.name for p in path.parent.iterdir()] == ["settings.json"]


@pytest.mark.parametrize("content", ["", "{ broken", "[1, 2]", '"text"', "null"])
def test_damaged_file_is_reported(tmp_path, content):
    path = tmp_path / "settings.json"
    path.write_text(content)
    with pytest.raises(SettingsError, match="damaged"):
        settings.load(path)


def test_failed_save_keeps_the_previous_settings(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    settings.save(path, {"preset": {"gain": 1}})

    def refuse(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr(settings.os, "replace", refuse)
    with pytest.raises(SettingsError, match="could not be written"):
        settings.save(path, {"preset": {"gain": 2}})

    assert settings.load(path) == {"preset": {"gain": 1}}


def test_default_path_is_per_user_and_named_after_the_app(monkeypatch, tmp_path):
    monkeypatch.undo()  # look at the real function, not the one the fixture installed
    path = settings.default_path()
    assert path.name == "settings.json"
    assert path.parent.name == "OpenVChange"
    assert path.is_absolute()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows location")
def test_default_path_on_windows_is_under_appdata(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert settings.default_path() == tmp_path / "OpenVChange" / "settings.json"


# --- the window ----------------------------------------------------------------


def reopen(window) -> MainWindow:
    window.close()
    return MainWindow()


def test_first_launch_starts_with_defaults_and_writes_nothing(qapp, settings_path):
    w = MainWindow()
    assert w.gain_slider.value() == 0
    assert w.status_label.text() == "Status: Stopped"
    assert not settings_path.exists()
    w.close()


def test_settings_survive_a_restart(qapp, settings_path):
    w = MainWindow()
    w.gain_slider.setValue(7)
    w.pitch_slider.setValue(-25)
    w.compressor_checkbox.setChecked(True)
    w.compressor_ratio_slider.setValue(80)
    w.effects_checkbox.setChecked(False)
    w.buffer_size_combo.setCurrentIndex(1)
    w.pitch_voices_spin.setValue(6)
    before = w.get_preset()

    w = reopen(w)

    assert w.get_preset() == before
    assert w.effects.pitch_semitones == pytest.approx(-2.5)
    assert w.effects.compressor_enabled
    assert not w.audio_processor.effects_enabled
    assert w.audio_processor.chunk_size == 256
    assert w.effects.pitch_num_voices == 6
    assert w.compressor_ratio_slider.isEnabled()
    assert w.status_label.text() == "Status: Stopped"
    w.close()


def test_devices_survive_a_restart(qapp):
    w = MainWindow()
    w.output_combo.setCurrentIndex(1)

    w = reopen(w)

    assert w.input_combo.currentText() == "Microphone (USB Audio)"
    assert w.output_combo.currentText() == "CABLE Input (VB-Audio Virtual Cable)"
    w.close()


def test_devices_are_found_again_after_their_indexes_moved(qapp):
    w = MainWindow()
    w.output_combo.setCurrentIndex(1)
    w.close()
    FakePyAudio.devices = [device("New Webcam Mic", WASAPI, inputs=1, outputs=0), *FakePyAudio.devices]

    w = MainWindow()

    assert w.input_combo.currentText() == "Microphone (USB Audio)"
    assert w.output_combo.currentText() == "CABLE Input (VB-Audio Virtual Cable)"
    assert w.output_combo.currentData() == 5
    w.close()


def test_show_all_devices_and_a_device_of_another_host_api_survive_a_restart(qapp):
    w = MainWindow()
    w.show_all_devices_checkbox.setChecked(True)
    w.input_combo.setCurrentIndex(0)
    assert w.input_combo.currentText() == "Microphone (MME) [MME]"

    w = reopen(w)

    assert w.show_all_devices_checkbox.isChecked()
    assert w.input_combo.currentText() == "Microphone (MME) [MME]"
    w.close()


def test_a_device_that_is_gone_is_mentioned_and_the_rest_is_restored(qapp):
    w = MainWindow()
    w.output_combo.setCurrentIndex(1)
    w.gain_slider.setValue(5)
    w.close()
    FakePyAudio.devices = [d for d in FakePyAudio.devices if "CABLE" not in d["name"]]

    w = MainWindow()

    assert w.output_combo.currentText() == "Speakers (Realtek)"
    assert w.input_combo.currentText() == "Microphone (USB Audio)"
    assert w.gain_slider.value() == 5
    assert w.status_label.text() == "Status: Stopped (the output device used last time was not found)"
    w.close()


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        ("{ broken", "the file is damaged"),
        ('{"show_all_devices": "yes"}', "the file is damaged"),
        ('{"preset": {"gain": "loud"}}', "'gain' must be a whole number, not the text \"loud\""),
        ('{"preset": [1, 2]}', "the file does not contain a preset"),
    ],
)
def test_unusable_settings_are_reported_and_defaults_are_used(qapp, settings_path, content, reason):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(content)

    w = MainWindow()

    assert w.status_label.text() == f"Status: Your saved settings could not be restored: {reason}"
    assert w.gain_slider.value() == 0
    assert not w.show_all_devices_checkbox.isChecked()
    w.close()


def test_settings_from_a_newer_version_still_load(qapp, settings_path):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"version": 9, "theme": "dark", "preset": {"gain": 4, "reverb": 3}}))

    w = MainWindow()

    assert w.gain_slider.value() == 4
    assert w.status_label.text() == "Status: Stopped"
    w.close()


def test_closing_works_even_if_settings_cannot_be_saved(qapp, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a folder")
    w = MainWindow(settings_path=blocker / "settings.json")

    assert w.close()

    assert w.audio_processor.pa is None


def test_closing_twice_saves_once(qapp, settings_path):
    w = MainWindow()
    w.gain_slider.setValue(3)
    w.close()
    saved = settings_path.read_text()

    w.gain_slider.setValue(9)
    w.close()

    assert settings_path.read_text() == saved


def test_an_explicit_settings_path_is_used(qapp, tmp_path, settings_path):
    path = tmp_path / "elsewhere.json"
    w = MainWindow(settings_path=path)
    w.gain_slider.setValue(2)
    w.close()

    assert json.loads(path.read_text())["preset"]["gain"] == 2
    assert not settings_path.exists()
