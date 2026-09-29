# OpenVChange

A real-time voice changer and audio router for Windows. It takes audio from an input device, such as a microphone, runs it through a chain of effects, and sends the result to an output device. Pointed at a virtual audio cable, the output becomes the microphone of any other application.

## Download

Ready-made builds for Windows are on the [Releases](https://github.com/gamma2653/OpenVChange/releases) page. Download `OpenVChange-<version>.exe` and run it; there is nothing to install. It is not code-signed, so Windows SmartScreen warns the first time. Choose **More info**, then **Run anyway**.

## Features

### Effects

The signal passes through the effects in this order. Each can be switched off or left at its neutral setting.

| Effect | What it does | Range |
|--------|--------------|-------|
| Expander / gate | Turns the signal down while it is quieter than the threshold, to hide background noise between words | Threshold 0 to 20 %, ratio 1.5:1 to 10:1, attack 1 to 50 ms, release 20 to 500 ms |
| High-pass filter | Removes rumble | 20 to 500 Hz |
| Low-pass filter | Removes hiss and harshness | 1 to 20 kHz |
| Bass | Raises or lowers everything below 250 Hz | -128 to +128 dB |
| Treble | Raises or lowers everything above 4 kHz | -128 to +128 dB |
| De-esser | Turns down harsh "s" and "sh" sounds, and nothing else | Threshold -40 to 0 dB, reduction up to 12 dB |
| Compressor | Evens out loud and quiet passages | Threshold -40 to 0 dB, ratio 1:1 to 20:1, attack 1 to 100 ms, release 10 ms to 1 s, makeup up to 24 dB |
| Pitch | Raises or lowers the voice | -12 to +12 semitones |
| Formant | Moves the resonances of the voice without changing its pitch: down sounds like a larger person, up like a smaller one. Can also keep them in place while the pitch is shifted, which avoids the sound of a tape played at the wrong speed | -12 to +12 semitones |
| Delay | Holds the signal back, for example to match a video | 0 to 10 s |
| Gain | Overall volume | -100 to +100 dB |

A soft clipper at the end keeps the output from exceeding full scale however the effects are set.

### Presets

- Eight built-in presets: Neutral, Clean voice, Radio announcer, Telephone, Deep voice, Giant, Higher voice, and Chipmunk
- Save your own settings to a file and load them again. A preset file is plain JSON
- The preset list shows which built-in preset is in use, and **Custom** once a setting has been changed

### Devices

- Any input and output device on the system can be used
- Only WASAPI devices are listed by default, since that is the low-latency interface on Windows. **Show all devices** lists the others too
- **Refresh** finds devices that were plugged in after the app was started
- The sample rate is chosen to suit both devices

### Interface

- Level meters for input and output, on a decibel scale, with a marker for the highest recent peak and a light that shows clipping
- **Enable Effects** switches the whole chain off and passes the input through untouched
- A keyboard shortcut can do the same from any application, for use in the middle of a game or a call. Set it under **Advanced Settings**. Windows only
- Devices, effect settings, and the shortcut are remembered between launches
- Problems are shown in the status line: a device that could not be opened, a preset that could not be read, a shortcut that is already taken

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

1. **Select devices.** Choose the input and the output. Press **Refresh** if a device is missing.
2. **Choose a preset,** or set the effects by hand. The **Main** tab has the tone and pitch controls, the **Dynamics** tab has the expander, compressor, and de-esser.
3. **Start.** Watch the meters. If the red light on the input meter comes on, turn the microphone down. If the one on the output meter comes on, turn the gain down.
4. **Stop** ends processing. **Reset to Defaults** returns every setting to neutral.

Settings can be changed while audio is running, with two exceptions. The buffer size and the number of pitch voices, both under **Advanced Settings**, take effect at the next start.

### Delay through the app

Every buffer of audio takes its own length to collect, which is 21 ms at the default size of 1024 samples. Smaller buffers lower the delay and raise the risk of dropouts. On top of that, the pitch shifter adds between 40 and 110 ms while the pitch is shifted, and formant control adds about 20 ms while it is in use.

### Where settings are kept

In `settings.json`, in the `OpenVChange` folder under your application data folder. On Windows that is `%APPDATA%\OpenVChange`. Deleting the file returns the app to its defaults.

## Building a Standalone Executable

PyInstaller is included as a dev dependency. To produce a self-contained Windows build that does not require Python:

```bash
poetry install --with dev
poetry run pyinstaller openvchange.spec
```

The executable is not code-signed, so Windows SmartScreen warns the first time it is run. Signing needs a certificate, which this project does not have.

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

1. Pushing to `main` with pending changesets opens or updates a **Version OpenVChange** pull request. It bumps the version everywhere it appears and writes `CHANGELOG.md`.
2. Merging that pull request builds the Windows executable and publishes a GitHub release tagged `v<version>`, with the executable attached and the changelog entry as release notes.

Versions below 1.0.0 are published as pre-releases. The workflow lives in `.github/workflows/release.yml`.

## Technical Details

| Parameter | Value |
|-----------|-------|
| Sample rate | The first of 48, 44.1, 96, 32, 22.05, and 16 kHz that both devices support |
| Buffer size | 128 to 4096 samples, 1024 by default |
| Audio format | 16-bit PCM |
| Channels | Mono |
| Filters | Second-order, from the Audio EQ Cookbook by Robert Bristow-Johnson. High-pass and low-pass are Butterworth |
| Pitch shift | Delay line read by 1 to 8 crossfaded voices, 4 by default |
| Formant shift | Spectral envelope from the cepstrum, moved frame by frame. Frames of 1024 samples at 48 kHz |
| Processing time | About 1 ms per 1024-sample buffer with every effect on, which is 5 % of the time available |

### Signal Flow

Input → Expander → High-Pass → Low-Pass → Bass → Treble → De-esser → Compressor → Pitch → Formant → Delay → Gain → Soft Clip → Output

### Known limitation of the pitch shifter

The pitch shifter works on short grains of sound and does not know where the waveform repeats. On a voice that is rarely noticed, but it puts a pure tone on the nearest of a set of evenly spaced frequencies, not exactly where it was asked to. A tone of 220 Hz shifted up an octave comes out at 407 Hz, not 440. It also colours the sound slightly, which is why formants that are kept in place return close to the original, not exactly to it.

## Dependencies

- **PySide6** — Qt GUI framework
- **PyAudio** — Audio I/O streaming
- **NumPy** — Signal processing

## License

See LICENSE file for details.
