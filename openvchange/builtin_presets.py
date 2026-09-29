"""Presets that come with the app.

Values are in the units of the controls, exactly as in a preset file: pitch in tenths
of a semitone, ratios in tenths, everything else in the unit its slider shows.

A built-in preset sets every effect, so choosing one after another never leaves
something behind from the first. It does not touch the master switch, the buffer size,
or the number of pitch voices, which are about the session and not about the sound.

The presets that shift the pitch add a few dB of gain, because the pitch shifter lowers
the level, so that changing presets does not change the loudness much.
"""

from __future__ import annotations

# Every effect at its neutral value. Also what "Reset to Defaults" restores.
NEUTRAL = {
    "gain": 0,
    "bass": 0,
    "treble": 0,
    "pitch": 0,
    "delay": 0,
    "high_pass_enabled": False,
    "high_pass_freq": 80,
    "low_pass_enabled": False,
    "low_pass_freq": 16000,
    "expander_enabled": False,
    "expander_threshold": 1,
    "expander_ratio": 20,
    "expander_attack": 5,
    "expander_release": 100,
    "compressor_enabled": False,
    "compressor_threshold": -10,
    "compressor_ratio": 40,
    "compressor_attack": 10,
    "compressor_release": 100,
    "compressor_makeup": 0,
    "deesser_enabled": False,
    "deesser_threshold": -20,
    "deesser_reduction": 6,
}

# Settings of the session, restored by "Reset to Defaults" along with the effects.
SESSION_DEFAULTS = {
    "effects_enabled": True,
    "buffer_size": 1024,
    "pitch_voices": 4,
}


def preset(**changes: int | bool) -> dict[str, int | bool]:
    """A complete preset: neutral, except for `changes`."""
    unknown = set(changes) - set(NEUTRAL)
    if unknown:
        raise KeyError(f"not a setting: {sorted(unknown)}")
    return {**NEUTRAL, **changes}


# A gentle gate, for the presets that add gain and would otherwise raise the noise too.
GATE = {
    "expander_enabled": True,
    "expander_threshold": 1,
    "expander_ratio": 20,
    "expander_attack": 3,
    "expander_release": 150,
}

BUILT_IN: dict[str, dict[str, int | bool]] = {
    "Neutral": preset(),
    "Clean voice": preset(
        **GATE,
        treble=2,
        high_pass_enabled=True,
        high_pass_freq=90,
        compressor_enabled=True,
        compressor_threshold=-18,
        compressor_ratio=30,
        compressor_attack=10,
        compressor_release=120,
        compressor_makeup=3,
        deesser_enabled=True,
        deesser_threshold=-24,
        deesser_reduction=5,
    ),
    "Radio announcer": preset(
        **GATE,
        bass=5,
        treble=3,
        high_pass_enabled=True,
        high_pass_freq=70,
        compressor_enabled=True,
        compressor_threshold=-22,
        compressor_ratio=45,
        compressor_attack=8,
        compressor_release=150,
        compressor_makeup=4,
        deesser_enabled=True,
        deesser_threshold=-22,
        deesser_reduction=6,
    ),
    "Telephone": preset(
        bass=-6,
        high_pass_enabled=True,
        high_pass_freq=300,
        low_pass_enabled=True,
        low_pass_freq=3400,
        compressor_enabled=True,
        compressor_threshold=-24,
        compressor_ratio=60,
        compressor_attack=5,
        compressor_release=80,
        compressor_makeup=8,
    ),
    "Deep voice": preset(
        gain=3,
        pitch=-40,
        bass=4,
        high_pass_enabled=True,
        high_pass_freq=60,
        compressor_enabled=True,
        compressor_threshold=-18,
        compressor_ratio=30,
        compressor_makeup=2,
    ),
    "Giant": preset(
        gain=5,
        pitch=-80,
        bass=6,
        treble=-3,
        low_pass_enabled=True,
        low_pass_freq=7000,
        compressor_enabled=True,
        compressor_threshold=-20,
        compressor_ratio=40,
        compressor_makeup=2,
    ),
    "Higher voice": preset(
        gain=6,
        pitch=40,
        bass=-2,
        treble=2,
        high_pass_enabled=True,
        high_pass_freq=120,
    ),
    "Chipmunk": preset(
        gain=4,
        pitch=90,
        treble=3,
        high_pass_enabled=True,
        high_pass_freq=150,
    ),
}
