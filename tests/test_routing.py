"""Links between devices: what they add, and how they cope with clocks that disagree."""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from openvchange.routing import LIMIT_KNEE, Link, limit
from tests.helpers import SAMPLE_RATE, sine

REPO_ROOT = Path(__file__).resolve().parent.parent
BLOCK = 1024


def test_importing_routing_does_not_pull_in_qt_or_pyaudio():
    code = (
        "import sys, openvchange.routing; "
        "loaded = [m for m in ('PySide6', 'pyaudio') if m in sys.modules]; "
        "sys.exit(f'unexpected imports: {loaded}' if loaded else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def run(
    link: Link,
    x: np.ndarray,
    block: int = BLOCK,
    input_speed: float = 1.0,
    bursts: int = 1,
    input_block: int | None = None,
) -> np.ndarray:
    """Push `x` through a link whose two ends each run on a clock of their own.

    The output takes `block` samples at a time, in groups of `bursts`, as devices do
    when the blocks are short. The input delivers the same amount per group, in pieces
    of `input_block`, and `input_speed` groups for each one the output takes.
    """
    input_block = input_block or block
    per_group = block * bursts
    out = []
    written = 0
    due = 0.0
    while True:
        due += input_speed
        while due >= 1:
            if written + per_group > len(x):
                return np.concatenate(out)
            for start in range(written, written + per_group, input_block):
                link.write(x[start : start + input_block])
            written += per_group
            due -= 1
        out.extend(link.read(block) for _ in range(bursts))


def start_of_sound(x: np.ndarray) -> int:
    return int(np.flatnonzero(x)[0])


def test_link_with_agreeing_clocks_passes_audio_through_unchanged():
    x = sine(440.0, 0.5, seconds=2.0).astype(np.float32)
    link = Link(BLOCK, SAMPLE_RATE)

    out = run(link, x)

    delay = start_of_sound(out) - start_of_sound(x)
    assert delay == link.target - BLOCK  # the first block was written just before it was read
    assert np.array_equal(out[delay:], x[: len(out) - delay])


def test_link_gives_silence_until_enough_is_waiting():
    link = Link(BLOCK, SAMPLE_RATE)
    link.write(np.ones(link.target - 1, dtype=np.float32))
    assert not link.read(BLOCK).any()

    link.write(np.ones(1, dtype=np.float32))
    assert link.read(BLOCK).all()


def test_link_delay_does_not_shrink_below_a_device_period_for_small_buffers():
    assert Link(128, 48000).target == 2 * 480
    assert Link(1024, 48000).target == 2048


@pytest.mark.parametrize("input_speed", [1.0005, 0.9995, 1.0001, 0.9999])
@pytest.mark.parametrize(("block", "bursts"), [(1024, 1), (128, 4)])
def test_link_absorbs_clock_drift_without_a_gap_or_a_jump(input_speed, block, bursts):
    freq = 300.0
    x = sine(freq, 0.5, seconds=120.0).astype(np.float32)
    link = Link(block, SAMPLE_RATE)

    out = run(link, x, block, input_speed, bursts)

    heard = out[start_of_sound(out) :]
    steepest = 0.5 * 2 * np.pi * freq / SAMPLE_RATE
    # A gap would show as a step down to zero, a dropped stretch as a step elsewhere.
    assert np.max(np.abs(np.diff(heard))) < steepest * 1.02
    assert link.flowing
    assert 0 < link.fill <= link.most


@pytest.mark.parametrize("input_speed", [1.0005, 0.9995])
@pytest.mark.parametrize(("block", "bursts", "input_block"), [(1024, 1, 256), (256, 4, 1024)])
def test_link_copes_with_ends_that_use_different_buffer_sizes(input_speed, block, bursts, input_block):
    freq = 300.0
    x = sine(freq, 0.5, seconds=120.0).astype(np.float32)
    link = Link(max(block, input_block), SAMPLE_RATE)

    out = run(link, x, block, input_speed, bursts, input_block)

    heard = out[start_of_sound(out) :]
    steepest = 0.5 * 2 * np.pi * freq / SAMPLE_RATE
    assert np.max(np.abs(np.diff(heard))) < steepest * 1.02
    assert link.flowing


def test_link_makes_up_for_drift_a_sample_at_a_time_and_then_leaves_the_audio_alone():
    x = sine(300.0, 0.5, seconds=120.0).astype(np.float32)
    link = Link(BLOCK, SAMPLE_RATE)
    corrections = []
    read = link.read
    link.read = lambda count: (read(count), corrections.append(link.correction))[0]

    run(link, x, input_speed=1.0005)

    # 500 parts per million over two minutes is 2880 samples: the input got two whole
    # blocks ahead, and each was worked off over about a thousand reads.
    assert set(corrections) == {0, 1}
    assert 2 * BLOCK <= sum(corrections) < 2.5 * BLOCK
    assert sum(corrections) < 0.5 * len(corrections)


def test_link_that_runs_empty_pads_with_silence_and_then_recovers():
    link = Link(BLOCK, SAMPLE_RATE)
    link.write(np.ones(link.target, dtype=np.float32))
    assert link.read(BLOCK).all()
    assert link.read(BLOCK).all()

    starved = link.read(BLOCK)
    assert not starved.any()
    assert not link.flowing

    link.write(np.ones(BLOCK, dtype=np.float32))
    assert not link.read(BLOCK).any()  # waits until the usual amount is there again
    link.write(np.ones(BLOCK, dtype=np.float32))
    assert link.read(BLOCK).all()


def test_link_whose_reader_stalls_keeps_the_newest_audio():
    link = Link(BLOCK, SAMPLE_RATE)
    for value in range(1, 22):
        link.write(np.full(BLOCK, value, dtype=np.float32))

    assert link.fill <= link.capacity
    assert link.read(BLOCK)[0] == 20  # the usual delay, not everything that piled up
    assert link.read(BLOCK)[0] == 21


def test_limit_leaves_everything_below_the_knee_alone():
    x = np.linspace(-LIMIT_KNEE, LIMIT_KNEE, 1001, dtype=np.float32)
    assert np.array_equal(limit(x), x)


def test_limit_never_exceeds_full_scale_and_keeps_the_order_of_levels():
    x = np.linspace(-6.0, 6.0, 4001, dtype=np.float32)
    y = limit(x)
    assert np.max(np.abs(y)) <= 1.0
    assert np.all(np.diff(y) >= 0)
    assert np.max(np.diff(y)) <= np.max(np.diff(x)) * 1.001  # no step at the knee
