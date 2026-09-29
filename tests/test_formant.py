"""Formant shifting, measured on synthetic vowels whose formants are known."""

import numpy as np
import pytest

from openvchange.__main__ import MainWindow
from openvchange.dsp import EffectsChain
from openvchange.formant import FormantShifter
from tests.helpers import (
    SAMPLE_RATE,
    buzz,
    dominant_frequency,
    harmonic_levels_db,
    outline_db,
    shape_difference_db,
    voice_like,
    vowel,
)

PITCHES = [110.0, 150.0, 220.0]


@pytest.fixture(scope="module")
def sources():
    """The buzz of the vocal cords at each pitch. Slow to make, so made once."""
    return {pitch: buzz(pitch) for pitch in PITCHES}


def shift(x: np.ndarray, ratio: float, buffer: int = 1024) -> np.ndarray:
    shifter = FormantShifter(SAMPLE_RATE)
    return np.concatenate([shifter.process(x[i : i + buffer], ratio) for i in range(0, len(x) - buffer + 1, buffer)])


# --- the shifter on its own ------------------------------------------------------


@pytest.mark.parametrize(
    ("sample_rate", "frame_size"),
    [(16000, 256), (22050, 512), (44100, 1024), (48000, 1024), (96000, 2048)],
)
def test_frames_last_about_a_fiftieth_of_a_second(sample_rate, frame_size):
    shifter = FormantShifter(sample_rate)
    assert shifter.frame_size == frame_size
    assert shifter.hop == frame_size // 4
    assert shifter.latency == frame_size
    assert 0.015 < shifter.latency / sample_rate < 0.025


def test_a_ratio_of_one_returns_the_input_delayed(sources):
    x = vowel(sources[150.0])
    out = shift(x, 1.0)
    latency = FormantShifter(SAMPLE_RATE).latency

    assert np.max(np.abs(out[:latency])) < 1e-9
    assert np.max(np.abs(out[latency:] - x[: len(out) - latency])) < 1e-6


@pytest.mark.parametrize("buffer", [128, 256, 4096, 1000, 77])
def test_output_does_not_depend_on_the_buffer_size(sources, buffer):
    x = vowel(sources[150.0])[:40000]
    reference = shift(x, 1.3, 1024)
    out = shift(x, 1.3, buffer)
    n = min(len(out), len(reference))
    assert np.array_equal(out[:n], reference[:n])


def test_buffers_of_changing_size_give_the_same_result(sources):
    x = vowel(sources[150.0])[:30000]
    reference = shift(x, 0.8, 1024)

    shifter = FormantShifter(SAMPLE_RATE)
    sizes = [300, 1024, 17, 2049, 1, 640]
    blocks = []
    start = 0
    i = 0
    while start + sizes[i % len(sizes)] <= len(x):
        size = sizes[i % len(sizes)]
        out = shifter.process(x[start : start + size], 0.8)
        assert len(out) == size
        blocks.append(out)
        start += size
        i += 1
    out = np.concatenate(blocks)

    n = min(len(out), len(reference))
    assert np.array_equal(out[:n], reference[:n])


@pytest.mark.parametrize("pitch", PITCHES)
@pytest.mark.parametrize("ratio", [0.7, 0.8, 1.2, 2 ** (4 / 12), 1.5])
def test_formants_move_by_the_ratio(sources, pitch, ratio):
    x = vowel(sources[pitch])
    # What the same voice would sound like with its resonances moved.
    wanted = harmonic_levels_db(vowel(sources[pitch], ratio), pitch)

    before = shape_difference_db(harmonic_levels_db(x, pitch), wanted)
    after = shape_difference_db(harmonic_levels_db(shift(x, ratio), pitch), wanted)

    # Measured: from about 11 dB down to between 1 and 4 dB.
    assert before > 10.0
    assert after < 4.5
    assert after < 0.4 * before


def test_high_voices_are_harder_but_still_improved():
    # The higher the pitch, the further apart its harmonics, and the less the spectrum
    # says about what lies between them.
    source = buzz(300.0)
    x = vowel(source)
    wanted = harmonic_levels_db(vowel(source, 1.2), 300.0)

    before = shape_difference_db(harmonic_levels_db(x, 300.0), wanted)
    after = shape_difference_db(harmonic_levels_db(shift(x, 1.2), 300.0), wanted)

    assert after < 0.5 * before


@pytest.mark.parametrize("pitch", PITCHES)
@pytest.mark.parametrize("ratio", [0.7, 1.5])
def test_pitch_does_not_move(sources, pitch, ratio):
    x = vowel(sources[pitch])
    out = shift(x, ratio)
    low = out[len(out) // 2 :].astype(np.float64)
    # Look at the fundamental alone, which the ratio would pull furthest.
    spectrum = np.fft.rfft(low * np.hanning(len(low)))
    freqs = np.fft.rfftfreq(len(low), 1 / SAMPLE_RATE)
    spectrum[(freqs < 0.6 * pitch) | (freqs > 1.4 * pitch)] = 0
    fundamental = np.fft.irfft(spectrum, len(low))

    assert dominant_frequency(fundamental) == pytest.approx(pitch, rel=0.01)


def test_silence_stays_silent():
    out = shift(np.zeros(20000, dtype=np.float32), 1.4)
    assert not out.any()


def test_no_frequency_is_changed_by_more_than_the_limit():
    shifter = FormantShifter(SAMPLE_RATE)
    rng = np.random.default_rng(0)
    # A spectrum that falls away steeply, so that moving it asks for huge changes.
    magnitude = np.exp(-np.arange(513) / 12.0) * (1 + 0.1 * rng.random(513))

    for ratio in (0.5, 2.0):
        gains_db = 20 * np.log10(shifter.gains(magnitude, ratio))
        assert np.max(np.abs(gains_db)) <= 30.0 + 1e-9
        assert np.max(np.abs(gains_db)) > 29.0


def test_reset_forgets_what_was_heard(sources):
    x = vowel(sources[150.0])[:8192]
    shifter = FormantShifter(SAMPLE_RATE)
    first = shifter.process(x, 1.2)
    assert shifter.active

    shifter.reset()

    assert not shifter.active
    assert np.array_equal(shifter.process(x, 1.2), first)


def test_output_is_single_precision_whatever_comes_in():
    shifter = FormantShifter(SAMPLE_RATE)
    for dtype in (np.float32, np.float64):
        assert shifter.process(np.zeros(512, dtype=dtype), 1.2).dtype == np.float32


# --- in the chain ------------------------------------------------------------------


def run_chain(x: np.ndarray, **settings: float) -> np.ndarray:
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_pitch(settings.get("pitch", 0.0))
    chain.set_formant(settings.get("formant", 0.0))
    chain.set_formant_preserve(bool(settings.get("preserve", False)))
    chain.reset()
    x = x.astype(np.float32)
    out = [chain.apply_formant_shift(chain.apply_pitch_shift(x[i : i + 1024])) for i in range(0, len(x) - 1023, 1024)]
    return np.concatenate(out)


def test_formant_shift_of_zero_is_skipped_entirely():
    x = voice_like(0.5).astype(np.float32)
    chain = EffectsChain(SAMPLE_RATE)
    chain.reset()
    assert chain.apply_formant_shift(x) is x
    assert not chain.formant_shifter.active


def test_keeping_formants_without_a_pitch_shift_is_skipped_entirely():
    x = voice_like(0.5).astype(np.float32)
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_formant_preserve(True)
    chain.reset()
    assert chain.apply_formant_shift(x) is x


@pytest.mark.parametrize(
    ("pitch", "formant", "preserve", "semitones"),
    [
        (0.0, 3.0, False, 3.0),
        (0.0, -5.0, True, -5.0),
        (4.0, 0.0, False, 0.0),
        (4.0, 0.0, True, -4.0),
        (-7.0, 0.0, True, 7.0),
        (4.0, 1.5, True, -2.5),
        (4.0, 1.5, False, 1.5),
        (0.05, 0.0, True, 0.0),  # a pitch shift this small is not applied, so there is nothing to undo
    ],
)
def test_formant_ratio_accounts_for_the_pitch_shift(pitch, formant, preserve, semitones):
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_pitch(pitch)
    chain.set_formant(formant)
    chain.set_formant_preserve(preserve)
    assert chain.formant_ratio() == pytest.approx(2 ** (semitones / 12))


def test_formant_shift_that_cancels_out_is_skipped():
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_pitch(4.0)
    chain.set_formant(4.0)
    chain.set_formant_preserve(True)
    chain.reset()
    x = voice_like(0.2).astype(np.float32)
    assert chain.apply_formant_shift(x) is x


def test_turning_the_shift_off_clears_the_shifter(sources):
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_formant(3.0)
    chain.reset()
    x = vowel(sources[150.0])[:4096]
    chain.apply_formant_shift(x)
    assert chain.formant_shifter.active

    chain.set_formant(0.0)
    chain.apply_formant_shift(x)

    assert not chain.formant_shifter.active
    assert not chain.formant_shifter.recent.any()


@pytest.mark.parametrize("semitones", [4.0, -4.0])
def test_pitch_shift_alone_drags_the_formants_along(sources, semitones):
    x = vowel(sources[150.0])
    original = outline_db(x)
    shifted = outline_db(run_chain(x, pitch=semitones))
    assert shape_difference_db(shifted, original) > 6.0


@pytest.mark.parametrize("semitones", [7.0, 4.0, -4.0, -7.0])
def test_keeping_formants_puts_them_back_after_a_pitch_shift(sources, semitones):
    source = sources[150.0]
    x = vowel(source)
    original = outline_db(x)
    pitch_shifted = outline_db(run_chain(x, pitch=semitones))

    dragged = shape_difference_db(pitch_shifted, original)
    kept = shape_difference_db(outline_db(run_chain(x, pitch=semitones, preserve=True)), original)

    assert dragged > 8.0
    assert kept < 0.65 * dragged

    # What is left is the colouring of the pitch shifter itself, which shows as the
    # difference between its output and a voice whose formants moved exactly with the
    # pitch. The formant shifter cannot undo that, and must not add much to it.
    moved_exactly = outline_db(vowel(source, 2 ** (semitones / 12)))
    colouring = shape_difference_db(pitch_shifted, moved_exactly)
    assert kept < colouring + 1.0


def test_a_formant_shift_on_top_of_kept_formants_is_measured_from_the_original(sources):
    source = sources[150.0]
    x = vowel(source)
    wanted = outline_db(vowel(source, 2 ** (-3 / 12)))

    left_alone = shape_difference_db(outline_db(run_chain(x, pitch=-5.0, preserve=True)), wanted)
    shifted = shape_difference_db(outline_db(run_chain(x, pitch=-5.0, formant=-3.0, preserve=True)), wanted)

    assert shifted < left_alone


def test_sample_rate_change_rebuilds_the_shifter():
    chain = EffectsChain(48000)
    assert chain.formant_shifter.frame_size == 1024
    chain.set_sample_rate(96000)
    assert chain.formant_shifter.frame_size == 2048
    assert chain.formant_shifter.sample_rate == 96000


# --- in the window -----------------------------------------------------------------


@pytest.fixture
def window(qapp):
    w = MainWindow()
    yield w
    w.close()


def test_formant_controls_drive_the_engine(window):
    window.formant_slider.setValue(-35)
    window.formant_preserve_checkbox.setChecked(True)

    assert window.effects.formant_semitones == pytest.approx(-3.5)
    assert window.effects.formant_preserve
    assert window.formant_label.text() == "-3.5 st"


def test_formants_are_left_alone_by_default(window):
    assert window.formant_slider.value() == 0
    assert not window.formant_preserve_checkbox.isChecked()
    assert window.effects.formant_ratio() == 1.0


def test_formant_settings_are_part_of_a_preset(window):
    window.formant_slider.setValue(20)
    window.formant_preserve_checkbox.setChecked(True)
    saved = window.get_preset()
    assert saved["formant"] == 20
    assert saved["formant_preserve"] is True

    window.on_reset_defaults()
    assert window.formant_slider.value() == 0
    assert not window.formant_preserve_checkbox.isChecked()

    window.apply_preset(saved)
    assert window.effects.formant_semitones == pytest.approx(2.0)
    assert window.effects.formant_preserve


def test_a_preset_from_before_formants_existed_leaves_them_alone(window):
    window.formant_slider.setValue(20)
    window.apply_preset({"gain": 5, "pitch": -23})
    assert window.formant_slider.value() == 20
    assert window.pitch_slider.value() == -23


def test_formant_settings_survive_a_restart(qapp):
    w = MainWindow()
    w.formant_slider.setValue(-15)
    w.formant_preserve_checkbox.setChecked(True)
    w.close()

    w = MainWindow()

    assert w.formant_slider.value() == -15
    assert w.formant_preserve_checkbox.isChecked()
    assert w.effects.formant_semitones == pytest.approx(-1.5)
    w.close()
