# OpenVChange

A virtual audio routing and processing application for real-time audio manipulation between devices.

## Overview

OpenVChange captures audio from an input device, applies configurable real-time filters and effects, and routes the processed audio to an output device. It functions as a software audio mixer with integrated DSP capabilities.

## Features

- **Audio Routing**: Route audio between any input/output devices on your system
- **Gain Control**: Adjust volume from -20 to +20 dB
- **Equalizer**: Bass and treble shelf filters (±12 dB)
- **High-Pass Filter**: Remove low frequencies (20-500 Hz, Butterworth design)
- **Low-Pass Filter**: Remove high frequencies (1000-20000 Hz, Butterworth design)
- **Noise Gate**: Threshold-based noise suppression
- **Level Meter**: Real-time visual feedback of input audio levels
- **Clipping Protection**: Prevents audio distortion

## Requirements

- Python 3.10 or higher
- Windows/macOS/Linux with audio devices

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/openvchange.git
cd openvchange

# Install with Poetry
poetry install
```

## Usage

```bash
# Run the application
poetry run openvchange
```

Or after installation:

```bash
openvchange
```

### Controls

1. **Select Devices**: Choose your input and output audio devices from the dropdowns
2. **Configure Filters**: Adjust sliders and toggles to set your desired processing
3. **Start**: Click "Start" to begin audio routing
4. **Stop**: Click "Stop" to end processing

## Technical Details

- **Sample Rate**: 44.1 kHz
- **Buffer Size**: 1024 samples
- **Audio Format**: 16-bit PCM
- **Filter Design**: Biquad shelf filters (EQ), 2nd-order Butterworth (HP/LP)

## Dependencies

- PySide6 - Qt-based GUI framework
- PyAudio - Audio I/O
- NumPy - Numerical operations
- SciPy - Signal processing

## License

See LICENSE file for details.
