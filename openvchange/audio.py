"""Audio streaming for OpenVChange: devices, the PortAudio streams, and the level meter."""

import logging
import math
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pyaudio
from PySide6.QtCore import QObject, Signal

from openvchange.dsp import EffectsChain
from openvchange.routing import Link, limit

logger = logging.getLogger(__name__)

StreamCallback = Callable[[bytes | None, int, Mapping[str, float], int], tuple[bytes | None, int]]


class AudioStartError(Exception):
    """The audio streams could not be started. The message is meant to be shown to the user."""


@dataclass(frozen=True)
class Device:
    """An audio device as PortAudio lists it."""

    index: int  # only valid until the next refresh
    name: str
    host_api: str
    input_channels: int
    output_channels: int

    @property
    def is_input(self) -> bool:
        return self.input_channels > 0

    @property
    def is_output(self) -> bool:
        return self.output_channels > 0

    @property
    def identity(self) -> str:
        """What stays the same about a device when the list is refreshed."""
        return f"{self.host_api}: {self.name}"


@dataclass(frozen=True)
class Levels:
    """What the meters show for one stretch of audio on one route."""

    input_db: float  # highest input peak, in dB below full scale
    output_db: float  # highest peak after the effects
    input_clipped: bool  # the input reached full scale
    output_clipped: bool  # the output would have exceeded full scale without the soft clipper
    seconds: float  # how much audio this covers
    route: int = 0  # position of the route in AudioProcessor.routes


def to_db(level: float) -> float:
    """A linear level in decibels, with silence at -200 dB."""
    return 20.0 * math.log10(max(level, 1e-10))


def peak(data: npt.NDArray[np.floating]) -> float:
    return float(np.max(np.abs(data))) if len(data) else 0.0


def from_pcm(audio_data: bytes) -> npt.NDArray[np.float32]:
    """16-bit audio as floats from -1.0 to 1.0."""
    return np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0


def to_pcm(data: npt.NDArray[np.floating]) -> bytes:
    return (data * 32767).astype(np.int16).tobytes()


# The meters are told about levels this many times per second of audio. More would
# only keep the GUI busy: small buffers arrive hundreds of times per second.
METER_UPDATES_PER_SECOND = 30

# A 16-bit input sample at either end of its range.
INPUT_FULL_SCALE = 32767 / 32768

# Tried in this order. The first that every device in use supports is taken.
SAMPLE_RATES = (48000, 44100, 96000, 32000, 22050, 16000)


class Route:
    """One way through the app: an input, a chain of effects, and an output.

    The input and the output are devices, or one channel each of a device. Channels
    are counted from 0; None takes every channel of the input, mixed, and plays on
    every channel of the output.
    """

    def __init__(self, sample_rate: int) -> None:
        self.input_device: int | None = None
        self.input_channel: int | None = None
        self.output_device: int | None = None
        self.output_channel: int | None = None
        self.effects = EffectsChain(sample_rate)
        self.effects_enabled = True  # False passes the input on untouched
        self.chunk_size = 1024  # frames per buffer. A device shared with another route gets the larger

        # Carries the audio from the input stream to the output stream, while the
        # two are separate streams.
        self.link: Link | None = None
        self.reset_meters()

    def reset_meters(self) -> None:
        """Forget the levels gathered so far."""
        self.metered_samples = 0
        self.input_peak = 0.0
        self.output_peak = 0.0
        self.output_peak_unclipped = 0.0


class AudioProcessor(QObject):
    """Runs audio along routes: from an input device, through effects, to an output device.

    Routes are independent. Two can take the same input and give it different effects
    on the way to different outputs, and two can arrive at the same output, which then
    plays their sum.

    A single route runs both devices as one stream, which keeps the delay as short as
    PortAudio can make it. Anything more opens one stream per device, and each route
    reaches its output through a link (`routing.Link`) that adds up to two buffers of
    delay and absorbs the difference between the device clocks.
    """

    # Levels for the meters, as a Levels object per route. Emitted from an audio thread.
    levels_changed = Signal(object)

    # Processing failed while audio was running. Emitted once per failure, from an audio
    # thread. The streams keep running but output silence until they are restarted.
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.running = False
        self.sample_rate = 44100
        self.streams: list[pyaudio.Stream] = []

        # What the app starts as: one input, its effects, one output.
        self.routes: list[Route] = []
        self.add_route()

        # Set when processing has failed. Nothing but silence goes out until a restart.
        self.failed = False
        self._failure_lock = threading.Lock()

        self.pa = pyaudio.PyAudio()

    @property
    def effects(self) -> EffectsChain:
        """The effects of the first route."""
        return self.routes[0].effects

    # --- routes --------------------------------------------------------------------

    def add_route(self) -> Route:
        """A new route at the end of the list, with no devices yet."""
        self._require_stopped()
        route = Route(self.sample_rate)
        self.routes.append(route)
        return route

    def remove_route(self, route: Route) -> None:
        self._require_stopped()
        self.routes.remove(route)

    def _require_stopped(self) -> None:
        # The audio threads walk the list without a lock.
        if self.running or self.streams:
            raise RuntimeError("the routes cannot be changed while audio is running")

    # --- devices -------------------------------------------------------------------

    def list_devices(self, all_host_apis: bool = False) -> list[Device]:
        """The devices PortAudio found when it last looked.

        By default only WASAPI devices are listed, since that is the low-latency
        interface on Windows and the same hardware shows up once per interface. Where
        there is no WASAPI, everything is listed.
        """
        host_apis = [str(self.pa.get_host_api_info_by_index(i)["name"]) for i in range(self.pa.get_host_api_count())]
        wasapi = next((i for i, name in enumerate(host_apis) if "WASAPI" in name), None)

        devices = []
        for index in range(self.pa.get_device_count()):
            info = self.pa.get_device_info_by_index(index)
            host_api = int(info["hostApi"])
            if not all_host_apis and wasapi is not None and host_api != wasapi:
                continue
            devices.append(
                Device(
                    index=index,
                    name=str(info["name"]),
                    host_api=host_apis[host_api] if 0 <= host_api < len(host_apis) else "",
                    input_channels=int(info["maxInputChannels"]),
                    output_channels=int(info["maxOutputChannels"]),
                )
            )
        return devices

    def shut_down(self) -> None:
        """Stop the streams and release PortAudio. Safe to call more than once."""
        self.stop()
        if self.pa is not None:
            self.pa.terminate()
            self.pa = None

    def refresh_devices(self) -> None:
        """Look for devices again, to find ones plugged in since the last look.

        PortAudio only scans when it starts up, so it is shut down and started again.
        That invalidates every device index, and cannot be done while a stream is open.
        """
        if self.running or self.streams:
            raise RuntimeError("devices cannot be refreshed while audio is running")
        self.pa.terminate()
        self.pa = pyaudio.PyAudio()
        for route in self.routes:
            route.input_device = None
            route.output_device = None

    def supports(self, device: int, is_input: bool, channels: int, rate: int) -> bool:
        """Whether a device can be opened with this many channels at this sample rate."""
        side = "input" if is_input else "output"
        try:
            return bool(
                self.pa.is_format_supported(
                    rate,
                    **{f"{side}_device": device, f"{side}_channels": channels, f"{side}_format": pyaudio.paInt16},
                )
            )
        except ValueError:
            return False

    def stream_channels(self, device: int, is_input: bool, wanted: set[int | None]) -> int:
        """How many channels to open a device with, given the channels that are used.

        One, when nobody asks for a particular channel: the device then mixes its
        channels down, or plays the one on all of them, as it sees fit. Otherwise all it
        has, and the picking is done here. Some devices with more than two channels
        refuse to be opened with one; those are opened with all of theirs as well.
        """
        info = self.pa.get_device_info_by_index(device)
        available = int(info["maxInputChannels" if is_input else "maxOutputChannels"])
        for channel in wanted:
            if channel is not None and channel >= available:
                side = "input" if is_input else "output"
                raise AudioStartError(f"{info['name']} has no {side} channel {channel + 1}.")
        if wanted == {None} and any(self.supports(device, is_input, 1, rate) for rate in SAMPLE_RATES):
            return 1
        return max(available, 1)

    def find_common_sample_rate(self, inputs: Mapping[int, int], outputs: Mapping[int, int]) -> int:
        """A sample rate that every device supports. Both map a device to its channel count."""
        for rate in SAMPLE_RATES:
            if all(self.supports(device, True, channels, rate) for device, channels in inputs.items()) and all(
                self.supports(device, False, channels, rate) for device, channels in outputs.items()
            ):
                return rate

        # Fallback
        return 44100

    # --- processing ----------------------------------------------------------------

    def run(self, route: Route, data: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        """One buffer through the effects of a route. A bypassed route gets `data` itself back."""
        input_peak = peak(data)

        # Bypass - return input untouched, but drop stale filter state
        # so re-enabling the chain does not click.
        if not route.effects_enabled:
            route.effects.reset_effect_states()
            self.measure(route, len(data), input_peak, input_peak, input_peak)
            return data

        processed = route.effects.process(data)
        self.measure(route, len(processed), input_peak, peak(processed), route.effects.peak_before_clipping)
        return processed

    def apply_filters(self, audio_data: bytes, route: Route | None = None) -> bytes:
        """Run one buffer of 16-bit audio through the effects of a route, by default the first."""
        data = from_pcm(audio_data)
        processed = self.run(route or self.routes[0], data)
        return audio_data if processed is data else to_pcm(processed)

    def reset_meters(self) -> None:
        """Forget the levels gathered so far."""
        for route in self.routes:
            route.reset_meters()

    def measure(
        self, route: Route, samples: int, input_peak: float, output_peak: float, output_peak_unclipped: float
    ) -> None:
        """Gather the levels of a route, and pass them on once enough audio has gone by."""
        route.metered_samples += samples
        route.input_peak = max(route.input_peak, input_peak)
        route.output_peak = max(route.output_peak, output_peak)
        route.output_peak_unclipped = max(route.output_peak_unclipped, output_peak_unclipped)

        if route.metered_samples * METER_UPDATES_PER_SECOND < self.sample_rate:
            return
        levels = Levels(
            input_db=to_db(route.input_peak),
            output_db=to_db(route.output_peak),
            input_clipped=route.input_peak >= INPUT_FULL_SCALE,
            output_clipped=route.output_peak_unclipped >= 1.0,
            seconds=route.metered_samples / self.sample_rate,
            route=self.routes.index(route),
        )
        route.reset_meters()
        self.levels_changed.emit(levels)

    def fail(self, error: BaseException) -> None:
        """Silence everything and report the error, unless one was reported already."""
        with self._failure_lock:
            if self.failed:
                return
            self.failed = True
        self.error_occurred.emit(describe(error))

    def duplex_callback(self, route: Route) -> StreamCallback:
        """The callback of a stream that takes a route in and plays it straight back out."""

        def callback(
            in_data: bytes | None, frame_count: int, time_info: Mapping[str, float], status: int
        ) -> tuple[bytes, int]:
            silence = bytes(frame_count * 2)
            if not self.running or self.failed or in_data is None:
                return (silence, pyaudio.paContinue)

            try:
                processed = self.apply_filters(in_data, route)
            except Exception as e:  # the audio thread must never raise
                # Never fall back to the input: that would send the unprocessed voice out.
                logger.exception("Audio processing failed")
                self.fail(e)
                return (silence, pyaudio.paContinue)
            return (processed, pyaudio.paContinue)

        return callback

    def input_callback(self, routes: list[Route], channels: int) -> StreamCallback:
        """The callback of an input stream, for the routes that start at its device."""

        def callback(
            in_data: bytes | None, frame_count: int, time_info: Mapping[str, float], status: int
        ) -> tuple[None, int]:
            if not self.running or self.failed or in_data is None:
                return (None, pyaudio.paContinue)

            try:
                frames = from_pcm(in_data).reshape(-1, channels)
                for route in routes:
                    if route.input_channel is not None:
                        data = frames[:, route.input_channel]
                    elif channels == 1:
                        data = frames[:, 0]
                    else:
                        data = frames.mean(axis=1)
                    route.link.write(self.run(route, data))
            except Exception as e:  # the audio thread must never raise
                logger.exception("Audio processing failed")
                self.fail(e)
            return (None, pyaudio.paContinue)

        return callback

    def output_callback(self, routes: list[Route], channels: int, crowded: npt.NDArray[np.bool_]) -> StreamCallback:
        """The callback of an output stream, for the routes that end at its device.

        `crowded` marks the channels of the stream that more than one route arrives on,
        whose sum can exceed full scale.
        """

        def callback(
            in_data: bytes | None, frame_count: int, time_info: Mapping[str, float], status: int
        ) -> tuple[bytes, int]:
            silence = bytes(frame_count * channels * 2)
            if not self.running or self.failed:
                return (silence, pyaudio.paContinue)

            try:
                frames = np.zeros((frame_count, channels), dtype=np.float32)
                for route in routes:
                    if route.output_channel is None:
                        frames += route.link.read(frame_count)[:, np.newaxis]
                    else:
                        frames[:, route.output_channel] += route.link.read(frame_count)
                # A single route is below full scale already, and is left as it is.
                if crowded.any():
                    frames[:, crowded] = limit(frames[:, crowded])
                played = to_pcm(frames)
            except Exception as e:  # the audio thread must never raise
                logger.exception("Audio processing failed")
                self.fail(e)
                return (silence, pyaudio.paContinue)
            return (played, pyaudio.paContinue)

        return callback

    # --- starting and stopping -----------------------------------------------------

    def start(self) -> None:
        """Start audio processing. Raises AudioStartError if a stream cannot be started."""
        self.stop()
        if any(r.input_device is None or r.output_device is None for r in self.routes):
            raise AudioStartError("Select an input and an output device first.")

        self.failed = False
        try:
            # How many channels each device in use is opened with.
            inputs = {
                device: self.stream_channels(
                    device, True, {r.input_channel for r in self.routes if r.input_device == device}
                )
                for device in dict.fromkeys(r.input_device for r in self.routes)
            }
            outputs = {
                device: self.stream_channels(
                    device, False, {r.output_channel for r in self.routes if r.output_device == device}
                )
                for device in dict.fromkeys(r.output_device for r in self.routes)
            }

            self.sample_rate = self.find_common_sample_rate(inputs, outputs)
            for route in self.routes:
                route.effects.set_sample_rate(self.sample_rate)
                route.effects.reset()
                route.reset_meters()

            if len(self.routes) == 1 and {*inputs.values(), *outputs.values()} == {1}:
                (route,) = self.routes
                self.open_stream(
                    self.duplex_callback(route),
                    channels=1,
                    frames=route.chunk_size,
                    input_device=route.input_device,
                    output_device=route.output_device,
                )
            else:
                self.open_streams(inputs, outputs)
            self.running = True
            for stream in self.streams:
                stream.start_stream()
        except AudioStartError:
            self.stop()
            raise
        except Exception as e:  # PortAudio raises several unrelated types
            logger.exception("Could not start the audio streams")
            self.stop()
            raise AudioStartError(describe(e)) from e

    def open_streams(self, inputs: Mapping[int, int], outputs: Mapping[int, int]) -> None:
        """Open a stream per device, with a link along each route.

        A device in use by several routes is opened with the largest of their buffer
        sizes: a larger buffer is the safer choice for all of them.
        """
        def frames(routes: list[Route]) -> int:
            return max(r.chunk_size for r in routes)

        starting = {device: [r for r in self.routes if r.input_device == device] for device in inputs}
        arriving = {device: [r for r in self.routes if r.output_device == device] for device in outputs}
        for route in self.routes:
            block = max(frames(starting[route.input_device]), frames(arriving[route.output_device]))
            route.link = Link(block, self.sample_rate)

        # Outputs first, so that nothing is captured before there is somewhere for it to go.
        for device, channels in outputs.items():
            sources = np.zeros(channels, dtype=int)
            for route in arriving[device]:
                sources[slice(None) if route.output_channel is None else route.output_channel] += 1
            callback = self.output_callback(arriving[device], channels, sources > 1)
            self.open_stream(callback, channels, frames(arriving[device]), output_device=device)

        for device, channels in inputs.items():
            callback = self.input_callback(starting[device], channels)
            self.open_stream(callback, channels, frames(starting[device]), input_device=device)

    def open_stream(
        self,
        callback: StreamCallback,
        channels: int,
        frames: int,
        input_device: int | None = None,
        output_device: int | None = None,
    ) -> None:
        self.streams.append(
            self.pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=self.sample_rate,
                input=input_device is not None,
                output=output_device is not None,
                input_device_index=input_device,
                output_device_index=output_device,
                frames_per_buffer=frames,
                stream_callback=callback,
            )
        )

    def stop(self) -> None:
        """Stop audio processing."""
        self.running = False

        streams, self.streams = self.streams, []
        for stream in streams:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:  # a stream that failed to start may fail to stop
                logger.exception("Could not close an audio stream cleanly")
        for route in self.routes:
            route.link = None


def describe(error: BaseException) -> str:
    """A one-line description of an error, for the status bar."""
    # PortAudio errors arrive as OSError(code, text) or OSError(text, code).
    parts = [str(arg) for arg in error.args if isinstance(arg, str) and arg.strip()]
    text = parts[0] if parts else str(error)
    text = " ".join(text.split())
    return text or type(error).__name__
