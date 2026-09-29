"""The engine's stream handling: devices, sample rates, the callback, and the level meter."""

import numpy as np
import pyaudio
import pytest

from openvchange.audio import AudioProcessor, AudioStartError, Levels
from tests.fakes import WASAPI, FakePyAudio, device
from tests.helpers import rms, sine, to_pcm

# --- streams ---------------------------------------------------------------------

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


def test_start_without_devices_is_refused():
    p = AudioProcessor()
    with pytest.raises(AudioStartError, match="Select an input and an output device"):
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


def test_start_reports_why_the_stream_could_not_be_opened():
    FakePyAudio.open_error = OSError(-9996, "Invalid input device (no default output device)")
    with pytest.raises(AudioStartError, match=r"^Invalid input device \(no default output device\)$"):
        started_processor()


def test_failed_open_leaves_the_engine_stopped():
    FakePyAudio.open_error = OSError("device unavailable")
    p = AudioProcessor()
    p.set_input_device(MIC)
    p.set_output_device(SPEAKERS)

    with pytest.raises(AudioStartError, match="device unavailable"):
        p.start()

    assert not p.running
    assert p.stream is None


def test_stream_that_opens_but_will_not_start_is_closed():
    FakePyAudio.start_error = OSError("Unanticipated host error", -9999)
    p = AudioProcessor()
    p.set_input_device(MIC)
    p.set_output_device(SPEAKERS)

    with pytest.raises(AudioStartError, match="Unanticipated host error"):
        p.start()

    assert not p.running
    assert p.stream is None
    assert p.pa.streams[0].closed


def test_engine_can_start_after_a_failed_attempt():
    FakePyAudio.open_error = OSError("device unavailable")
    p = AudioProcessor()
    p.set_input_device(MIC)
    p.set_output_device(SPEAKERS)
    with pytest.raises(AudioStartError):
        p.start()

    FakePyAudio.open_error = None
    p.start()

    assert p.running


def test_starting_twice_does_not_leak_the_first_stream():
    p = started_processor()
    first = p.pa.streams[0]

    p.start()

    assert first.closed
    assert p.stream is p.pa.streams[1]


def test_callback_processes_audio_while_running():
    p = started_processor()
    p.effects.set_gain(-6.0)
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


# --- levels for the meters ---------------------------------------------------


def metered(p: AudioProcessor, x: np.ndarray, buffer: int = 1024) -> list[Levels]:
    """Feed a signal through the engine and collect what it tells the meters."""
    p.sample_rate = 48000
    p.effects.set_sample_rate(48000)
    p.reset_meters()
    seen = []
    p.levels_changed.connect(seen.append)
    pcm = to_pcm(x)
    for start in range(0, len(pcm) - buffer + 1, buffer):
        p.apply_filters(pcm[start : start + buffer].tobytes())
    return seen


def test_levels_are_peaks_in_db(qapp):
    seen = metered(AudioProcessor(), sine(1000.0, 0.5))

    assert seen
    for levels in seen:
        assert levels.input_db == pytest.approx(-6.02, abs=0.01)
        # A neutral chain still passes through the soft clipper.
        assert levels.output_db == pytest.approx(20 * np.log10(np.tanh(0.5)), abs=0.01)
        assert not levels.input_clipped
        assert not levels.output_clipped


@pytest.mark.parametrize("buffer", [128, 1024, 4096])
def test_levels_are_reported_about_thirty_times_per_second_whatever_the_buffer_size(qapp, buffer):
    seen = metered(AudioProcessor(), sine(1000.0, 0.5, seconds=2.0), buffer)

    whole_buffers = (2 * 48000) // buffer
    per_update = max(1, -(-1600 // buffer))  # buffers needed to cover a thirtieth of a second
    assert len(seen) == whole_buffers // per_update
    assert len(seen) <= 60
    assert all(levels.seconds == pytest.approx(per_update * buffer / 48000) for levels in seen)


def test_a_peak_between_two_reports_is_not_lost(qapp):
    x = np.zeros(48000)
    x[300] = 0.8  # one loud sample, early in the first stretch
    seen = metered(AudioProcessor(), x, buffer=128)

    assert seen[0].input_db == pytest.approx(20 * np.log10(0.8), abs=0.01)
    assert seen[1].input_db < -100


def test_silence_reads_far_below_the_scale(qapp):
    seen = metered(AudioProcessor(), np.zeros(9600))
    assert seen[0].input_db == -200.0
    assert seen[0].output_db == -200.0


def test_input_that_reaches_full_scale_is_flagged(qapp):
    assert metered(AudioProcessor(), sine(1000.0, 1.0))[0].input_clipped
    assert not metered(AudioProcessor(), sine(1000.0, 0.98))[0].input_clipped


def test_output_pushed_past_full_scale_is_flagged(qapp):
    p = AudioProcessor()
    p.effects.set_gain(12.0)
    p.effects.reset()

    loud = metered(p, sine(1000.0, 0.5))[-1]

    assert loud.output_clipped
    assert not loud.input_clipped
    assert loud.output_db < 0.0  # the soft clipper keeps the output below full scale


def test_output_just_below_full_scale_is_not_flagged(qapp):
    p = AudioProcessor()
    p.effects.set_gain(5.0)  # 0.5 becomes 0.89
    p.effects.reset()
    assert not metered(p, sine(1000.0, 0.5))[-1].output_clipped


def test_bypassed_output_is_metered_as_the_input(qapp):
    p = AudioProcessor()
    p.effects.set_gain(30.0)
    p.set_effects_enabled(False)

    seen = metered(p, sine(1000.0, 0.25))

    assert seen[0].output_db == seen[0].input_db == pytest.approx(-12.04, abs=0.01)
    assert not seen[0].output_clipped


def test_meters_start_afresh_with_each_stream(qapp):
    p = started_processor()
    seen = []
    p.levels_changed.connect(seen.append)
    loud = to_pcm(sine(1000.0, 0.9, seconds=0.02))[:512].tobytes()
    p.pa.streams[0].feed(loud)  # not enough audio for a report yet
    assert not seen

    p.start()
    quiet = to_pcm(sine(1000.0, 0.1, seconds=0.1))
    for start in range(0, 4096, 1024):
        p.pa.streams[-1].feed(quiet[start : start + 1024].tobytes())

    assert seen[0].input_db == pytest.approx(-20.0, abs=0.05)


# --- failures while running ------------------------------------------------------


def failing_processor(qapp) -> tuple[AudioProcessor, list[str]]:
    p = started_processor()
    errors = []
    p.error_occurred.connect(errors.append)

    def broken(data):
        raise RuntimeError("filter blew up")

    p.effects.process = broken
    return p, errors


def test_processing_failure_outputs_silence_not_the_raw_voice(qapp):
    p, _ = failing_processor(qapp)
    voice = to_pcm(sine(300.0, 0.5, seconds=0.1))[:1024].tobytes()

    out = p.pa.streams[0].feed(voice)

    assert out == b"\x00" * len(voice)


def test_processing_failure_is_reported_once(qapp):
    p, errors = failing_processor(qapp)
    voice = to_pcm(sine(300.0, 0.5, seconds=0.1))[:1024].tobytes()

    for _ in range(5):
        assert p.pa.streams[0].feed(voice) == b"\x00" * len(voice)

    assert errors == ["filter blew up"]
    assert p.failed


def test_restart_clears_a_processing_failure(qapp):
    p, errors = failing_processor(qapp)
    voice = to_pcm(sine(300.0, 0.5, seconds=0.1))[:1024].tobytes()
    p.pa.streams[0].feed(voice)
    del p.effects.process  # the fault is gone

    p.start()
    out = p.pa.streams[-1].feed(voice)

    assert not p.failed
    assert np.frombuffer(out, dtype=np.int16).any()
    assert len(errors) == 1


def test_bypass_still_passes_audio_through_untouched(qapp):
    p = started_processor()
    p.set_effects_enabled(False)
    voice = to_pcm(sine(300.0, 0.5, seconds=0.1))[:1024].tobytes()
    assert p.pa.streams[0].feed(voice) == voice


# --- devices ---------------------------------------------------------------------


def test_devices_are_listed_with_their_host_api():
    p = AudioProcessor()

    wasapi = p.list_devices()
    everything = p.list_devices(all_host_apis=True)

    assert [d.name for d in wasapi] == [
        "Microphone (USB Audio)",
        "Speakers (Realtek)",
        "CABLE Input (VB-Audio Virtual Cable)",
    ]
    assert {d.host_api for d in wasapi} == {"Windows WASAPI"}
    assert [d.index for d in everything] == [0, 1, 2, 3, 4]
    assert [d.is_input for d in everything] == [True, False, True, False, False]
    assert everything[0].identity == "MME: Microphone (MME)"


def test_refresh_restarts_portaudio_to_scan_again():
    p = AudioProcessor()
    first = p.pa
    FakePyAudio.devices = [*FakePyAudio.devices, device("Headset", WASAPI, inputs=1, outputs=2)]
    assert len(p.list_devices(all_host_apis=True)) == 5

    p.refresh_devices()

    assert first.terminated
    assert p.pa is not first
    assert len(p.list_devices(all_host_apis=True)) == 6


def test_refresh_forgets_device_indexes_because_they_no_longer_mean_anything():
    p = AudioProcessor()
    p.set_input_device(MIC)
    p.set_output_device(SPEAKERS)

    p.refresh_devices()

    with pytest.raises(AudioStartError, match="Select an input and an output device"):
        p.start()


def test_refresh_is_refused_while_running():
    p = started_processor()
    with pytest.raises(RuntimeError, match="while audio is running"):
        p.refresh_devices()
    assert not p.pa.terminated


def test_shut_down_releases_portaudio_once():
    p = started_processor()
    pa = p.pa
    stream = pa.streams[0]

    p.shut_down()
    p.shut_down()

    assert stream.closed
    assert pa.terminated
    assert FakePyAudio.alive == 0
