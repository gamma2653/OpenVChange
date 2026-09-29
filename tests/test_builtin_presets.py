"""The presets that come with the app."""

import numpy as np
import pytest

from openvchange import presets
from openvchange.__main__ import MainWindow
from openvchange.builtin_presets import BUILT_IN, NEUTRAL, SESSION_DEFAULTS, preset
from tests.helpers import SAMPLE_RATE, db, rms, voice_like


@pytest.fixture
def window(qapp):
    w = MainWindow()
    yield w
    w.close()


# --- the presets themselves ------------------------------------------------------


def test_there_is_a_neutral_preset_and_it_is_first():
    assert next(iter(BUILT_IN)) == "Neutral"
    assert BUILT_IN["Neutral"] == NEUTRAL


@pytest.mark.parametrize("name", list(BUILT_IN))
def test_every_preset_sets_every_effect_and_nothing_else(name):
    assert set(BUILT_IN[name]) == set(NEUTRAL)
    assert not set(BUILT_IN[name]) & set(SESSION_DEFAULTS)


@pytest.mark.parametrize("name", list(BUILT_IN))
def test_every_preset_fits_the_controls_without_adjustment(window, name):
    values, notes = presets.check(BUILT_IN[name], window.preset_fields())
    assert notes == []
    assert values == BUILT_IN[name]


def test_presets_differ_from_each_other():
    seen = [tuple(sorted(p.items())) for p in BUILT_IN.values()]
    assert len(set(seen)) == len(seen)


def test_a_misspelt_setting_is_caught_when_a_preset_is_defined():
    with pytest.raises(KeyError, match="pich"):
        preset(pich=40)


@pytest.mark.parametrize("name", list(BUILT_IN))
def test_every_preset_leaves_headroom_on_a_normal_voice(window, name):
    # A voice peaking around -7 dB, which is a sensible microphone level.
    window.apply_preset(BUILT_IN[name])
    chain = window.effects
    chain.set_sample_rate(SAMPLE_RATE)
    chain.reset()
    voice = voice_like(2.0)
    x = (0.45 * voice / np.max(np.abs(voice))).astype(np.float32)

    peaks = []
    blocks = []
    for start in range(0, len(x) - 1023, 1024):
        blocks.append(chain.process(x[start : start + 1024]))
        peaks.append(chain.peak_before_clipping)
    out = np.concatenate(blocks)[10 * 1024 :]

    assert np.all(np.isfinite(out))
    assert max(peaks[10:]) < 1.0, "the preset drives the output into clipping"
    # About as loud as it went in, so that changing presets is not a jump in volume.
    assert db(rms(out) / rms(x[10 * 1024 :])) == pytest.approx(0.0, abs=4.0)


# --- the list in the window ------------------------------------------------------


def names(window) -> list[str]:
    return [window.preset_combo.itemText(i) for i in range(window.preset_combo.count())]


def choose(window, name: str) -> None:
    """Pick a preset the way a user does."""
    index = window.preset_combo.findText(name)
    window.preset_combo.setCurrentIndex(index)
    window.preset_combo.activated.emit(index)


def test_list_offers_every_built_in_preset(window):
    assert names(window) == list(BUILT_IN)


def test_a_fresh_window_shows_neutral(window):
    assert window.preset_combo.currentText() == "Neutral"


def test_choosing_a_preset_applies_it(window):
    choose(window, "Deep voice")

    assert window.pitch_slider.value() == -40
    assert window.bass_slider.value() == 4
    assert window.compressor_checkbox.isChecked()
    assert window.effects.pitch_semitones == pytest.approx(-4.0)
    assert window.effects.compressor_enabled
    assert window.status_label.text() == "Status: Preset applied: Deep voice"
    assert window.preset_combo.currentText() == "Deep voice"


def test_choosing_another_preset_leaves_nothing_behind(window):
    choose(window, "Telephone")
    assert window.lp_checkbox.isChecked()

    choose(window, "Chipmunk")

    expected = {**window.get_preset(), **BUILT_IN["Chipmunk"]}
    assert window.get_preset() == expected
    assert not window.lp_checkbox.isChecked()
    assert not window.compressor_checkbox.isChecked()
    assert window.bass_slider.value() == 0


def test_a_preset_does_not_touch_the_session_settings(window):
    window.effects_checkbox.setChecked(False)
    window.buffer_size_combo.setCurrentIndex(0)
    window.pitch_voices_spin.setValue(7)

    choose(window, "Giant")

    assert not window.effects_checkbox.isChecked()
    assert window.buffer_size_combo.currentData() == 128
    assert window.pitch_voices_spin.value() == 7
    assert window.preset_combo.currentText() == "Giant"


def test_changing_a_setting_shows_custom(window):
    choose(window, "Deep voice")

    window.treble_slider.setValue(7)

    assert window.preset_combo.currentIndex() == -1
    assert window.preset_combo.currentText() == ""
    assert window.preset_combo.placeholderText() == "Custom"


def test_changing_the_setting_back_shows_the_preset_again(window):
    choose(window, "Deep voice")
    window.treble_slider.setValue(7)
    window.treble_slider.setValue(0)
    assert window.preset_combo.currentText() == "Deep voice"


def test_reset_shows_neutral_and_restores_the_session_settings(window):
    choose(window, "Giant")
    window.effects_checkbox.setChecked(False)
    window.pitch_voices_spin.setValue(7)

    window.on_reset_defaults()

    assert window.preset_combo.currentText() == "Neutral"
    assert window.get_preset() == {**window.get_preset(), **NEUTRAL, **SESSION_DEFAULTS}
    assert window.effects_checkbox.isChecked()
    assert window.pitch_voices_spin.value() == 4


def test_loading_a_file_that_matches_a_preset_shows_its_name(window):
    window.apply_preset({**BUILT_IN["Telephone"], "buffer_size": 2048})
    assert window.preset_combo.currentText() == "Telephone"


def test_the_preset_is_shown_again_after_a_restart(qapp):
    w = MainWindow()
    choose(w, "Radio announcer")
    w.close()

    w = MainWindow()

    assert w.preset_combo.currentText() == "Radio announcer"
    assert w.treble_slider.value() == 3
    w.close()


def test_presets_can_be_chosen_while_running(window):
    window.on_start()
    choose(window, "Higher voice")
    assert window.effects.pitch_semitones == pytest.approx(4.0)
    assert window.audio_processor.running
