"""The signal processing module must stay usable without Qt or an audio backend."""

import subprocess
import sys
from pathlib import Path

import numpy as np

from openvchange.dsp import EffectsChain

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_importing_dsp_does_not_pull_in_qt_or_pyaudio():
    code = (
        "import sys, openvchange.dsp; "
        "loaded = [m for m in ('PySide6', 'pyaudio') if m in sys.modules]; "
        "sys.exit(f'unexpected imports: {loaded}' if loaded else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_chain_processes_float_buffers_directly():
    chain = EffectsChain(sample_rate=48000)
    chain.set_gain(-6.0)
    chain.reset()
    x = np.full(2048, 0.5, dtype=np.float32)

    out = chain.process(x)

    assert out.shape == x.shape
    assert abs(out[-1] - np.tanh(0.5 * 10 ** (-6 / 20))) < 1e-6


def test_reset_keeps_settings_but_clears_history():
    chain = EffectsChain(sample_rate=48000)
    chain.set_delay(20.0)
    chain.set_pitch(3.0)
    chain.reset()
    chain.process(np.full(4096, 0.3, dtype=np.float32))

    chain.reset()

    assert chain.delay_ms == 20.0
    assert chain.pitch_semitones == 3.0
    assert not chain.delay_buffer.any()
    assert not chain.pitch_buffer.any()
    assert chain.filter_states == {}
