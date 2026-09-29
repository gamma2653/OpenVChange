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
    "formant_semitones": 0.0,
    "formant_preserve": False,
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
    fx.set_formant(s["formant_semitones"])
    fx.set_formant_preserve(bool(s["formant_preserve"]))
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


def distortion_percent(x: np.ndarray, freq: float, sample_rate: int = SAMPLE_RATE) -> float:
    """Harmonics two to ten relative to the fundamental, measured on the settled half.

    `freq` must fit a whole number of cycles into that half, so no window is needed.
    """
    settled = tail(np.asarray(x, dtype=np.float64))
    cycles = freq * len(settled) / sample_rate
    assert abs(cycles - round(cycles)) < 1e-9, "frequency does not fit the analysis length"
    spectrum = np.abs(np.fft.rfft(settled))
    k = round(cycles)
    harmonics = [spectrum[k * m] for m in range(2, 11) if k * m < len(spectrum)]
    return 100.0 * float(np.sqrt(np.sum(np.square(harmonics))) / spectrum[k])


# --- synthetic vowels --------------------------------------------------------

# Centre frequency and bandwidth of each resonance, roughly an "ah".
VOWEL_FORMANTS = ((700.0, 110.0), (1200.0, 120.0), (2600.0, 160.0), (3500.0, 200.0))


def resonate(x: np.ndarray, freq: float, bandwidth: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """A two-pole resonance with unity gain at its centre."""
    r = np.exp(-np.pi * bandwidth / sample_rate)
    theta = 2 * np.pi * freq / sample_rate
    a1, a2 = -2 * r * np.cos(theta), r * r
    out = []
    y1 = y2 = 0.0
    for value in x.tolist():
        y0 = value - a1 * y1 - a2 * y2
        out.append(y0)
        y2, y1 = y1, y0
    at_centre = np.exp(1j * theta)
    return np.array(out) / abs(1 / (1 + a1 / at_centre + a2 / at_centre**2))


def buzz(pitch: float, seconds: float = 1.5, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """The sound of vocal cords alone: every harmonic of the pitch, with slight vibrato."""
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    phase = 2 * np.pi * np.cumsum(pitch * (1 + 0.01 * np.sin(2 * np.pi * 5 * t))) / sample_rate
    return sum(np.sin(k * phase + k) / k**0.7 for k in range(1, int(sample_rate / 2.2 / pitch)))


def vowel(source: np.ndarray, formant_ratio: float = 1.0, peak: float = 0.3) -> np.ndarray:
    """`source` shaped by the resonances of a vowel, optionally moved by a ratio."""
    shaped = sum(resonate(source, f * formant_ratio, b * formant_ratio) for f, b in VOWEL_FORMANTS)
    return (peak * shaped / np.max(np.abs(shaped))).astype(np.float32)


def harmonic_levels_db(x: np.ndarray, pitch: float, up_to: float = 4500.0) -> np.ndarray:
    """Level of each harmonic of `pitch`, measured on the last two thirds of the signal.

    Each level is the energy in a band around the harmonic, not the height of one peak.
    Vibrato spreads a harmonic over several peaks, and can empty the middle one.
    """
    settled = np.asarray(x, dtype=np.float64)[len(x) // 3 :]
    power = np.abs(np.fft.rfft(settled * np.hanning(len(settled)))) ** 2
    hz_per_bin = SAMPLE_RATE / len(settled)
    half_band = round(0.25 * pitch / hz_per_bin)
    levels = []
    k = 1
    while k * pitch < up_to:
        centre = round(k * pitch / hz_per_bin)
        levels.append(power[centre - half_band : centre + half_band + 1].sum())
        k += 1
    return 10 * np.log10(np.array(levels) + 1e-20)


def shape_difference_db(a: np.ndarray, b: np.ndarray) -> float:
    """How differently two sets of levels are shaped, whatever their overall level."""
    difference = a - b
    return float(np.sqrt(np.mean((difference - np.mean(difference)) ** 2)))


def outline_db(x: np.ndarray, low: float = 300.0, high: float = 4500.0, width: float = 300.0) -> np.ndarray:
    """The long-term spectrum smoothed over `width` Hz: its outline without the pitch.

    Read every 50 Hz from `low` to `high`, so outlines of signals of different lengths
    can be compared.
    """
    settled = np.asarray(x, dtype=np.float64)[len(x) // 3 :]
    power = np.abs(np.fft.rfft(settled * np.hanning(len(settled)))) ** 2
    hz_per_bin = SAMPLE_RATE / len(settled)
    span = max(1, round(width / hz_per_bin))
    smooth = np.convolve(power, np.ones(span) / span, mode="same")
    wanted = np.arange(low, high, 50.0)
    return 10 * np.log10(np.interp(wanted, np.arange(len(smooth)) * hz_per_bin, smooth) + 1e-20)
