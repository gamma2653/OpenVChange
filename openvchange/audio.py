"""Audio streaming for OpenVChange: devices, the PortAudio stream, and the level meter."""

import logging
from collections.abc import Mapping

import numpy as np
import pyaudio
from PySide6.QtCore import QObject, Signal

from openvchange.dsp import EffectsChain

logger = logging.getLogger(__name__)


class AudioStartError(Exception):
    """The audio stream could not be started. The message is meant to be shown to the user."""


class AudioProcessor(QObject):
    """Routes audio from an input device, through the effects chain, to an output device."""

    level_changed = Signal(float)

    # Processing failed while the stream was running. Emitted once per failure, from the
    # audio thread. The stream keeps running but outputs silence until it is restarted.
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.running = False
        self.input_device = None
        self.output_device = None
        self.sample_rate = 44100
        self.chunk_size = 1024
        self.channels = 1
        self.stream = None

        # The signal processing itself. The GUI sets effect parameters on this object.
        self.effects = EffectsChain(self.sample_rate)

        # Master effects bypass (False = pass input straight to output)
        self.effects_enabled = True

        # Set when processing has failed. Nothing but silence goes out until a restart.
        self.failed = False

        self.pa = pyaudio.PyAudio()

    def set_input_device(self, device_index: int) -> None:
        self.input_device = device_index

    def set_output_device(self, device_index: int) -> None:
        self.output_device = device_index

    def get_supported_sample_rate(self, device_index: int, is_input: bool) -> int:
        """Find a supported sample rate for the device."""
        common_rates = [48000, 44100, 96000, 32000, 22050, 16000]
        device_info = self.pa.get_device_info_by_index(device_index)

        for rate in common_rates:
            try:
                if is_input:
                    supported = self.pa.is_format_supported(
                        rate,
                        input_device=device_index,
                        input_channels=self.channels,
                        input_format=pyaudio.paInt16,
                    )
                else:
                    supported = self.pa.is_format_supported(
                        rate,
                        output_device=device_index,
                        output_channels=self.channels,
                        output_format=pyaudio.paInt16,
                    )
                if supported:
                    return rate
            except ValueError:
                continue

        # Fallback to device default
        return int(device_info.get("defaultSampleRate", 44100))

    def find_common_sample_rate(self) -> int:
        """Find a sample rate supported by both input and output devices."""
        common_rates = [48000, 44100, 96000, 32000, 22050, 16000]

        for rate in common_rates:
            try:
                input_ok = self.pa.is_format_supported(
                    rate,
                    input_device=self.input_device,
                    input_channels=self.channels,
                    input_format=pyaudio.paInt16,
                )
                output_ok = self.pa.is_format_supported(
                    rate,
                    output_device=self.output_device,
                    output_channels=self.channels,
                    output_format=pyaudio.paInt16,
                )
                if input_ok and output_ok:
                    return rate
            except ValueError:
                continue

        # Fallback
        return 44100

    def set_effects_enabled(self, enabled: bool) -> None:
        """Enable or bypass the entire effects chain."""
        self.effects_enabled = enabled

    def set_chunk_size(self, size: int) -> None:
        """Set the audio buffer size (frames per buffer)."""
        self.chunk_size = size

    def apply_filters(self, audio_data: bytes) -> bytes:
        """Run one buffer of 16-bit audio through the effects chain."""
        data = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32)
        data = data / 32768.0  # Normalize to -1.0 to 1.0

        # Calculate input level for meter
        rms = np.sqrt(np.mean(data**2))
        self.level_changed.emit(rms)

        # Master bypass - return input untouched, but drop stale filter state
        # so re-enabling the chain does not click.
        if not self.effects_enabled:
            self.effects.reset_effect_states()
            return audio_data

        data = self.effects.process(data)

        # Convert back to int16
        return (data * 32767).astype(np.int16).tobytes()

    def audio_callback(self, in_data: bytes | None, frame_count: int, time_info: Mapping[str, float], status: int) -> tuple[bytes, int]:
        """Combined callback for full-duplex audio processing."""
        silence = b"\x00" * (frame_count * self.channels * 2)
        if not self.running or self.failed or in_data is None:
            return (silence, pyaudio.paContinue)

        try:
            processed = self.apply_filters(in_data)
        except Exception as e:  # the audio thread must never raise
            # Never fall back to the input: that would send the unprocessed voice out.
            self.failed = True
            logger.exception("Audio processing failed")
            self.error_occurred.emit(describe(e))
            return (silence, pyaudio.paContinue)
        return (processed, pyaudio.paContinue)

    def start(self) -> None:
        """Start audio processing. Raises AudioStartError if the stream cannot be started."""
        if self.input_device is None or self.output_device is None:
            raise AudioStartError("Select an input and an output device first.")

        self.stop()
        self.failed = False
        self.sample_rate = self.find_common_sample_rate()
        self.effects.set_sample_rate(self.sample_rate)
        self.effects.reset()

        try:
            # Use full-duplex stream for synchronized I/O
            self.stream = self.pa.open(
                format=pyaudio.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                output=True,
                input_device_index=self.input_device,
                output_device_index=self.output_device,
                frames_per_buffer=self.chunk_size,
                stream_callback=self.audio_callback,
            )
            self.running = True
            self.stream.start_stream()
        except Exception as e:  # PortAudio raises several unrelated types
            logger.exception("Could not start the audio stream")
            self.stop()
            raise AudioStartError(describe(e)) from e

    def stop(self) -> None:
        """Stop audio processing."""
        self.running = False

        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:  # a stream that failed to start may fail to stop
                logger.exception("Could not close the audio stream cleanly")


def describe(error: BaseException) -> str:
    """A one-line description of an error, for the status bar."""
    # PortAudio errors arrive as OSError(code, text) or OSError(text, code).
    parts = [str(arg) for arg in error.args if isinstance(arg, str) and arg.strip()]
    text = parts[0] if parts else str(error)
    text = " ".join(text.split())
    return text or type(error).__name__
