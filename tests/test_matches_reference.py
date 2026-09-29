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


# --- filter coefficients -------------------------------------------------------


def test_coefficients_are_designed_once_per_setting(monkeypatch):
    chain = EffectsChain(SAMPLE_RATE)
    designs = []
    original = chain.make_shelf_filter
    monkeypatch.setattr(chain, "make_shelf_filter", lambda *a: designs.append(a) or original(*a))
    chain.set_bass(6.0)
    chain.reset()
    block = noise(1024)

    for _ in range(5):
        chain.process(block)
    assert len(designs) == 1

    chain.set_bass(7.0)
    chain.process(block)
    chain.process(block)
    assert len(designs) == 2


def test_coefficients_follow_the_sample_rate():
    chain = EffectsChain(48000)
    at_48k = chain.coefficients("bass", "lowshelf", 250, 6.0)
    chain.set_sample_rate(44100)
    at_44k = chain.coefficients("bass", "lowshelf", 250, 6.0)
    assert not np.array_equal(at_48k[0], at_44k[0])


def test_cached_coefficients_equal_a_fresh_design():
    chain = EffectsChain(SAMPLE_RATE)
    fresh = EffectsChain(SAMPLE_RATE)
    for gain in (3.0, -9.0, 3.0):
        b, a = chain.coefficients("treble", "highshelf", 4000, gain)
        expected_b, expected_a = fresh.make_shelf_filter(4000, gain, "high")
        assert np.array_equal(b, expected_b)
        assert np.array_equal(a, expected_a)
