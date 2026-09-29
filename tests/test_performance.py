"""The chain has to keep up with real time, with room to spare.

Timing tests are noisy, so the limit is deliberately loose: half of the time available.
The chain normally needs a few percent of it. A Python loop over every sample would need
most or all of it, and that is what this guards against.
"""

import statistics
import time

import numpy as np
import pytest

from openvchange.dsp import EffectsChain

SAMPLE_RATE = 48000


def everything_on(voices: int) -> EffectsChain:
    chain = EffectsChain(SAMPLE_RATE)
    chain.set_pitch_num_voices(voices)
    chain.set_gain(3.0)
    chain.set_bass(6.0)
    chain.set_treble(3.0)
    chain.set_pitch(4.0)
    chain.set_formant(-2.0)
    chain.set_formant_preserve(True)
    chain.set_delay(50.0)
    chain.set_high_pass_enabled(True)
    chain.set_low_pass_enabled(True)
    chain.set_expander_enabled(True)
    chain.set_compressor_enabled(True)
    chain.set_deesser_enabled(True)
    chain.reset()
    return chain


@pytest.mark.parametrize("voices", [4, 8])
@pytest.mark.parametrize("buffer", [256, 1024])
def test_full_chain_uses_less_than_half_the_time_available(buffer, voices):
    chain = everything_on(voices)
    rng = np.random.default_rng(0)
    blocks = [rng.uniform(-0.5, 0.5, buffer).astype(np.float32) for _ in range(40)]
    for block in blocks[:10]:
        chain.process(block)

    times = []
    for block in blocks[10:]:
        started = time.perf_counter()
        chain.process(block)
        times.append(time.perf_counter() - started)

    available = buffer / SAMPLE_RATE
    assert statistics.median(times) < 0.5 * available
