# OpenVChange

A virtual audio routing and real-time DSP application for Windows. Captures audio from an input device, applies configurable effects and filters, and routes the processed audio to an output device via a PySide6 GUI.

## Features

### Audio Routing
- Route audio between any input and output devices on your system
- WASAPI device filtering by default for low-latency on Windows, with an option to show all devices
- Automatic sample rate detection and negotiation between input/output devices

### Real-Time DSP Effects
- **Gain**: -20 to +20 dB volume adjustment
- **Bass Shelf EQ**: ±12 dB at 250 Hz (biquad shelving filter)
- **Treble Shelf EQ**: ±12 dB at 4000 Hz (biquad shelving filter)
- **Pitch Shift**: -12 to +12 semitones using a 4-voice delay-line algorithm with Hann window crossfade for artifact-free shifting
- **High-Pass Filter**: 20–500 Hz cutoff (2nd-order Butterworth)
- **Low-Pass Filter**: 1000–20000 Hz cutoff (2nd-order Butterworth)
- **Noise Gate**: RMS-based threshold gating (0–20%)

### Interface
- Real-time input level meter
- Per-filter enable/disable checkboxes (HP, LP, Noise Gate)
- Reset to Defaults button to restore all parameters
- Status display showing running/stopped state

### Signal Quality
- Filters carry their state from one buffer to the next — no clicks or pops between audio chunks
- Soft clipping to prevent digital distortion
- Full-duplex callback-based streaming for minimal latency

## Recommended Setup: VB-Audio Virtual Cable

To route processed audio into other applications (Discord, OBS, games, etc.), install **[VB-Audio Virtual Cable](https://vb-audio.com/Cable/)**. This creates a virtual audio device that acts as a bridge:

1. Download and install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) (free)
2. Restart your computer after installation
3. In OpenVChange:
   - Set your **Input** to your physical microphone
   - Set your **Output** to **CABLE Input (VB-Audio Virtual Cable)**
4. In your target application (Discord, OBS, etc.):
   - Set the input/microphone to **CABLE Output (VB-Audio Virtual Cable)**

This routes your microphone through OpenVChange's processing pipeline and into whatever application you choose.

## Requirements

- Python 3.10 or higher
- Windows (WASAPI support); macOS/Linux may work but are untested

## Installation

```bash
# Clone the repository
git clone https://github.com/gamma2653/openvchange.git
cd openvchange

# Install with Poetry
poetry install
```

## Usage

```bash
poetry run openvchange
```

Or after installation:

```bash
openvchange
```

### Controls

1. **Select Devices** — Choose input and output audio devices from the dropdowns
2. **Configure Effects** — Adjust sliders and enable/disable filters
3. **Start** — Begin audio routing and processing
4. **Stop** — End processing
5. **Reset to Defaults** — Restore all parameters to neutral values

## Building a Standalone Executable

PyInstaller is included as a dev dependency. To produce a self-contained Windows build that does not require Python:

```bash
poetry install --with dev
poetry run pyinstaller openvchange.spec
```

The result is a single self-contained `dist/OpenVChange-<version>.exe`, where the version comes from `pyproject.toml`. The spec file trims unused Qt modules, so the build is roughly 34 MB. Because it is a one-file build, the exe unpacks itself to a temp directory on launch, so the first window takes a few seconds to appear.

## Development

```bash
poetry install --with dev
poetry run ruff check .   # lint
poetry run pytest         # test
poetry run python scripts/benchmark.py   # time the effects against the real-time budget
```

The tests run without a display and never open a real audio device, so they are safe to run anywhere. Both commands run in CI on every pull request.

## Releasing

Versions and the changelog are managed with [Changesets](https://changesets.dev). This needs Node 22.11 or newer, used only for release tooling.

```bash
npm install          # once, to install the Changesets CLI
npm run changeset    # describe a change and pick patch, minor, or major
```

Commit the generated file in `.changeset/` along with your change. After that, releases are automatic:

1. Pushing to `main` with pending changesets opens or updates a **Version OpenVChange** pull request. It bumps the version in `package.json` and `pyproject.toml` and writes `CHANGELOG.md`.
2. Merging that pull request builds the Windows executable and publishes a GitHub release tagged `v<version>`, with the executable attached and the changelog entry as release notes.

Versions below 1.0.0 are published as pre-releases. The workflow lives in `.github/workflows/release.yml`.

## Technical Details

| Parameter | Value |
|-----------|-------|
| Sample Rate | 44100 Hz (auto-detected) |
| Buffer Size | 1024 samples |
| Audio Format | 16-bit PCM (int16) |
| Channels | Mono |
| HP/LP Filters | 2nd-order Butterworth |
| EQ Filters | Biquad shelving (Bristow-Johnson) |
| Pitch Shift | 4-voice overlap with Hann crossfade, 8192-sample circular buffer |

### Signal Flow

Input → Noise Gate → High-Pass → Low-Pass → Bass Shelf → Treble Shelf → Pitch Shift → Gain → Soft Clip → Output

## Dependencies

- **PySide6** — Qt GUI framework
- **PyAudio** — Audio I/O streaming
- **NumPy** — Signal processing

## License

See LICENSE file for details.
