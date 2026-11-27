"""Stand-ins for PyAudio and the system shortcut API, so tests never touch the real ones."""

from __future__ import annotations

from typing import Any, ClassVar

import pyaudio

MME = 0
WASAPI = 1

DEFAULT_HOST_APIS = [
    {"index": MME, "name": "MME"},
    {"index": WASAPI, "name": "Windows WASAPI"},
]


def device(
    name: str,
    host_api: int,
    inputs: int,
    outputs: int,
    rates: tuple[int, ...] = (48000, 44100),
    all_channels_only: bool = False,
) -> dict:
    """A device. With `all_channels_only` it refuses to be opened with fewer channels than it has."""
    return {
        "name": name,
        "hostApi": host_api,
        "maxInputChannels": inputs,
        "maxOutputChannels": outputs,
        "defaultSampleRate": float(rates[0]),
        "supportedRates": rates,
        "allChannelsOnly": all_channels_only,
    }


DEFAULT_DEVICES = [
    device("Microphone (MME)", MME, inputs=2, outputs=0),
    device("Speakers (MME)", MME, inputs=0, outputs=2),
    device("Microphone (USB Audio)", WASAPI, inputs=1, outputs=0),
    device("Speakers (Realtek)", WASAPI, inputs=0, outputs=2),
    device("CABLE Input (VB-Audio Virtual Cable)", WASAPI, inputs=0, outputs=2),
]


class FakeStream:
    """Records how it was opened and lets a test drive the callback by hand."""

    def __init__(self, start_error: Exception | None = None, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.callback = kwargs.get("stream_callback")
        self.start_error = start_error
        self.started = False
        self.closed = False

    def start_stream(self) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.started = True

    def stop_stream(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True

    def is_active(self) -> bool:
        return self.started

    def feed(self, data: bytes) -> bytes | None:
        """Push one input buffer through the callback, as PortAudio would.

        Returns what the stream plays in return, which is nothing for an input stream.
        """
        assert self.callback is not None, "stream was opened without a callback"
        assert self.kwargs["input"], "fed a stream that does not capture"
        frames = len(data) // (2 * self.kwargs["channels"])
        out, flag = self.callback(data, frames, {}, 0)
        assert flag == pyaudio.paContinue
        return out

    def pull(self, frames: int) -> bytes:
        """Ask an output stream for its next buffer, as PortAudio would."""
        assert self.callback is not None, "stream was opened without a callback"
        assert self.kwargs["output"] and not self.kwargs["input"], "pulled from a stream that captures"
        out, flag = self.callback(None, frames, {}, 0)
        assert flag == pyaudio.paContinue
        assert len(out) == frames * 2 * self.kwargs["channels"]
        return out


class FakePyAudio:
    """Minimal PyAudio replacement backed by an in-memory device table.

    Like PortAudio, it looks at the device table only when the library starts up, which is
    when the first instance is created. Instances created while another is alive share
    what that one found. Changing `devices` models plugging hardware in or out.
    """

    devices: ClassVar[list[dict]] = list(DEFAULT_DEVICES)
    host_apis: ClassVar[list[dict]] = list(DEFAULT_HOST_APIS)
    alive: ClassVar[int] = 0
    scanned: ClassVar[list[dict]] = []
    open_error: ClassVar[Exception | None] = None
    start_error: ClassVar[Exception | None] = None
    instances: ClassVar[list[FakePyAudio]] = []

    def __init__(self) -> None:
        cls = type(self)
        if cls.alive == 0:
            cls.scanned = [dict(d) for d in cls.devices]
        cls.alive += 1
        self._devices = cls.scanned
        self.streams: list[FakeStream] = []
        self.terminated = False
        cls.instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.devices = list(DEFAULT_DEVICES)
        cls.host_apis = list(DEFAULT_HOST_APIS)
        cls.open_error = None
        cls.start_error = None
        cls.instances = []
        cls.alive = 0
        cls.scanned = []

    def terminate(self) -> None:
        assert not self.terminated, "terminated twice"
        self.terminated = True
        type(self).alive -= 1

    def get_host_api_count(self) -> int:
        return len(self.host_apis)

    def get_host_api_info_by_index(self, index: int) -> dict:
        return self.host_apis[index]

    def get_device_count(self) -> int:
        return len(self._devices)

    def get_device_info_by_index(self, index: int) -> dict:
        return self._devices[index]

    def is_format_supported(self, rate: float, **kwargs: Any) -> bool:
        for side in ("input", "output"):
            index = kwargs.get(f"{side}_device")
            if index is None:
                continue
            info = self._devices[index]
            if int(rate) not in info["supportedRates"]:
                raise ValueError("Invalid sample rate", -9997)
            self.check_channels(info, side, kwargs[f"{side}_channels"])
        return True

    @staticmethod
    def check_channels(info: dict, side: str, channels: int) -> None:
        available = info["maxInputChannels" if side == "input" else "maxOutputChannels"]
        if channels > available or (info.get("allChannelsOnly") and channels != available):
            raise ValueError("Invalid number of channels", -9998)

    def open(self, **kwargs: Any) -> FakeStream:
        assert not self.terminated, "opened a stream on a terminated instance"
        for side in ("input", "output"):
            index = kwargs.get(f"{side}_device_index")
            if index is None:
                continue
            if not 0 <= index < len(self._devices):
                raise OSError(-9996, "Invalid device")
            try:
                self.check_channels(self._devices[index], side, kwargs["channels"])
            except ValueError as e:
                raise OSError(*reversed(e.args)) from e
        error = type(self).open_error
        if error is not None:
            raise error
        stream = FakeStream(start_error=type(self).start_error, **kwargs)
        self.streams.append(stream)
        return stream


class FakeHotkeyBackend:
    """Remembers which shortcuts are registered, and refuses those listed in `taken`."""

    taken: ClassVar[set[tuple[int, int]]] = set()
    instances: ClassVar[list[FakeHotkeyBackend]] = []

    def __init__(self) -> None:
        self.registered: dict[int, tuple[int, int]] = {}
        self.calls: list[tuple] = []
        type(self).instances.append(self)

    @classmethod
    def reset(cls) -> None:
        cls.taken = set()
        cls.instances = []

    def register(self, hotkey_id: int, modifiers: int, key_code: int) -> None:
        from openvchange.hotkey import HotkeyError

        self.calls.append(("register", modifiers, key_code))
        assert hotkey_id not in self.registered, "registered twice without unregistering"
        if (modifiers, key_code) in type(self).taken:
            raise HotkeyError("another application already uses it")
        self.registered[hotkey_id] = (modifiers, key_code)

    def unregister(self, hotkey_id: int) -> None:
        self.calls.append(("unregister",))
        assert hotkey_id in self.registered, "unregistered something that was not registered"
        del self.registered[hotkey_id]
