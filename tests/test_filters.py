"""Filter designs, checked against theory, and the filter itself, checked against a loop."""

import math

import numpy as np
import pytest

from openvchange import dsp, filters
from openvchange.dsp import EffectsChain
from openvchange.filters import Biquad, response_db
from tests import reference_dsp

SAMPLE_RATE = 48000


def noise(n: int, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).uniform(-0.5, 0.5, n)


# --- designs -------------------------------------------------------------------


def butterworth_db(freq: float, cutoff: float, sample_rate: float, high: bool) -> float:
    """What a second-order digital Butterworth filter does at `freq`, from its definition."""
    ratio = math.tan(math.pi * freq / sample_rate) / math.tan(math.pi * cutoff / sample_rate)
    if high:
        ratio = 1 / ratio
    return -10 * math.log10(1 + ratio**4)


@pytest.mark.parametrize("sample_rate", [16000, 44100, 48000, 96000])
@pytest.mark.parametrize("cutoff", [20.1, 80.0, 500.0, 1000.0, 3400.0, 7000.0])
def test_lowpass_and_highpass_are_butterworth(sample_rate, cutoff):
    low = filters.lowpass(cutoff, sample_rate)
    high = filters.highpass(cutoff, sample_rate)
    for freq in (cutoff / 8, cutoff / 2, cutoff, cutoff * 2, cutoff * 8):
        if freq >= 0.49 * sample_rate:
            continue
        assert response_db(low, freq, sample_rate) == pytest.approx(
            butterworth_db(freq, cutoff, sample_rate, high=False), abs=1e-6
        )
        assert response_db(high, freq, sample_rate) == pytest.approx(
            butterworth_db(freq, cutoff, sample_rate, high=True), abs=1e-6
        )


def test_lowpass_and_highpass_are_3_db_down_at_the_cutoff():
    assert response_db(filters.lowpass(1000.0, SAMPLE_RATE), 1000.0, SAMPLE_RATE) == pytest.approx(-3.0103, abs=1e-4)
    assert response_db(filters.highpass(1000.0, SAMPLE_RATE), 1000.0, SAMPLE_RATE) == pytest.approx(-3.0103, abs=1e-4)


def test_designs_match_the_values_scipy_gave():
    # From scipy.signal.butter(2, 1000 / 24000, "low") and (2, 80 / 24000, "high"),
    # SciPy 1.15.3, which this code replaced.
    b, a = filters.lowpass(1000.0, SAMPLE_RATE)
    assert b == pytest.approx([0.003916126660547369, 0.007832253321094738, 0.003916126660547369], rel=1e-12)
    assert a == pytest.approx([1.0, -1.815341082704568, 0.8310055893467575], rel=1e-12)

    b, a = filters.highpass(80.0, SAMPLE_RATE)
    assert b == pytest.approx([0.992622542756119, -1.985245085512238, 0.992622542756119], rel=1e-12)
    assert a == pytest.approx([1.0, -1.9851906578962617, 0.985299513128215], rel=1e-12)


NYQUIST = SAMPLE_RATE / 2


@pytest.mark.parametrize("gain_db", [-128.0, -12.0, -0.6, 0.6, 6.0, 20.0, 128.0])
def test_low_shelf_changes_the_lows_by_its_gain_and_leaves_the_highs(gain_db):
    design = filters.shelf(250.0, SAMPLE_RATE, gain_db, False)
    assert response_db(design, 0.0, SAMPLE_RATE) == pytest.approx(gain_db, abs=1e-6)
    assert response_db(design, NYQUIST, SAMPLE_RATE) == pytest.approx(0.0, abs=1e-6)
    # Half way, in dB, at the frequency it is named after.
    assert response_db(design, 250.0, SAMPLE_RATE) == pytest.approx(gain_db / 2, abs=1e-6)


@pytest.mark.parametrize("gain_db", [-128.0, -12.0, -0.6, 0.6, 6.0, 20.0, 128.0])
def test_high_shelf_changes_the_highs_by_its_gain_and_leaves_the_lows(gain_db):
    design = filters.shelf(4000.0, SAMPLE_RATE, gain_db, True)
    assert response_db(design, NYQUIST, SAMPLE_RATE) == pytest.approx(gain_db, abs=1e-6)
    assert response_db(design, 0.0, SAMPLE_RATE) == pytest.approx(0.0, abs=1e-6)
    assert response_db(design, 4000.0, SAMPLE_RATE) == pytest.approx(gain_db / 2, abs=1e-6)


def test_a_moderate_shelf_has_reached_its_gain_well_before_the_ends():
    low = filters.shelf(250.0, SAMPLE_RATE, 12.0, False)
    high = filters.shelf(4000.0, SAMPLE_RATE, 12.0, True)
    assert response_db(low, 40.0, SAMPLE_RATE) == pytest.approx(12.0, abs=0.3)
    assert response_db(low, 5000.0, SAMPLE_RATE) == pytest.approx(0.0, abs=0.1)
    assert response_db(high, 16000.0, SAMPLE_RATE) == pytest.approx(12.0, abs=0.3)
    assert response_db(high, 100.0, SAMPLE_RATE) == pytest.approx(0.0, abs=0.1)


def test_a_cut_is_the_mirror_image_of_a_boost():
    boost = filters.shelf(250.0, SAMPLE_RATE, 9.0, False)
    cut = filters.shelf(250.0, SAMPLE_RATE, -9.0, False)
    for freq in (30.0, 250.0, 900.0, 8000.0):
        assert response_db(boost, freq, SAMPLE_RATE) == pytest.approx(-response_db(cut, freq, SAMPLE_RATE), abs=1e-9)


def test_bandpass_has_unity_gain_at_its_centre_and_falls_away_on_both_sides():
    centre = 6000.0
    design = filters.bandpass(centre, SAMPLE_RATE, 2.0)

    assert response_db(design, centre, SAMPLE_RATE) == pytest.approx(0.0, abs=1e-9)
    assert response_db(design, centre / 2, SAMPLE_RATE) < -9.0
    assert response_db(design, centre * 2, SAMPLE_RATE) < -9.0
    # Second order: 6 dB per octave on either side, once clear of the band.
    assert response_db(design, 100.0, SAMPLE_RATE) - response_db(design, 200.0, SAMPLE_RATE) == pytest.approx(
        -6.02, abs=0.05
    )


def test_a_higher_q_makes_a_narrower_band():
    def width(q: float) -> float:
        design = filters.bandpass(6000.0, SAMPLE_RATE, q)
        inside = [f for f in np.arange(1000.0, 20000.0, 5.0) if response_db(design, f, SAMPLE_RATE) >= -3.0103]
        return inside[-1] - inside[0]

    assert width(1.0) > 1.9 * width(2.0) > 3.6 * width(4.0)


@pytest.mark.parametrize("freq", [30.0, 250.0, 1000.0, 3000.0, 5000.0, 8000.0, 12000.0, 20000.0])
def test_bandpass_never_turns_the_phase_by_more_than_a_quarter_cycle(freq):
    # The de-esser relies on this: taking part of the band away can then only reduce.
    b, a = filters.bandpass(6324.6, SAMPLE_RATE, 2.108)
    z = np.exp(-2j * np.pi * freq / SAMPLE_RATE)
    h = (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    assert h.real >= -1e-12


# --- the filter ------------------------------------------------------------------

DESIGNS = {
    "highpass at the bottom of its range": filters.highpass(20.1, SAMPLE_RATE),
    "highpass 80 Hz": filters.highpass(80.0, SAMPLE_RATE),
    "highpass 500 Hz": filters.highpass(500.0, SAMPLE_RATE),
    "lowpass 1 kHz": filters.lowpass(1000.0, SAMPLE_RATE),
    "lowpass 12 kHz, the smallest poles": filters.lowpass(12000.0, SAMPLE_RATE),
    "lowpass 20 kHz": filters.lowpass(20000.0, SAMPLE_RATE),
    "bass +13 dB": filters.shelf(250.0, SAMPLE_RATE, 13.0, False),
    "bass -128 dB": filters.shelf(250.0, SAMPLE_RATE, -128.0, False),
    "bass +128 dB": filters.shelf(250.0, SAMPLE_RATE, 128.0, False),
    "treble +128 dB": filters.shelf(4000.0, SAMPLE_RATE, 128.0, True),
    "treble -128 dB": filters.shelf(4000.0, SAMPLE_RATE, -128.0, True),
    "de-esser band": filters.bandpass(6324.6, SAMPLE_RATE, 2.108),
    "lowpass at 16 kHz sampling": filters.lowpass(7000.0, 16000),
}


def run(biquad: Biquad, x: np.ndarray, sizes: list[int]) -> np.ndarray:
    blocks = []
    start = 0
    i = 0
    while start < len(x):
        size = sizes[i % len(sizes)]
        blocks.append(biquad.process(x[start : start + size]))
        start += size
        i += 1
    return np.concatenate(blocks)


@pytest.mark.parametrize("name", list(DESIGNS))
@pytest.mark.parametrize("sizes", [[1024], [128], [4096], [1], [300, 1024, 17, 5000]])
def test_filter_matches_the_loop(name, sizes):
    b, a = DESIGNS[name]
    x = noise(8000 if sizes == [1] else 40000)
    expected, _ = reference_dsp.biquad(x, b, a, reference_dsp.biquad_settled_state(b, a, x[0]))

    out = run(Biquad((b, a), x[0]), x, sizes)

    assert out.dtype == np.float64
    assert np.max(np.abs(out - expected)) <= 1e-9 * max(1.0, np.max(np.abs(expected)))


@pytest.mark.parametrize("name", list(DESIGNS))
def test_filter_does_not_overflow_on_a_long_buffer(name):
    b, a = DESIGNS[name]
    x = noise(200_000)
    expected, _ = reference_dsp.biquad(x, b, a, reference_dsp.biquad_settled_state(b, a, x[0]))

    with np.errstate(all="raise"):
        out = Biquad((b, a), x[0]).process(x)

    assert np.all(np.isfinite(out))
    assert np.max(np.abs(out - expected)) <= 1e-9 * max(1.0, np.max(np.abs(expected)))


def test_filter_starts_settled_on_its_first_sample():
    # A steady input is what the filter was told to expect, so nothing happens.
    low = Biquad(filters.lowpass(1000.0, SAMPLE_RATE), 0.4)
    assert low.process(np.full(2000, 0.4)) == pytest.approx(0.4, abs=1e-12)

    # A high-pass removes a steady level altogether. What is left is rounding.
    high = Biquad(filters.highpass(80.0, SAMPLE_RATE), 0.4)
    assert np.max(np.abs(high.process(np.full(2000, 0.4)))) < 1e-10


def test_filter_keeps_its_state_when_redesigned():
    x = noise(8192)
    b, a = filters.lowpass(1000.0, SAMPLE_RATE)
    expected_first, _ = reference_dsp.biquad(x[:4096], b, a, reference_dsp.biquad_settled_state(b, a, x[0]))

    biquad = Biquad((b, a), x[0])
    first = biquad.process(x[:4096])
    biquad.set_coefficients(filters.lowpass(1200.0, SAMPLE_RATE))
    second = biquad.process(x[4096:])

    assert np.max(np.abs(first - expected_first)) < 1e-9
    # No jump where the design changes: the step is no larger than the steps around it.
    steps = np.abs(np.diff(np.concatenate([first[-50:], second[:50]])))
    assert steps[49] <= 1.5 * np.max(np.delete(steps, 49))


def test_filter_accepts_single_precision_and_empty_buffers():
    biquad = Biquad(filters.lowpass(1000.0, SAMPLE_RATE), 0.0)
    assert len(biquad.process(np.zeros(0, dtype=np.float32))) == 0
    out = biquad.process(noise(512).astype(np.float32))
    assert out.dtype == np.float64
    assert np.all(np.isfinite(out))


def test_silence_after_sound_decays_to_nothing():
    biquad = Biquad(filters.lowpass(12000.0, SAMPLE_RATE), 0.0)
    biquad.process(noise(4096))
    for _ in range(20):
        tail = biquad.process(np.zeros(4096))
    assert np.max(np.abs(tail)) < 1e-100


# --- in the chain ------------------------------------------------------------------


def test_filters_are_designed_once_per_setting(monkeypatch):
    designs = []
    original = filters.shelf
    monkeypatch.setattr(dsp.filters, "shelf", lambda *a: designs.append(a) or original(*a))
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_bass(6.0)
    chain.reset()
    block = noise(1024).astype(np.float32)

    for _ in range(5):
        chain.process(block)
    assert designs == [(250, SAMPLE_RATE, 6.0, False)]

    chain.set_bass(7.0)
    chain.process(block)
    chain.process(block)
    assert designs[1:] == [(250, SAMPLE_RATE, 7.0, False)]


def test_filters_are_designed_again_when_the_sample_rate_changes(monkeypatch):
    designs = []
    original = filters.highpass
    monkeypatch.setattr(dsp.filters, "highpass", lambda *a: designs.append(a) or original(*a))
    chain = EffectsChain(48000)
    chain.set_high_pass_enabled(True)
    chain.set_low_cut(120.0)
    block = noise(1024).astype(np.float32)

    chain.process(block)
    chain.set_sample_rate(44100)
    chain.process(block)

    assert designs == [(120.0, 48000), (120.0, 44100)]


def test_a_filter_that_is_switched_off_starts_afresh_when_switched_on_again():
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_bass(6.0)
    chain.reset()
    chain.process(noise(1024).astype(np.float32))
    assert "bass" in chain.filter_states

    chain.set_bass(0.0)
    chain.process(noise(1024).astype(np.float32))

    assert "bass" not in chain.filter_states


def test_the_signal_chain_does_not_need_scipy():
    import subprocess
    import sys
    from pathlib import Path

    code = (
        "import sys, openvchange.dsp, openvchange.formant, openvchange.filters; "
        "sys.exit('scipy was imported' if any(m.split('.')[0] == 'scipy' for m in sys.modules) else 0)"
    )
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
