"""The optimised effects must produce exactly what the sample-by-sample originals do."""

import numpy as np
import pytest

from openvchange.dsp import EffectsChain
from tests import reference_dsp

SAMPLE_RATE = 48000


def noise(n: int, seed: int = 0, dtype: type = np.float32) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-0.9, 0.9, n).astype(dtype)


def buffers(total: int, sizes: list[int], seed: int = 0, dtype: type = np.float32):
    """Random audio cut into buffers whose sizes cycle through `sizes`."""
    x = noise(total, seed, dtype)
    start = 0
    i = 0
    while start < total:
        size = sizes[i % len(sizes)]
        yield x[start : start + size]
        start += size
        i += 1


# --- delay ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("buffer_size", "delay_samples"),
    [
        (5000, 0),  # shorter than one sample: passes straight through
        (5000, 1),
        (5000, 100),  # shorter than a buffer: reads its own output
        (5000, 1024),  # exactly one buffer
        (5000, 3000),
        (5000, 4999),  # the longest the buffer allows
        (2000, 1999),  # buffer barely longer than the audio buffers
    ],
)
@pytest.mark.parametrize("sizes", [[1024], [128], [4096], [300, 1024, 17]])
def test_delay_matches_reference(buffer_size, delay_samples, sizes):
    chain = EffectsChain(SAMPLE_RATE)
    chain.delay_buffer_size = buffer_size
    chain.reset()
    chain.set_delay(delay_samples * 1000 / SAMPLE_RATE + 1e-9)
    ref_buffer = np.zeros(buffer_size, dtype=np.float32)
    ref_pos = 0

    for block in buffers(3 * buffer_size + 5000, sizes):
        expected, ref_pos = reference_dsp.delay(block, ref_buffer, ref_pos, delay_samples)
        out = chain.apply_delay(block)
        assert out.dtype == np.float32
        assert np.array_equal(out, expected)
        assert chain.delay_write_pos == ref_pos
        assert np.array_equal(chain.delay_buffer, ref_buffer)


def test_delay_longer_than_the_buffer_is_capped_like_the_reference():
    chain = EffectsChain(SAMPLE_RATE)
    chain.delay_buffer_size = 3000
    chain.reset()
    chain.set_delay(10_000)
    ref_buffer = np.zeros(3000, dtype=np.float32)
    ref_pos = 0

    for block in buffers(12000, [1024]):
        expected, ref_pos = reference_dsp.delay(block, ref_buffer, ref_pos, 2999)
        assert np.array_equal(chain.apply_delay(block), expected)


def test_delay_accepts_double_precision_input():
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_delay(5.0)
    chain.reset()
    ref_buffer = np.zeros(chain.delay_buffer_size, dtype=np.float32)
    block = noise(1024, dtype=np.float64)

    expected, _ = reference_dsp.delay(block, ref_buffer, 0, 240)

    assert np.array_equal(chain.apply_delay(block), expected)


# --- gain ----------------------------------------------------------------------


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("sizes", [[1024], [128], [4096], [300, 1024, 17]])
def test_gain_matches_reference_through_changes(dtype, sizes):
    chain = EffectsChain(SAMPLE_RATE)
    chain.reset()
    smoothed = 1.0
    gains_db = [0.0, 12.0, 12.0, -30.0, 58.0, -100.0, 0.0, 0.0, 3.5]

    for i, block in enumerate(buffers(60_000, sizes, dtype=dtype)):
        # Change the setting every few buffers, including mid-glide.
        gain_db = gains_db[(i // 3) % len(gains_db)]
        chain.set_gain(gain_db)

        expected, smoothed = reference_dsp.smoothed_gain(block, smoothed, 10 ** (gain_db / 20), 0.995)
        out = chain.apply_gain(block)

        assert out.dtype == dtype
        assert np.array_equal(out, expected)
        assert chain.gain_smoothed == smoothed


def test_gain_settles_and_then_stays_put():
    chain = EffectsChain(SAMPLE_RATE)
    chain.reset()
    chain.set_gain(6.0)
    block = noise(4096)

    for _ in range(4):
        chain.apply_gain(block)
    settled = chain.gain_smoothed
    chain.apply_gain(block)

    assert chain.gain_smoothed == settled
    assert settled == pytest.approx(10 ** (6 / 20), rel=1e-12)


# --- pitch shift ---------------------------------------------------------------


def assert_same_audio(out: np.ndarray, expected: np.ndarray) -> None:
    """Equal to within one float32 step.

    Both sides call the same maths library, but on whole buffers it may take a different
    code path than on single samples, and the two are allowed to round differently.
    """
    assert out.dtype == expected.dtype == np.float32
    np.testing.assert_array_max_ulp(out, expected, maxulp=1)


def compare_pitch_shift(semitones: float, voices: int, sizes: list[int], total: int, dtype: type = np.float32):
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_pitch_num_voices(voices)
    chain.set_pitch(semitones)
    chain.reset()
    state = reference_dsp.PitchState(voices)

    for block in buffers(total, sizes, dtype=dtype):
        expected = reference_dsp.pitch_shift(block, semitones, state)
        assert_same_audio(chain.apply_pitch_shift(block), expected)

        assert chain.pitch_write_pos == state.write_pos
        assert chain.pitch_read_pos == state.read_pos
        assert chain.pitch_fade_pos == state.fade_pos
        assert np.array_equal(chain.pitch_buffer, state.buffer)


@pytest.mark.parametrize("semitones", [12.0, 7.0, 0.1, -2.3, -5.0, -12.0])
@pytest.mark.parametrize("voices", [1, 3, 4, 8])
def test_pitch_shift_matches_reference(semitones, voices):
    compare_pitch_shift(semitones, voices, [1024], total=20_000)


@pytest.mark.parametrize("sizes", [[128], [4096], [300, 1024, 17, 2049]])
@pytest.mark.parametrize("semitones", [5.0, -7.5])
def test_pitch_shift_matches_reference_at_any_buffer_size(sizes, semitones):
    compare_pitch_shift(semitones, 4, sizes, total=30_000)


@pytest.mark.parametrize("semitones", [24.0, 19.0, -24.0, -40.0])
def test_pitch_shift_matches_reference_beyond_the_slider_range(semitones):
    # Far enough that the voices overtake the write position or fall a full buffer behind.
    compare_pitch_shift(semitones, 4, [1024, 4096], total=40_000)


def test_pitch_shift_matches_reference_on_buffers_longer_than_its_own():
    compare_pitch_shift(4.0, 4, [20_000], total=40_000)


def test_pitch_shift_matches_reference_with_double_precision_input():
    compare_pitch_shift(-3.0, 4, [1024], total=12_000, dtype=np.float64)


def test_pitch_shift_matches_reference_when_the_setting_changes():
    chain = EffectsChain(SAMPLE_RATE)
    chain.reset()
    state = reference_dsp.PitchState()
    settings = [4.0, 4.0, -9.0, 11.5, -0.5, 2.0]

    for i, block in enumerate(buffers(40_000, [1024, 512])):
        semitones = settings[(i // 4) % len(settings)]
        chain.set_pitch(semitones)
        assert_same_audio(chain.apply_pitch_shift(block), reference_dsp.pitch_shift(block, semitones, state))
        assert chain.pitch_read_pos == state.read_pos


# --- dynamics ------------------------------------------------------------------


def speech_like(total: int, sizes: list[int], dtype: type = np.float32):
    """Buffers with loud passages, quiet passages, exact silence, and hiss."""
    rng = np.random.default_rng(3)
    t = np.arange(total) / SAMPLE_RATE
    loudness = np.clip(np.sin(2 * np.pi * 1.7 * t), 0, None) ** 2
    tone = np.sin(2 * np.pi * 180 * t) + 0.4 * np.sin(2 * np.pi * 6500 * t)
    x = 0.7 * loudness * tone + 0.002 * rng.standard_normal(total)
    x[total // 3 : total // 3 + 3000] = 0.0
    x = x.astype(dtype)
    start = 0
    i = 0
    while start < total:
        size = sizes[i % len(sizes)]
        yield x[start : start + size]
        start += size
        i += 1


def assert_close_audio(out: np.ndarray, expected: np.ndarray) -> None:
    """Equal to within a couple of steps of the array's own precision.

    The logarithms and powers are evaluated on whole buffers here and on single samples
    in the reference, and the maths library may round those differently.
    """
    assert out.dtype == expected.dtype
    np.testing.assert_array_max_ulp(out, expected, maxulp=2)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("sizes", [[1024], [128], [300, 1024, 17]])
@pytest.mark.parametrize(
    ("threshold_db", "ratio", "attack_ms", "release_ms", "makeup_db"),
    [(-10.0, 4.0, 10.0, 100.0, 0.0), (-30.0, 11.4, 27.0, 229.0, 1.0), (0.0, 1.0, 1.0, 10.0, 24.0)],
)
def test_compressor_matches_reference(dtype, sizes, threshold_db, ratio, attack_ms, release_ms, makeup_db):
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_compressor_enabled(True)
    chain.set_compressor_threshold(threshold_db)
    chain.set_compressor_ratio(ratio)
    chain.set_compressor_attack(attack_ms)
    chain.set_compressor_release(release_ms)
    chain.set_compressor_makeup(makeup_db)
    chain.reset()
    envelope_db = -60.0

    for block in speech_like(40_000, sizes, dtype):
        expected, envelope_db = reference_dsp.compressor(
            block, envelope_db, SAMPLE_RATE, threshold_db, ratio, attack_ms, release_ms, makeup_db
        )
        assert_close_audio(chain.apply_compressor(block), expected)
        # Single-precision logarithms round differently on buffers than on samples.
        assert chain.compressor_envelope_db == pytest.approx(envelope_db, rel=1e-7)


def test_an_empty_buffer_is_passed_through():
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_expander_enabled(True)
    chain.set_compressor_enabled(True)
    chain.set_deesser_enabled(True)
    chain.set_pitch(3.0)
    chain.set_delay(10.0)
    chain.reset()
    empty = np.zeros(0, dtype=np.float32)

    assert len(chain.process(empty)) == 0
    for effect in (chain.apply_expander, chain.apply_compressor, chain.apply_pitch_shift, chain.apply_delay):
        assert len(effect(empty)) == 0
