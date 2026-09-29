"""Helpers for driving the audio engine with synthetic signals.

Settings are given in engine units (dB, Hz, ms, semitones), so tests do not depend on how the
engine happens to expose them. Only `make_processor` knows the engine's API.
"""

from __future__ import annotations

import numpy as np

from openvchange.audio import AudioProcessor

SAMPLE_RATE = 48000

DEFAULTS = {
    "gain_db": 0.0,
    "bass_db": 0.0,
    "treble_db": 0.0,
    "pitch_semitones": 0.0,
    "pitch_voices": 4,
    "delay_ms": 0.0,
    "high_pass_enabled": False,
    "high_pass_hz": 80.0,
    "low_pass_enabled": False,
    "low_pass_hz": 16000.0,
    "expander_enabled": False,
    "expander_threshold_percent": 1.0,
    "expander_ratio": 2.0,
    "expander_attack_ms": 5.0,
    "expander_release_ms": 100.0,
    "compressor_enabled": False,
    "compressor_threshold_db": -10.0,
    "compressor_ratio": 4.0,
    "compressor_attack_ms": 10.0,
    "compressor_release_ms": 100.0,
    "compressor_makeup_db": 0.0,
    "deesser_enabled": False,
    "deesser_threshold_db": -20.0,
    "deesser_reduction_db": 6.0,
}


def make_processor(sample_rate: int = SAMPLE_RATE, **settings: float) -> AudioProcessor:
    """Build an engine with the given settings, in the state it has right after start()."""
    unknown = set(settings) - set(DEFAULTS)
    assert not unknown, f"unknown settings: {sorted(unknown)}"
    s = {**DEFAULTS, **settings}

    p = AudioProcessor()
    p.sample_rate = sample_rate
    fx = p.effects
    fx.set_sample_rate(sample_rate)
    fx.set_pitch_num_voices(int(s["pitch_voices"]))
    fx.set_gain(s["gain_db"])
    fx.set_bass(s["bass_db"])
    fx.set_treble(s["treble_db"])
    fx.set_pitch(s["pitch_semitones"])
    fx.set_delay(s["delay_ms"])
    fx.set_high_pass_enabled(bool(s["high_pass_enabled"]))
    fx.set_low_cut(s["high_pass_hz"])
    fx.set_low_pass_enabled(bool(s["low_pass_enabled"]))
    fx.set_high_cut(s["low_pass_hz"])
    fx.set_expander_enabled(bool(s["expander_enabled"]))
    fx.set_expander_threshold(s["expander_threshold_percent"])
    fx.set_expander_ratio(s["expander_ratio"])
    fx.set_expander_attack(s["expander_attack_ms"])
    fx.set_expander_release(s["expander_release_ms"])
    fx.set_compressor_enabled(bool(s["compressor_enabled"]))
    fx.set_compressor_threshold(s["compressor_threshold_db"])
    fx.set_compressor_ratio(s["compressor_ratio"])
    fx.set_compressor_attack(s["compressor_attack_ms"])
    fx.set_compressor_release(s["compressor_release_ms"])
    fx.set_compressor_makeup(s["compressor_makeup_db"])
    fx.set_deesser_enabled(bool(s["deesser_enabled"]))
    fx.set_deesser_threshold(s["deesser_threshold_db"])
    fx.set_deesser_reduction(s["deesser_reduction_db"])
    fx.reset()
    return p


# --- signals -----------------------------------------------------------------


def to_pcm(x: np.ndarray) -> np.ndarray:
    """Float signal in [-1, 1] to int16 samples."""
    return np.round(np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)


def from_pcm(x: np.ndarray) -> np.ndarray:
    """int16 samples to float, using the engine's own scaling."""
    return x.astype(np.float64) / 32768.0


def sine(freq: float, amplitude: float, seconds: float = 1.0, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    return amplitude * np.sin(2 * np.pi * freq * t)


def voice_like(seconds: float = 1.0, sample_rate: int = SAMPLE_RATE, seed: int = 0) -> np.ndarray:
    """Harmonic tone with syllable-like gaps and bursts of hiss. Exercises every effect."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sample_rate)
    t = np.arange(n) / sample_rate
    f0 = 140 + 25 * np.sin(2 * np.pi * 0.7 * t)
    phase = 2 * np.pi * np.cumsum(f0) / sample_rate
    voiced = sum((1.0 / k) * np.sin(k * phase) for k in range(1, 14))
    envelope = np.clip(np.sin(2 * np.pi * 2.3 * t), 0, None) ** 0.6
    hiss = np.diff(rng.standard_normal(n), prepend=0.0)
    hiss_envelope = np.clip(np.sin(2 * np.pi * 1.1 * t + 1.0), 0, None) ** 4
    x = 0.22 * voiced * envelope + 0.12 * hiss * hiss_envelope + 0.003 * rng.standard_normal(n)
    return np.clip(x, -1.0, 1.0)


# --- running -----------------------------------------------------------------


def process(p: AudioProcessor, x: np.ndarray, chunk: int = 1024) -> np.ndarray:
    """Feed a float signal through the engine buffer by buffer. Returns float output.

    Trailing samples that do not fill a whole buffer are dropped.
    """
    return from_pcm(process_pcm(p, to_pcm(x), chunk))


def process_pcm(p: AudioProcessor, pcm: np.ndarray, chunk: int = 1024) -> np.ndarray:
    """Same as `process` but int16 in, int16 out."""
    blocks = []
    for start in range(0, len(pcm) - chunk + 1, chunk):
        out = p.apply_filters(pcm[start : start + chunk].tobytes())
        blocks.append(np.frombuffer(out, dtype=np.int16))
    return np.concatenate(blocks)


# --- measuring ---------------------------------------------------------------


def db(ratio: float) -> float:
    return 20.0 * np.log10(max(float(ratio), 1e-12))


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def tail(x: np.ndarray, fraction: float = 0.5) -> np.ndarray:
    """The last part of a signal, after filters and envelopes have settled."""
    return x[int(len(x) * (1.0 - fraction)) :]


def level_change_db(out: np.ndarray, reference: np.ndarray) -> float:
    """Steady-state level of `out` relative to `reference`, in dB."""
    n = min(len(out), len(reference))
    return db(rms(tail(out[:n])) / rms(tail(reference[:n])))


def dominant_frequency(x: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    """Frequency of the strongest spectral peak, refined by parabolic interpolation."""
    windowed = x * np.hanning(len(x))
    spectrum = np.abs(np.fft.rfft(windowed))
    k = int(np.argmax(spectrum[1:-1])) + 1
    a, b, c = np.log(spectrum[k - 1 : k + 2] + 1e-20)
    offset = 0.5 * (a - c) / (a - 2 * b + c)
    return (k + offset) * sample_rate / len(x)
