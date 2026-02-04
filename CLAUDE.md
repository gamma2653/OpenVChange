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
```

Note: No test framework or linting tools are currently configured.

## Architecture

The codebase has two main modules:

**`openvchange/__main__.py`** - GUI layer using PySide6/Qt
- `MainWindow`: Orchestrates UI components and AudioProcessor
- Device selection (input/output combo boxes)
- Filter control sliders/checkboxes for all DSP parameters
- Real-time level meter visualization
- Start/Stop/Reset controls

**`openvchange/audio.py`** - Audio processing engine
- `AudioProcessor`: Qt QObject with callback-based PyAudio streaming
- Full-duplex audio (simultaneous input/output)
- Stateful filter implementation using `scipy.lfilter` with `lfilter_zi` for continuous processing without clicks/pops

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

- Filter coefficients are recalculated when parameters change via `_update_filter_coefficients()`
- Pitch shift uses circular buffer with 4 overlapping read pointers and crossfade to reduce artifacts
- Level meter emits Qt signals for thread-safe GUI updates
- PyAudio callback runs in separate thread; use Qt signals to communicate with GUI
