"""Settings remembered between launches."""

import json
import sys

import pytest
from PySide6.QtGui import QKeySequence

from openvchange import settings
from openvchange.__main__ import MainWindow
from openvchange.hotkey import MOD_ALT, MOD_CONTROL
from openvchange.settings import SettingsError
from tests.fakes import MME, WASAPI, FakePyAudio, device

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
    assert w.route.gain_slider.value() == 0
    assert w.status_label.text() == "Status: Stopped"
    assert not settings_path.exists()
    w.close()


def test_settings_survive_a_restart(qapp, settings_path):
    w = MainWindow()
    w.route.gain_slider.setValue(7)
    w.route.pitch_slider.setValue(-25)
    w.route.compressor_checkbox.setChecked(True)
    w.route.compressor_ratio_slider.setValue(80)
    w.route.effects_checkbox.setChecked(False)
    w.route.buffer_size_combo.setCurrentIndex(1)
    w.route.pitch_voices_spin.setValue(6)
    before = w.route.get_preset()

    w = reopen(w)

    assert w.route.get_preset() == before
    assert w.route.effects.pitch_semitones == pytest.approx(-2.5)
    assert w.route.effects.compressor_enabled
    assert not w.audio_processor.routes[0].effects_enabled
    assert w.audio_processor.routes[0].chunk_size == 256
    assert w.route.effects.pitch_num_voices == 6
    assert w.route.compressor_ratio_slider.isEnabled()
    assert w.status_label.text() == "Status: Stopped"
    w.close()


def test_devices_survive_a_restart(qapp):
    w = MainWindow()
    w.route.output.device.setCurrentIndex(1)

    w = reopen(w)

    assert w.route.input.device.currentText() == "Microphone (USB Audio)"
    assert w.route.output.device.currentText() == "CABLE Input (VB-Audio Virtual Cable)"
    w.close()


def test_devices_are_found_again_after_their_indexes_moved(qapp):
    w = MainWindow()
    w.route.output.device.setCurrentIndex(1)
    w.close()
    FakePyAudio.devices = [device("New Webcam Mic", WASAPI, inputs=1, outputs=0), *FakePyAudio.devices]

    w = MainWindow()

    assert w.route.input.device.currentText() == "Microphone (USB Audio)"
    assert w.route.output.device.currentText() == "CABLE Input (VB-Audio Virtual Cable)"
    assert w.route.output.device.currentData() == 5
    w.close()


def test_show_all_devices_and_a_device_of_another_host_api_survive_a_restart(qapp):
    w = MainWindow()
    w.route.show_all_devices_checkbox.setChecked(True)
    w.route.input.device.setCurrentIndex(0)
    assert w.route.input.device.currentText() == "Microphone (MME) [MME]"

    w = reopen(w)

    assert w.route.show_all_devices_checkbox.isChecked()
    assert w.route.input.device.currentText() == "Microphone (MME) [MME]"
    w.close()


def test_a_device_that_is_gone_is_mentioned_and_the_rest_is_restored(qapp):
    w = MainWindow()
    w.route.output.device.setCurrentIndex(1)
    w.route.gain_slider.setValue(5)
    w.close()
    FakePyAudio.devices = [d for d in FakePyAudio.devices if "CABLE" not in d["name"]]

    w = MainWindow()

    assert w.route.output.device.currentText() == "Speakers (Realtek)"
    assert w.route.input.device.currentText() == "Microphone (USB Audio)"
    assert w.route.gain_slider.value() == 5
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
    assert w.route.gain_slider.value() == 0
    assert not w.route.show_all_devices_checkbox.isChecked()
    w.close()


def test_settings_from_a_newer_version_still_load(qapp, settings_path):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"version": 9, "theme": "dark", "preset": {"gain": 4, "reverb": 3}}))

    w = MainWindow()

    assert w.route.gain_slider.value() == 4
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
    w.route.gain_slider.setValue(3)
    w.close()
    saved = settings_path.read_text()

    w.route.gain_slider.setValue(9)
    w.close()

    assert settings_path.read_text() == saved


def test_an_explicit_settings_path_is_used(qapp, tmp_path, settings_path):
    path = tmp_path / "elsewhere.json"
    w = MainWindow(settings_path=path)
    w.route.gain_slider.setValue(2)
    w.close()

    assert json.loads(path.read_text())["preset"]["gain"] == 2
    assert not settings_path.exists()


# --- routes --------------------------------------------------------------------


def keys(text: str) -> QKeySequence:
    return QKeySequence.fromString(text, QKeySequence.SequenceFormat.PortableText)


def two_routes(w: MainWindow) -> None:
    """The USB microphone to the speakers, and channel 2 of the MME microphone to channel 2 of the cable."""
    w.set_show_all_devices(True)
    w.add_route()
    w.route.input.restore("MME: Microphone (MME)", 1)
    w.route.output.restore("Windows WASAPI: CABLE Input (VB-Audio Virtual Cable)", 1)


def test_routes_survive_a_restart(qapp):
    w = MainWindow()
    two_routes(w)

    w = reopen(w)

    assert [w.tabs.tabText(i) for i in range(w.tabs.count())] == ["Route 1", "Route 2"]
    assert w.tabs.currentIndex() == 1
    first, second = w.routes
    assert first.input.device.currentText() == "Microphone (USB Audio) [Windows WASAPI]"
    assert first.output.device.currentText() == "Speakers (Realtek) [Windows WASAPI]"
    assert second.input.device.currentText() == "Microphone (MME) [MME]"
    assert second.input.channel.currentText() == "Ch 2"
    assert second.output.channel.currentText() == "Ch 2"
    assert len(w.audio_processor.routes) == 2
    w.close()


def test_the_settings_of_every_route_survive_a_restart(qapp):
    w = MainWindow()
    w.route.gain_slider.setValue(4)
    w.route.buffer_size_combo.setCurrentIndex(1)
    w.add_route()
    w.route.pitch_slider.setValue(-50)
    w.route.effects_checkbox.setChecked(False)
    w.route.pitch_voices_spin.setValue(6)
    w.route.set_shortcut(keys("Ctrl+Alt+2"))
    w.add_route()
    w.route.effects_checkbox.setChecked(True)
    w.route.delay_slider.setValue(250)
    w.route.buffer_size_combo.setCurrentIndex(5)
    w.tabs.setCurrentIndex(1)

    w = reopen(w)

    assert w.tabs.currentIndex() == 1
    first, second, third = w.routes
    assert first.gain_slider.value() == 4 and first.buffer_size_combo.currentData() == 256
    assert second.pitch_slider.value() == -50 and not second.effects_checkbox.isChecked()
    assert second.hotkey.sequence == keys("Ctrl+Alt+2")
    assert second.hotkey_edit.keySequence() == keys("Ctrl+Alt+2")
    assert third.delay_slider.value() == 250 and third.effects_checkbox.isChecked()
    engine = w.audio_processor
    assert engine.routes[0].effects.gain_target == pytest.approx(10 ** (4 / 20))
    assert [r.chunk_size for r in engine.routes] == [256, 256, 4096]
    assert [r.effects.pitch_num_voices for r in engine.routes] == [4, 6, 6]
    assert engine.routes[1].effects.pitch_semitones == -5.0 and not engine.routes[1].effects_enabled
    assert engine.routes[2].effects.delay_ms == 250 and engine.routes[2].effects_enabled
    assert w.status_label.text() == "Status: Stopped"
    w.close()


def test_settings_from_before_there_were_routes_give_one_route(qapp, settings_path):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "version": 1,
                "input_device": "Windows WASAPI: Microphone (USB Audio)",
                "output_device": "Windows WASAPI: CABLE Input (VB-Audio Virtual Cable)",
                "show_all_devices": False,
                "effects_shortcut": "Ctrl+Alt+F9",
                "preset": {"gain": 7, "pitch": -25, "effects_enabled": False, "buffer_size": 256},
            }
        )
    )

    w = MainWindow()

    assert len(w.routes) == 1
    assert w.route.output.device.currentText() == "CABLE Input (VB-Audio Virtual Cable)"
    assert w.route.gain_slider.value() == 7
    assert w.route.effects.pitch_semitones == -2.5
    assert not w.audio_processor.routes[0].effects_enabled
    assert w.audio_processor.routes[0].chunk_size == 256
    assert w.route.hotkey.sequence == keys("Ctrl+Alt+F9")
    assert w.status_label.text() == "Status: Stopped"
    w.close()


def test_the_file_still_says_what_earlier_versions_look_for(qapp, settings_path):
    w = MainWindow()
    w.route.gain_slider.setValue(3)
    w.route.set_shortcut(keys("Ctrl+Alt+1"))
    w.add_route()
    w.route.gain_slider.setValue(-9)
    w.close()

    saved = json.loads(settings_path.read_text())

    assert saved["version"] == 2
    assert saved["input_device"] == "Windows WASAPI: Microphone (USB Audio)"
    assert saved["output_device"] == "Windows WASAPI: Speakers (Realtek)"
    assert saved["effects_shortcut"] == "Ctrl+Alt+1"
    assert saved["preset"]["gain"] == 3
    assert saved["preset"]["buffer_size"] == 1024
    assert [route["preset"]["gain"] for route in saved["routes"]] == [3, -9]
    assert [route["shortcut"] for route in saved["routes"]] == ["Ctrl+Alt+1", ""]
    assert saved["selected_route"] == 1


def test_a_device_or_channel_that_is_gone_is_named_by_its_route(qapp):
    w = MainWindow()
    two_routes(w)
    w.close()
    FakePyAudio.devices = [
        device("Microphone (MME)", MME, inputs=1, outputs=0),
        *(d for d in FakePyAudio.devices[1:] if "CABLE" not in d["name"]),
    ]

    w = MainWindow()

    assert w.status_label.text() == (
        "Status: Stopped (the input device of route 2 and the output device of route 2 used last time was not found)"
    )
    assert len(w.routes) == 2
    assert w.routes[1].input.channel.currentText() == "All"
    w.close()


def test_a_remembered_shortcut_that_is_now_taken_names_its_route(qapp, settings_path, fake_hotkeys):
    w = MainWindow()
    w.add_route()
    w.route.set_shortcut(keys("Ctrl+Alt+2"))
    w.close()
    fake_hotkeys.taken = {(MOD_CONTROL | MOD_ALT, ord("2"))}

    w = MainWindow()

    assert w.status_label.text() == (
        "Status: Stopped (the shortcut Ctrl+Alt+2 of route 2 cannot be used: another application already uses it)"
    )
    assert w.routes[1].hotkey.sequence.isEmpty()
    w.close()


@pytest.mark.parametrize(
    "change",
    [
        {"routes": []},
        {"routes": "all"},
        {"routes": [5]},
        {"routes": None},
        {"routes": [{"input_channel": "left"}]},
        {"routes": [{"output_channel": -1}]},
        {"routes": [{"output_channel": True}]},
    ],
)
def test_routes_that_make_no_sense_are_reported_and_nothing_is_applied(qapp, settings_path, change):
    saved = {"show_all_devices": True, "preset": {"gain": 5}, "routes": [{"preset": {"gain": 5}}], **change}
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps(saved))

    w = MainWindow()

    assert w.status_label.text() == "Status: Your saved settings could not be restored: the file is damaged"
    assert w.route.gain_slider.value() == 0
    assert not w.show_all_devices
    assert len(w.routes) == 1
    w.close()


def test_a_wrong_value_on_any_route_refuses_the_whole_file(qapp, settings_path):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"routes": [{"preset": {"gain": 5}}, {"preset": {"gain": "loud"}}]}))

    w = MainWindow()

    assert w.status_label.text() == (
        "Status: Your saved settings could not be restored: 'gain' must be a whole number, not the text \"loud\""
    )
    assert len(w.routes) == 1
    assert w.route.gain_slider.value() == 0
    w.close()


def test_a_value_out_of_range_is_fitted_and_its_route_is_named(qapp, settings_path):
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"routes": [{}, {"preset": {"gain": 500}}], "selected_route": 7}))

    w = MainWindow()

    assert w.status_label.text() == "Status: Stopped (route 2: 'gain' was changed from 500 to 100 to fit its range)"
    assert w.tabs.currentIndex() == 0
    assert w.audio_processor.routes[1].effects.gain_target == pytest.approx(10 ** (100 / 20))
    w.close()
