"""Checking, reading, and writing presets, without a window."""

import json

import pytest

from openvchange import presets
from openvchange.presets import Choice, Number, PresetError, Toggle

FIELDS = {
    "enabled": Toggle(),
    "gain": Number(-100, 100),
    "buffer_size": Choice((256, 512, 1024)),
}


def test_valid_values_pass_through():
    values, notes = presets.check({"enabled": True, "gain": -7, "buffer_size": 512}, FIELDS)
    assert values == {"enabled": True, "gain": -7, "buffer_size": 512}
    assert notes == []


def test_values_at_the_ends_of_the_range_are_kept():
    assert presets.check({"gain": 100}, FIELDS) == ({"gain": 100}, [])
    assert presets.check({"gain": -100}, FIELDS) == ({"gain": -100}, [])


def test_missing_settings_are_not_invented():
    assert presets.check({}, FIELDS) == ({}, [])


def test_values_come_back_in_the_order_of_the_fields():
    values, _ = presets.check({"buffer_size": 256, "gain": 1, "enabled": False}, FIELDS)
    assert list(values) == ["enabled", "gain", "buffer_size"]


@pytest.mark.parametrize("preset", [None, [], "text", 3, True])
def test_anything_but_an_object_is_refused(preset):
    with pytest.raises(PresetError, match="does not contain a preset"):
        presets.check(preset, FIELDS)


def test_a_wrong_type_refuses_the_whole_preset():
    with pytest.raises(PresetError, match="'enabled' must be true or false, not 0"):
        presets.check({"gain": 5, "enabled": 0}, FIELDS)


def test_long_text_is_shortened_in_the_message():
    with pytest.raises(PresetError) as error:
        presets.check({"gain": "x" * 200}, FIELDS)
    assert len(str(error.value)) < 80


def test_numbers_too_large_for_the_controls_are_clamped_not_overflowed():
    values, notes = presets.check({"gain": 10**30}, FIELDS)
    assert values == {"gain": 100}
    assert len(notes) == 1


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "p.json"
    preset = {"enabled": True, "gain": -3, "buffer_size": 1024}

    presets.save(path, preset)

    assert presets.load(path) == preset
    assert path.read_text(encoding="utf-8").endswith("}\n")


def test_load_refuses_a_binary_file(tmp_path):
    path = tmp_path / "p.json"
    path.write_bytes(b"\xff\xfe\x00\x01 not text \x80")
    with pytest.raises(PresetError, match="not a text file"):
        presets.load(path)


def test_load_refuses_an_empty_file(tmp_path):
    path = tmp_path / "p.json"
    path.write_text("")
    with pytest.raises(PresetError, match="not valid JSON"):
        presets.load(path)


def test_load_refuses_a_directory(tmp_path):
    with pytest.raises(PresetError, match="could not be read"):
        presets.load(tmp_path)


def test_saved_files_are_plain_json(tmp_path):
    path = tmp_path / "p.json"
    presets.save(path, {"gain": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"gain": 1}
