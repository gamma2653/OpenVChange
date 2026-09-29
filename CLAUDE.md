# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenVChange is a real-time voice changer and audio router for Windows, written in Python. It captures audio from an input device, runs it through a chain of effects, and routes the result to an output device. The GUI is PySide6. It is distributed as a single executable built with PyInstaller.

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

# Draw the icon again after changing scripts/make_icon.py
poetry run python scripts/make_icon.py

# Record a user-facing change for the next release (needs Node 22.11+)
npm run changeset
```

CI and release builds use Python 3.12. The locked NumPy (1.26) has no wheels for Python 3.13, so there it is compiled from source, which takes six minutes on the GitHub runners. Moving to Python 3.13 there means upgrading to NumPy 2 first.

## Testing

- Tests live in `tests/` and run headless; `tests/conftest.py` selects Qt's offscreen platform
- `pyaudio.PyAudio` is replaced by `tests/fakes.py` for every test, so nothing opens a real audio device. Never open a real stream from a test: it would route the microphone to the speakers
- Effects are tested by feeding synthetic signals through the engine and measuring the result (`tests/helpers.py`). Settings are passed in engine units (dB, Hz, ms, semitones)
- Output must not depend on the buffer size; `test_output_does_not_depend_on_the_buffer_size` guards that
- `tests/reference_dsp.py` holds plain sample-by-sample implementations of the delay, the gain, the pitch shifter, the compressor, and a second-order filter. The fast code in `dsp.py` and `filters.py` must match them (`tests/test_matches_reference.py`, `tests/test_filters.py`), so an optimisation never changes the sound. When the behaviour of an effect is changed on purpose, change its reference too, or replace it by tests of the new behaviour
- Timing tests are loose on purpose (`tests/test_performance.py`): they catch a loop over every sample, not a slow machine

## Releases

Releases are driven by Changesets. `package.json` is the version source of truth and exists only for that purpose; the app has no JavaScript.

- User-facing changes should include a changeset file in `.changeset/` (frontmatter `"openvchange": patch|minor|major`, then a one-line summary)
- Never edit the version in `pyproject.toml` or `openvchange/__init__.py` by hand; `scripts/sync-version.mjs` copies it from `package.json`, and CI fails if they differ
- The executable is not code-signed. That needs a certificate, which the project does not have
- `.github/workflows/release.yml` opens a "Version OpenVChange" pull request while changesets are pending, then builds the exe and publishes a GitHub release tagged `v<version>` once that pull request is merged
- `changeset init` and `changeset add` are interactive; write changeset files directly when working non-interactively

## Architecture

The codebase is split by concern. The window, the audio stream, and the signal processing each have their own module, and the signal processing depends on neither of the others:

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
- Needs NumPy and nothing else. Do not add SciPy back for a function or two: it doubles the size of the executable

**`openvchange/filters.py`** - Second-order filters
- Designs from the Audio EQ Cookbook: `lowpass`, `highpass` (Butterworth), `bandpass`, `shelf`
- `Biquad` runs a filter over a stream without a loop over the samples: it splits the feedback into two one-pole stages, each of which is a cumulative sum. See its docstring before changing it
- The terms of those sums grow as one over the pole magnitude, so long buffers are processed in pieces (`Biquad.piece`). `test_filter_does_not_overflow_on_a_long_buffer` guards this
- Checked against theory (the Butterworth response from its definition) and against a plain loop in `tests/reference_dsp.py`

**`openvchange/formant.py`** - Formant shifting
- `FormantShifter` moves the spectral envelope of each frame by a ratio and leaves the harmonics in place, so the pitch does not change. No Qt, no PyAudio
- Works on overlapping frames of about 21 ms and adds one frame of delay. It is skipped, with no delay, while the formants are to stay where they are
- The envelope comes from the cepstrum. How much of the cepstrum counts as envelope is set per frame from the detected pitch, so that the harmonics themselves are never moved
- In the chain it runs after the pitch shifter. With `formant_preserve`, the ratio first undoes the pitch shift (`EffectsChain.formant_ratio()`)
- Tests measure it on synthetic vowels with known formants (`tests/helpers.py`: `buzz`, `vowel`). Measure harmonic levels as band energy, never as a single spectral peak: vibrato can empty the peak

**`openvchange/widgets.py`** - Widgets that Qt does not provide
- `LevelMeter`: a peak meter on a decibel scale with peak hold and a clip light. Its drawing is tested by rendering it and reading pixels

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

**`openvchange/resources.py`** and **`openvchange/assets/`** - Files that ship with the app
- The icon is drawn by `scripts/make_icon.py`; the files in `assets/` are its output and are committed. A test fails if they no longer match the drawing
- Look files up through `resources.py`, never relative to `__main__.py`: in the executable the entry script is not inside the package, so its folder is a different one
- Anything added to `assets/` is packed into the executable by the spec

**`openvchange/settings.py`** - What is remembered between launches
- Devices (by identity), the device filter, and the effect settings, as `settings.json` in the per-user configuration folder (`%APPDATA%\OpenVChange` on Windows)
- The effect settings inside it have the same form as a preset and go through the same checks
- Saved when the window closes, restored after the device lists are filled. A damaged file is reported in the status line and never prevents startup
- Tests redirect `settings.default_path` to a temporary folder (`tests/conftest.py`), so they never read or write real settings

## Audio Processing Pipeline

Signal flow (in order):
1. Input capture → int16 to float32 normalization
2. Expander/Gate (peak detector, gain smoothed in dB)
3. High-Pass Filter (Butterworth, 20-500 Hz)
4. Low-Pass Filter (Butterworth, 1000-20000 Hz)
5. Bass Shelf Filter (250 Hz, slider ±128 dB)
6. Treble Shelf Filter (4000 Hz, slider ±128 dB)
7. De-esser (split-band, 5-8 kHz)
8. Compressor (follower in the dB domain)
9. Pitch Shift (delay line with Hann-crossfaded voices, ±12 semitones)
10. Formant Shift (spectral envelope warping, ±12 semitones)
11. Delay (0-10 s)
12. Gain (slider ±100 dB, smoothed)
13. Soft clipping (tanh) → float32 to int16 output

The slider ranges are wider than is useful for most voices, and users have presets that rely on that. Do not narrow them.

## Technical Specs

- Sample Rate: negotiated at each start. The first of 48000, 44100, 96000, 32000, 22050, 16000 Hz that both devices support
- Buffer Size: 128 to 4096 samples, 1024 by default
- Audio Format: 16-bit PCM, mono
- Filter Design: second-order, from the Audio EQ Cookbook. Butterworth for high-pass and low-pass
- Processing time: about 1 ms per 1024-sample buffer at 48 kHz with everything on (`scripts/benchmark.py`)

## Key Implementation Details

- The Main tab's "Enable Effects" checkbox sets `AudioProcessor.effects_enabled`; when off, `apply_filters()` returns the input bytes untouched (after emitting the level meter signal) and calls `reset_effect_states()` so re-enabling starts clean
- `EffectsChain.filtered()` keeps each filter with the settings it was designed for, and designs it again only when those or the sample rate change. A filter that is switched off is dropped, so that it starts afresh
- The audio callback has one buffer's worth of time per buffer (21 ms at 1024 samples and 48 kHz). Avoid per-sample Python loops over NumPy arrays in `dsp.py`; they are what made the engine miss that budget
- Pitch shift uses a circular buffer with overlapping read pointers (4 by default) and a crossfade between them. Read positions advance by repeated addition; the vectorised code reproduces that with `np.add.accumulate`, cut where a voice wraps or restarts its fade
- Known limitation: the pitch shifter places a pure tone on a grid whose spacing is the rate at which grains start (94 Hz at 48 kHz with 4 voices), so 220 Hz shifted up an octave comes out at 407 Hz. It also colours the spectrum by a few dB. Fixing this means aligning grains to the waveform, which would change how every existing preset sounds
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
