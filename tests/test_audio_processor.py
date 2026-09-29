"""The engine's stream handling: devices, sample rates, the callback, and the level meter."""

import numpy as np
import pyaudio
import pytest

from openvchange.audio import AudioProcessor
from tests.fakes import WASAPI, FakePyAudio, device
from tests.helpers import rms, sine, to_pcm

MIC = 2
SPEAKERS = 3


def started_processor() -> AudioProcessor:
    p = AudioProcessor()
    p.set_input_device(MIC)
    p.set_output_device(SPEAKERS)
    p.start()
    return p


def test_start_opens_one_full_duplex_stream_on_the_selected_devices():
    p = started_processor()

    (stream,) = p.pa.streams
    assert stream.started
    assert p.running
    assert stream.kwargs["input"] and stream.kwargs["output"]
    assert stream.kwargs["input_device_index"] == MIC
    assert stream.kwargs["output_device_index"] == SPEAKERS
    assert stream.kwargs["format"] == pyaudio.paInt16
    assert stream.kwargs["channels"] == 1
    assert stream.kwargs["frames_per_buffer"] == 1024


def test_start_uses_the_configured_buffer_size():
    p = AudioProcessor()
    p.set_input_device(MIC)
    p.set_output_device(SPEAKERS)
    p.set_chunk_size(256)
    p.start()
    assert p.pa.streams[0].kwargs["frames_per_buffer"] == 256


def test_start_without_devices_does_nothing():
    p = AudioProcessor()
    p.start()
    assert not p.running
    assert p.pa.streams == []


def test_start_prefers_48_khz_when_both_devices_support_it():
    p = started_processor()
    assert p.sample_rate == 48000
    assert p.pa.streams[0].kwargs["rate"] == 48000


def test_start_picks_a_rate_both_devices_support():
    FakePyAudio.devices = [
        device("Mic", WASAPI, inputs=1, outputs=0, rates=(48000, 44100)),
        device("Speakers", WASAPI, inputs=0, outputs=2, rates=(44100, 96000)),
    ]
    p = AudioProcessor()
    p.set_input_device(0)
    p.set_output_device(1)
    p.start()
    assert p.sample_rate == 44100


def test_stop_closes_the_stream():
    p = started_processor()
    stream = p.pa.streams[0]

    p.stop()

    assert not p.running
    assert not stream.started
    assert stream.closed
    assert p.stream is None


def test_stop_before_start_is_harmless():
    AudioProcessor().stop()


def test_failed_start_leaves_the_engine_stopped():
    FakePyAudio.open_error = OSError("device unavailable")
    p = started_processor()
    assert not p.running
    assert p.stream is None


def test_callback_processes_audio_while_running():
    p = started_processor()
    p.set_gain(-6.0)
    pcm = to_pcm(sine(300.0, 0.5, seconds=0.5))

    out = b"".join(p.pa.streams[0].feed(pcm[i : i + 1024].tobytes()) for i in range(0, 23 * 1024, 1024))

    processed = np.frombuffer(out, dtype=np.int16)
    assert len(processed) == 23 * 1024
    assert rms(processed[-4096:]) < rms(pcm[:4096])


def test_callback_returns_silence_when_stopped():
    p = started_processor()
    stream = p.pa.streams[0]
    p.running = False

    out = stream.feed(to_pcm(sine(300.0, 0.5, seconds=0.1))[:1024].tobytes())

    assert out == b"\x00" * 2048


def test_callback_returns_silence_when_there_is_no_input():
    p = started_processor()
    out, flag = p.audio_callback(None, 512, {}, 0)
    assert out == b"\x00" * 1024
    assert flag == pyaudio.paContinue


def test_level_meter_reports_the_input_rms(qapp):
    p = AudioProcessor()
    levels = []
    p.level_changed.connect(levels.append)

    p.apply_filters(to_pcm(sine(1000.0, 0.5, seconds=0.1))[:4800].tobytes())

    assert levels == [pytest.approx(0.5 / np.sqrt(2), rel=0.01)]


def test_level_meter_keeps_working_while_effects_are_bypassed(qapp):
    p = AudioProcessor()
    p.set_effects_enabled(False)
    levels = []
    p.level_changed.connect(levels.append)

    p.apply_filters(to_pcm(sine(1000.0, 0.25, seconds=0.1))[:4800].tobytes())

    assert levels == [pytest.approx(0.25 / np.sqrt(2), rel=0.01)]
