"""Time the effects chain against the real-time budget.

The engine gets one buffer's worth of time to process each buffer. Anything slower than
that causes dropouts, and the closer the chain gets to the budget the more likely another
thread is to push it over.

    poetry run python scripts/benchmark.py
    poetry run python scripts/benchmark.py --buffer 256 --rate 44100
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openvchange.dsp import EffectsChain


def dynamics(chain: EffectsChain) -> None:
    chain.set_expander_enabled(True)
    chain.set_compressor_enabled(True)
    chain.set_deesser_enabled(True)


def filters(chain: EffectsChain) -> None:
    chain.set_high_pass_enabled(True)
    chain.set_low_pass_enabled(True)
    chain.set_bass(6.0)
    chain.set_treble(3.0)


def everything(chain: EffectsChain) -> None:
    dynamics(chain)
    filters(chain)
    chain.set_pitch(4.0)
    chain.set_formant(-2.0)
    chain.set_formant_preserve(True)
    chain.set_delay(50.0)
    chain.set_gain(3.0)


def eight_voices(chain: EffectsChain) -> None:
    chain.set_pitch_num_voices(8)
    chain.set_pitch(4.0)


SCENARIOS = {
    "gain only": lambda chain: None,
    "delay": lambda chain: chain.set_delay(50.0),
    "filters and tone": filters,
    "expander, compressor, de-esser": dynamics,
    "pitch shift, 4 voices": lambda chain: chain.set_pitch(4.0),
    "pitch shift, 8 voices": eight_voices,
    "formant shift": lambda chain: chain.set_formant(3.0),
    "everything on": everything,
}


def test_signal(n: int, sample_rate: int) -> np.ndarray:
    rng = np.random.default_rng(0)
    t = np.arange(n) / sample_rate
    tone = sum((0.3 / k) * np.sin(2 * np.pi * 150 * k * t) for k in range(1, 10))
    return (tone + 0.02 * rng.standard_normal(n)).astype(np.float32)


def measure(configure, buffer: int, sample_rate: int, repeat: int) -> list[float]:
    chain = EffectsChain(sample_rate)
    configure(chain)
    chain.reset()
    signal = test_signal(buffer * (repeat + 5), sample_rate)
    blocks = [signal[i : i + buffer] for i in range(0, len(signal), buffer)]

    for block in blocks[:5]:
        chain.process(block)

    times = []
    for block in blocks[5:]:
        started = time.perf_counter()
        chain.process(block)
        times.append((time.perf_counter() - started) * 1000)
    return times


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--buffer", type=int, default=1024, help="samples per buffer (default 1024)")
    parser.add_argument("--rate", type=int, default=48000, help="sample rate in Hz (default 48000)")
    parser.add_argument("--repeat", type=int, default=100, help="buffers to time per scenario (default 100)")
    args = parser.parse_args()

    budget = args.buffer / args.rate * 1000
    print(f"{args.buffer} samples at {args.rate} Hz: budget {budget:.2f} ms per buffer\n")
    print(f"{'scenario':<34}{'median':>10}{'worst':>10}{'of budget':>12}")
    for name, configure in SCENARIOS.items():
        times = measure(configure, args.buffer, args.rate, args.repeat)
        median = statistics.median(times)
        print(f"{name:<34}{median:>8.2f}ms{max(times):>8.2f}ms{median / budget:>11.0%}")


if __name__ == "__main__":
    main()
