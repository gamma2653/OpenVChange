"""Behaviour of the effects chain, measured on synthetic signals."""

import numpy as np
import pytest

from tests.helpers import (
    SAMPLE_RATE,
    dominant_frequency,
    from_pcm,
    level_change_db,
    make_processor,
    process,
    process_pcm,
    sine,
    tail,
    to_pcm,
    voice_like,
)

# One int16 step, in float units. Conversions may round either way.
LSB = 1.0 / 32768.0

EVERYTHING = {
    "gain_db": 3.0,
    "bass_db": 6.0,
    "treble_db": -4.0,
    "pitch_semitones": 4.0,
    "delay_ms": 50.0,
    "high_pass_enabled": True,
    "high_pass_hz": 120.0,
    "low_pass_enabled": True,
    "low_pass_hz": 9000.0,
    "expander_enabled": True,
    "expander_threshold_percent": 2.0,
    "expander_ratio": 3.0,
    "compressor_enabled": True,
    "compressor_threshold_db": -20.0,
    "compressor_makeup_db": 4.0,
    "deesser_enabled": True,
    "deesser_threshold_db": -28.0,
}


def change_db(settings: dict, freq: float, amplitude: float) -> float:
    """Steady-state level change caused by `settings` on a sine, relative to a neutral chain."""
    x = sine(freq, amplitude)
    reference = process(make_processor(), x)
    return level_change_db(process(make_processor(**settings), x), reference)


# --- neutral chain and bypass --------------------------------------------------


def test_bypass_returns_the_input_bytes_untouched():
    p = make_processor(**EVERYTHING)
    p.set_effects_enabled(False)
    pcm = to_pcm(voice_like(0.2))
    assert np.array_equal(process_pcm(p, pcm), pcm[: len(pcm) // 1024 * 1024])


def test_bypass_clears_filter_state_so_reenabling_starts_clean():
    p = make_processor(high_pass_enabled=True, high_pass_hz=200.0, bass_db=6.0)
    process(p, voice_like(0.1))
    assert p.effects.filter_states

    p.set_effects_enabled(False)
    process(p, voice_like(0.1))
    assert p.effects.filter_states == {}


def test_neutral_chain_only_soft_clips():
    x = sine(300.0, 0.5)
    out = process(make_processor(), x)
    expected = np.tanh(from_pcm(to_pcm(x)))[: len(out)]
    assert np.max(np.abs(out - expected)) <= 2 * LSB


def test_silence_in_gives_silence_out():
    out = process_pcm(make_processor(**EVERYTHING), np.zeros(SAMPLE_RATE // 2, dtype=np.int16))
    assert not out.any()


def test_output_never_exceeds_full_scale():
    out = process(make_processor(gain_db=58.0, bass_db=20.0), voice_like(0.5))
    assert np.max(np.abs(out)) <= 1.0


# --- gain ----------------------------------------------------------------------


def test_gain_is_applied_before_the_soft_clipper():
    out = process(make_processor(gain_db=20 * np.log10(2.0)), sine(300.0, 0.1))
    assert np.max(np.abs(tail(out))) == pytest.approx(np.tanh(0.2), abs=3 * LSB)


def test_gain_change_is_smoothed_rather_than_stepped():
    p = make_processor()
    x = sine(300.0, 0.1, seconds=0.5)
    process(p, x)
    p.effects.set_gain(12.0)
    out = process(p, x)
    settled = np.tanh(0.1 * 10 ** (12 / 20))
    # One millisecond after the change the level has only started to move.
    assert np.max(np.abs(out[:48])) < 0.5 * settled
    assert np.max(np.abs(tail(out))) == pytest.approx(settled, abs=3 * LSB)


# --- filters -------------------------------------------------------------------


def test_high_pass_removes_lows_and_keeps_highs():
    settings = {"high_pass_enabled": True, "high_pass_hz": 300.0}
    # Second order: 12 dB per octave, and 50 Hz is about 2.6 octaves below the cutoff.
    assert change_db(settings, 50.0, 0.05) == pytest.approx(-31.2, abs=1.0)
    assert change_db(settings, 3000.0, 0.05) == pytest.approx(0.0, abs=0.1)


def test_high_pass_at_its_minimum_frequency_is_skipped():
    settings = {"high_pass_enabled": True, "high_pass_hz": 20.0}
    x = voice_like(0.3)
    assert np.array_equal(process(make_processor(**settings), x), process(make_processor(), x))


def test_low_pass_removes_highs_and_keeps_lows():
    settings = {"low_pass_enabled": True, "low_pass_hz": 1000.0}
    assert change_db(settings, 8000.0, 0.05) == pytest.approx(-38.1, abs=1.0)
    assert change_db(settings, 100.0, 0.05) == pytest.approx(0.0, abs=0.1)


def test_disabled_filters_do_nothing_whatever_their_frequency():
    x = voice_like(0.3)
    out = process(make_processor(high_pass_hz=400.0, low_pass_hz=2000.0), x)
    assert np.array_equal(out, process(make_processor(), x))


@pytest.mark.parametrize("gain_db", [12.0, -12.0])
def test_bass_shelf_changes_lows_only(gain_db):
    assert change_db({"bass_db": gain_db}, 40.0, 0.02) == pytest.approx(gain_db, abs=0.5)
    assert change_db({"bass_db": gain_db}, 5000.0, 0.02) == pytest.approx(0.0, abs=0.1)


@pytest.mark.parametrize("gain_db", [12.0, -12.0])
def test_treble_shelf_changes_highs_only(gain_db):
    assert change_db({"treble_db": gain_db}, 12000.0, 0.02) == pytest.approx(gain_db, abs=0.8)
    assert change_db({"treble_db": gain_db}, 100.0, 0.02) == pytest.approx(0.0, abs=0.1)


def test_shelf_gains_of_half_a_db_or_less_are_skipped():
    x = voice_like(0.3)
    out = process(make_processor(bass_db=0.5, treble_db=-0.5), x)
    assert np.array_equal(out, process(make_processor(), x))


# --- delay ---------------------------------------------------------------------


@pytest.mark.parametrize("delay_ms", [10.0, 250.0])
def test_delay_shifts_the_signal_by_the_requested_time(delay_ms):
    x = sine(300.0, 0.2, seconds=0.75)
    out = process(make_processor(delay_ms=delay_ms), x)
    undelayed = process(make_processor(), x)
    shift = int(delay_ms * SAMPLE_RATE / 1000)

    assert not out[:shift].any()
    assert np.max(np.abs(out[shift:] - undelayed[: len(out) - shift])) <= 2 * LSB


# --- pitch ---------------------------------------------------------------------


@pytest.mark.parametrize("semitones", [12.0, 7.0, -5.0, -12.0])
def test_pitch_shift_moves_a_tone_towards_the_target(semitones):
    freq = 1000.0
    p = make_processor(pitch_semitones=semitones)
    out = process(p, sine(freq, 0.3, seconds=2.0))
    target = freq * 2 ** (semitones / 12)

    # The grain-based shifter can only place a pure tone on a grid whose spacing is the
    # rate at which grains start, so allow half of that spacing.
    grain_rate = SAMPLE_RATE / (p.effects.pitch_window_size / p.effects.pitch_num_voices)
    assert dominant_frequency(tail(out)) == pytest.approx(target, abs=grain_rate / 2)


def test_pitch_shifts_below_a_tenth_of_a_semitone_are_skipped():
    x = voice_like(0.3)
    out = process(make_processor(pitch_semitones=0.05), x)
    assert np.array_equal(out, process(make_processor(), x))


@pytest.mark.parametrize("voices", [1, 3, 8])
def test_pitch_shift_works_with_any_voice_count(voices):
    out = process(make_processor(pitch_semitones=5.0, pitch_voices=voices), voice_like(0.5))
    assert np.all(np.isfinite(out))
    assert tail(out).any()


# --- dynamics ------------------------------------------------------------------


def test_compressor_turns_down_loud_signals_only():
    settings = {"compressor_enabled": True, "compressor_threshold_db": -20.0, "compressor_ratio": 4.0}
    assert change_db(settings, 300.0, 0.5) == pytest.approx(-8.4, abs=1.0)
    assert change_db(settings, 300.0, 0.01) == pytest.approx(0.0, abs=0.1)


def test_compressor_with_a_ratio_of_one_changes_nothing():
    settings = {"compressor_enabled": True, "compressor_threshold_db": -40.0, "compressor_ratio": 1.0}
    assert change_db(settings, 300.0, 0.5) == pytest.approx(0.0, abs=0.01)


def test_compressor_makeup_gain_raises_the_level():
    settings = {"compressor_enabled": True, "compressor_threshold_db": -20.0, "compressor_makeup_db": 6.0}
    assert change_db(settings, 300.0, 0.01) == pytest.approx(6.0, abs=0.1)


def test_expander_silences_signals_below_the_threshold():
    settings = {"expander_enabled": True, "expander_threshold_percent": 5.0, "expander_ratio": 4.0}
    assert change_db(settings, 300.0, 0.005) < -20.0


def test_expander_mostly_keeps_signals_above_the_threshold():
    settings = {"expander_enabled": True, "expander_threshold_percent": 5.0, "expander_ratio": 4.0}
    assert -6.0 < change_db(settings, 300.0, 0.5) <= 0.0


def test_deesser_turns_down_sibilance_only():
    settings = {"deesser_enabled": True, "deesser_threshold_db": -20.0, "deesser_reduction_db": 6.0}
    assert change_db(settings, 6500.0, 0.3) == pytest.approx(-6.0, abs=0.5)
    assert change_db(settings, 200.0, 0.3) == pytest.approx(0.0, abs=0.1)


def test_deesser_leaves_quiet_sibilance_alone():
    settings = {"deesser_enabled": True, "deesser_threshold_db": -20.0, "deesser_reduction_db": 6.0}
    assert change_db(settings, 6500.0, 0.01) == pytest.approx(0.0, abs=0.1)


# --- whole chain ---------------------------------------------------------------


@pytest.mark.parametrize("chunk", [128, 256, 4096])
def test_output_does_not_depend_on_the_buffer_size(chunk):
    pcm = to_pcm(voice_like(1.0))
    reference = process_pcm(make_processor(**EVERYTHING), pcm, 1024)
    out = process_pcm(make_processor(**EVERYTHING), pcm, chunk)
    n = min(len(out), len(reference))
    assert np.array_equal(out[:n], reference[:n])


@pytest.mark.parametrize("sample_rate", [16000, 44100, 96000])
def test_chain_runs_at_every_supported_sample_rate(sample_rate):
    x = voice_like(0.5, sample_rate=sample_rate)
    out = process(make_processor(sample_rate=sample_rate, **EVERYTHING), x)
    assert np.all(np.isfinite(out))
    assert tail(out).any()
