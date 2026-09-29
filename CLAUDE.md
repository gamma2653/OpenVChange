# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenVChange is a virtual audio routing and real-time DSP application written in Python. It captures audio from an input device, applies configurable real-time filters/effects, and routes processed audio to an output device via a PySide6 GUI.

## Commands

```bash
# Install dependencies
poetry install

# Run the application
poetry run openvchange

# Build a standalone one-file Windows executable (output: dist/OpenVChange-<version>.exe)
poetry run pyinstaller openvchange.spec

# Lint and test (both run in CI on every pull request)
poetry run ruff check .
poetry run pytest

# Time the effects chain against the real-time budget
poetry run python scripts/benchmark.py

# Record a user-facing change for the next release (needs Node 22.11+)
npm run changeset
```

CI and release builds use Python 3.12. The locked NumPy (1.26) has no wheels for Python 3.13, and a source build of it crashes on the GitHub runners. Moving to Python 3.13 there means upgrading to NumPy 2 first.

## Testing

- Tests live in `tests/` and run headless; `tests/conftest.py` selects Qt's offscreen platform
- `pyaudio.PyAudio` is replaced by `tests/fakes.py` for every test, so nothing opens a real audio device. Never open a real stream from a test: it would route the microphone to the speakers
- Effects are tested by feeding synthetic signals through the engine and measuring the result (`tests/helpers.py`). Settings are passed in engine units (dB, Hz, ms, semitones)
- Output must not depend on the buffer size; `test_output_does_not_depend_on_the_buffer_size` guards that
- `tests/reference_dsp.py` holds the original sample-by-sample implementations. Optimised code in `dsp.py` must match them exactly (`tests/test_matches_reference.py`), so an optimisation never changes the sound

## Releases

Releases are driven by Changesets. `package.json` is the version source of truth and exists only for that purpose; the app has no JavaScript.

- User-facing changes should include a changeset file in `.changeset/` (frontmatter `"openvchange": patch|minor|major`, then a one-line summary)
- Never edit the version in `pyproject.toml` by hand; `scripts/sync-version.mjs` copies it from `package.json`, and CI fails if they differ
- `.github/workflows/release.yml` opens a "Version OpenVChange" pull request while changesets are pending, then builds the exe and publishes a GitHub release tagged `v<version>` once that pull request is merged
- `changeset init` and `changeset add` are interactive; write changeset files directly when working non-interactively

## Architecture

The codebase has three modules:

**`openvchange/__main__.py`** - GUI layer using PySide6/Qt
- `MainWindow`: Orchestrates UI components and AudioProcessor
- Device selection (input/output combo boxes)
- Filter control sliders/checkboxes for all DSP parameters
- Input and output level meters with peak hold and clip lights
- Start/Stop/Reset controls
- Effect parameters are set on `self.effects` (the chain); stream settings on `self.audio_processor`

**`openvchange/audio.py`** - Audio streaming
- `AudioProcessor`: Qt QObject with callback-based PyAudio streaming
- Full-duplex audio (simultaneous input/output)
- Converts 16-bit PCM to float and back, emits the level meter signal, and handles the master bypass
- Owns an `EffectsChain` as `.effects`
- Owns the only `PyAudio` instance (`.pa`). PortAudio scans for devices once, when its first instance is created, and further instances share that scan. Creating a second instance therefore finds nothing new; `refresh_devices()` shuts PortAudio down and starts it again, which is only possible while no stream is open
- Device indexes change on every refresh. Identify a device by `Device.identity` (name and host API) whenever it has to be found again

**`openvchange/dsp.py`** - Signal processing
- `EffectsChain`: every effect, working on float32 NumPy arrays
- Must not import Qt or PyAudio (a test enforces this), so it can be tested and reused on its own
- `reset()` clears all history when a stream starts; `reset_effect_states()` clears only filter and envelope state and is used by the bypass
- Stateful filter implementation using `scipy.lfilter` with `lfilter_zi` for continuous processing without clicks/pops

**`openvchange/presets.py`** - Preset files
- Reads, checks, and writes presets; no Qt
- `MainWindow.preset_controls()` maps each preset key to its control and is the single list that saving, loading, and checking all use. A new setting only needs an entry there
- A preset is checked in full before anything is applied. Wrong types refuse the preset; out-of-range numbers are clamped and reported
- Preset keys and their units (slider units, not engine units) are a file format. Do not rename keys or change what a value means: users have presets on disk

**`openvchange/builtin_presets.py`** - Presets that come with the app
- `BUILT_IN` maps names to complete presets, defined with `preset(...)` as changes to `NEUTRAL`
- A built-in preset sets every effect and none of the session settings (master switch, buffer size, pitch voices)
- The list in the window is never set directly: `show_matching_builtin_preset()` runs whenever a control changes and shows the preset the controls match, or Custom
- Tests check that every preset fits the controls and leaves headroom on a voice at a normal level. They cannot check how a preset sounds

**`openvchange/hotkey.py`** - System-wide shortcut (Windows only)
- `GlobalHotkey` registers one shortcut with `RegisterHotKey` for the GUI thread and hears about presses through a native event filter. No window handle is involved
- No shortcut is set by default: Ctrl+Alt plus a letter types a character on many keyboard layouts, and any default could clash with another application
- Tests replace the backend with a fake (`tests/conftest.py`). Presses are tested by posting the real `WM_HOTKEY` message to the thread. Never simulate key presses in a test: they would go to whatever has the focus on the machine running the tests

**`openvchange/settings.py`** - What is remembered between launches
- Devices (by identity), the device filter, and the effect settings, as `settings.json` in the per-user configuration folder (`%APPDATA%\OpenVChange` on Windows)
- The effect settings inside it have the same form as a preset and go through the same checks
- Saved when the window closes, restored after the device lists are filled. A damaged file is reported in the status line and never prevents startup
- Tests redirect `settings.default_path` to a temporary folder (`tests/conftest.py`), so they never read or write real settings

## Audio Processing Pipeline

Signal flow (in order):
1. Input capture → int16 to float32 normalization
2. Noise Gate (RMS-based threshold)
3. High-Pass Filter (Butterworth, 20-500 Hz)
4. Low-Pass Filter (Butterworth, 1000-20000 Hz)
5. Bass Shelf Filter (biquad, ±12 dB)
6. Treble Shelf Filter (biquad, ±12 dB)
7. Pitch Shift (4-voice delay-line with Hann window crossfade)
8. Gain application (-20 to +20 dB)
9. Soft clipping → float32 to int16 output

## Technical Specs

- Sample Rate: 44100 Hz
- Buffer Size: 1024 samples
- Audio Format: 16-bit PCM
- Filter Design: 2nd-order Butterworth (HP/LP), biquad shelving (bass/treble)

## Key Implementation Details

- The Main tab's "Enable Effects" checkbox sets `AudioProcessor.effects_enabled`; when off, `apply_filters()` returns the input bytes untouched (after emitting the level meter signal) and calls `reset_effect_states()` so re-enabling starts clean
- Filter coefficients are cached by `EffectsChain.coefficients()` and redesigned only when the settings behind them, or the sample rate, change
- The audio callback has one buffer's worth of time per buffer (21 ms at 1024 samples and 48 kHz). Avoid per-sample Python loops over NumPy arrays in `dsp.py`; they are what made the engine miss that budget
- Pitch shift uses circular buffer with 4 overlapping read pointers and crossfade to reduce artifacts
- Dynamics processors measure level with a follower (`dsp.follow`), never from single samples: a waveform crosses zero twice per cycle, so per-sample level detection turns down signals that are well above the threshold
- De-esser: split-band. It subtracts part of a band-passed copy of the signal (`DEESSER_CENTER_HZ`, `DEESSER_Q`), so everything outside the band passes unchanged. The band filter must stay second order: its phase then never turns by more than a quarter cycle, which is what guarantees the subtraction cannot boost
- Expander: attack is how fast the gate opens, release how fast it closes. Its gain is smoothed in dB and bottoms out at `EXPANDER_FLOOR_DB`
- The engine emits `levels_changed` with a `Levels` object about 30 times per second of audio, whatever the buffer size, keeping the highest peak in between. It is emitted from the audio thread; Qt queues it to the GUI thread
- `LevelMeter` (`widgets.py`) is told how much audio each update covers and keeps time by that, not by the wall clock, so its behaviour can be tested exactly
- The output clip light means the signal reached the soft clipper at or above full scale (`EffectsChain.peak_before_clipping`). The output itself never reaches full scale, because `tanh` does not
- PyAudio callback runs in separate thread; use Qt signals to communicate with GUI
- Buffer size and pitch voice count are stream settings: the engine reads them while processing, so `MainWindow.apply_stream_settings()` only passes them on while the stream is stopped
- The callback must never raise and must never return the input on failure: for a voice changer, leaking the unprocessed voice is worse than silence. On an error it returns silence and emits `error_occurred`, and the window stops the stream
- `AudioProcessor.start()` raises `AudioStartError` with a message fit for the status line. The packaged app has no console, so `print` reaches nobody; use `logging` for detail and the status line for the user
