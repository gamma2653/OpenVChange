"""The engine with more than one route: one stream per device, linked."""

import numpy as np
import pytest

from openvchange.audio import AudioProcessor, AudioStartError, Route
from openvchange.routing import LIMIT_KNEE
from tests.fakes import WASAPI, FakeStream, device
from tests.helpers import dominant_frequency, from_pcm, rms, sine, to_pcm

MIC_A, MIC_B, SPEAKERS, CABLE, MATRIX_IN, MATRIX_OUT = range(6)
BLOCK = 1024


@pytest.fixture(autouse=True)
def devices(fake_pyaudio):
    fake_pyaudio.devices = [
        device("Mic A", WASAPI, inputs=1, outputs=0),
        device("Mic B", WASAPI, inputs=2, outputs=0),
        device("Speakers", WASAPI, inputs=0, outputs=2),
        device("Cable", WASAPI, inputs=0, outputs=2),
        device("Matrix In", WASAPI, inputs=8, outputs=0, all_channels_only=True),
        device("Matrix Out", WASAPI, inputs=0, outputs=8, all_channels_only=True),
    ]


def engine(*routes: tuple[int, int]) -> AudioProcessor:
    """An engine with a route per (input device, output device)."""
    p = AudioProcessor()
    p.remove_route(p.routes[0])
    for input_device, output_device in routes:
        route = p.add_route()
        route.input_device = input_device
        route.output_device = output_device
    return p


def capturing(p: AudioProcessor, input_device: int) -> FakeStream:
    (stream,) = (s for s in p.streams if s.kwargs["input_device_index"] == input_device)
    return stream


def playing(p: AudioProcessor, output_device: int) -> FakeStream:
    (stream,) = (s for s in p.streams if s.kwargs["output_device_index"] == output_device)
    return stream


def pump(p: AudioProcessor, captured: dict[int, np.ndarray], blocks: int = 40) -> dict[int, np.ndarray]:
    """Run the streams in turn, as devices with one clock would.

    `captured` gives the signal on each input device, with one column per channel of
    its stream. Returns what each output device played, in the same form.
    """
    played = {s.kwargs["output_device_index"]: [] for s in p.streams if s.kwargs["output"]}
    for block in range(blocks):
        for input_device, x in captured.items():
            capturing(p, input_device).feed(to_pcm(x[block * BLOCK : (block + 1) * BLOCK]).tobytes())
        for output_device, heard in played.items():
            stream = playing(p, output_device)
            pcm = np.frombuffer(stream.pull(BLOCK), dtype=np.int16)
            heard.append(from_pcm(pcm).reshape(-1, stream.kwargs["channels"]))
    return {output_device: np.concatenate(heard).squeeze() for output_device, heard in played.items()}


def tone(freq: float, amplitude: float = 0.25) -> np.ndarray:
    return sine(freq, amplitude, seconds=1.0)


# --- which streams are opened -------------------------------------------------------


def test_a_single_route_still_shares_one_stream_between_its_devices():
    p = engine((MIC_A, SPEAKERS))
    p.start()
    (stream,) = p.streams
    assert stream.kwargs["input"] and stream.kwargs["output"]
    assert p.routes[0].link is None


def test_one_input_to_two_outputs_opens_a_stream_per_device():
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    p.start()

    assert len(p.streams) == 3
    assert all(s.started for s in p.streams)
    assert not capturing(p, MIC_A).kwargs["output"]
    assert not playing(p, SPEAKERS).kwargs["input"]
    assert not playing(p, CABLE).kwargs["input"]
    assert {s.kwargs["rate"] for s in p.streams} == {48000}
    assert {s.kwargs["frames_per_buffer"] for s in p.streams} == {1024}
    assert {s.kwargs["channels"] for s in p.streams} == {1}


def test_two_inputs_to_one_output_open_three_streams():
    p = engine((MIC_A, SPEAKERS), (MIC_B, SPEAKERS))
    p.start()
    assert len(p.streams) == 3
    assert playing(p, SPEAKERS).started


def test_start_is_refused_while_a_route_lacks_a_device():
    p = engine((MIC_A, SPEAKERS), (MIC_B, SPEAKERS))
    p.routes[1].output_device = None
    with pytest.raises(AudioStartError, match="Select an input and an output device first"):
        p.start()
    assert not p.running
    assert p.streams == []


def test_the_sample_rate_is_one_that_every_device_supports(fake_pyaudio):
    fake_pyaudio.devices = [
        device("Mic A", WASAPI, inputs=1, outputs=0, rates=(48000, 44100, 32000)),
        device("Mic B", WASAPI, inputs=1, outputs=0, rates=(48000, 32000)),
        device("Speakers", WASAPI, inputs=0, outputs=2, rates=(44100, 32000)),
    ]
    p = engine((0, 2), (1, 2))
    p.start()
    assert p.sample_rate == 32000
    assert {s.kwargs["rate"] for s in p.streams} == {32000}
    assert {r.effects.sample_rate for r in p.routes} == {32000}


def test_stop_closes_every_stream():
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    p.start()
    streams = list(p.streams)

    p.stop()

    assert all(s.closed for s in streams)
    assert p.streams == []
    assert all(r.link is None for r in p.routes)


def test_a_stream_that_cannot_be_opened_closes_the_ones_that_were(monkeypatch):
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    really_open = p.pa.open

    def open_all_but_the_cable(**kwargs):
        if kwargs["output_device_index"] == CABLE:
            raise OSError(-9985, "Device unavailable")
        return really_open(**kwargs)

    monkeypatch.setattr(p.pa, "open", open_all_but_the_cable)

    with pytest.raises(AudioStartError, match="^Device unavailable$"):
        p.start()

    assert not p.running
    assert p.streams == []
    assert all(s.closed for s in p.pa.streams)


def test_the_routes_cannot_be_changed_while_running():
    p = engine((MIC_A, SPEAKERS))
    p.start()
    for change in (p.add_route, lambda: p.remove_route(p.routes[0])):
        with pytest.raises(RuntimeError, match="while audio is running"):
            change()
    assert len(p.routes) == 1


def test_a_new_engine_has_one_route():
    p = AudioProcessor()
    assert len(p.routes) == 1
    assert p.effects is p.routes[0].effects
    assert p.routes[0].input_device is None and p.routes[0].output_device is None


# --- what comes out -----------------------------------------------------------------


def test_one_input_reaches_both_of_its_outputs(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    for route in p.routes:
        route.effects.set_gain(-6.0)
    p.start()
    x = tone(300.0, 0.5)

    played = pump(p, {MIC_A: x})

    assert np.array_equal(played[SPEAKERS], played[CABLE])
    settled = played[SPEAKERS][-8192:]
    assert dominant_frequency(settled) == pytest.approx(300.0, abs=1.0)
    assert rms(settled) == pytest.approx(rms(np.tanh(x * 10 ** (-6 / 20))), rel=0.01)


def test_a_link_delays_the_audio_by_one_buffer_when_the_devices_take_turns(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    p.routes[0].effects_enabled = False
    p.start()
    x = tone(300.0)

    played = pump(p, {MIC_A: x})[SPEAKERS]

    assert not played[:BLOCK].any()
    assert np.allclose(played[BLOCK:], x[: len(played) - BLOCK], atol=2 / 32768)


def test_two_inputs_are_mixed_into_one_output(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_B, SPEAKERS))
    for route in p.routes:
        route.effects_enabled = False
    p.start()
    a, b = tone(300.0), tone(1000.0)

    played = pump(p, {MIC_A: a, MIC_B: b})[SPEAKERS]

    assert np.allclose(played[BLOCK:], (a + b)[: len(played) - BLOCK], atol=3 / 32768)


def test_each_route_has_effects_of_its_own(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    p.routes[0].effects_enabled = False
    p.routes[1].effects.set_gain(-20.0)
    p.start()
    x = tone(300.0)

    played = pump(p, {MIC_A: x})

    assert rms(played[SPEAKERS][-8192:]) == pytest.approx(rms(x), rel=0.01)
    assert rms(played[CABLE][-8192:]) == pytest.approx(rms(x) / 10, rel=0.02)


def test_a_mix_that_is_too_loud_is_held_below_full_scale(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_B, SPEAKERS))
    for route in p.routes:
        route.effects_enabled = False
    p.start()
    x = tone(300.0, 0.9)

    played = pump(p, {MIC_A: x, MIC_B: x})[SPEAKERS]

    assert LIMIT_KNEE < np.max(np.abs(played)) < 1.0


def test_a_single_route_is_not_touched_by_the_limiter(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    p.routes[0].effects_enabled = False
    p.start()
    x = tone(300.0, 0.99)

    played = pump(p, {MIC_A: x})[SPEAKERS]

    assert np.max(np.abs(played)) == pytest.approx(0.99, abs=1e-3)


def test_levels_say_which_route_they_belong_to(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_B, SPEAKERS))
    p.start()
    seen = []
    p.levels_changed.connect(seen.append)

    pump(p, {MIC_A: tone(300.0, 0.5), MIC_B: tone(300.0, 0.125)}, blocks=4)

    assert {levels.route for levels in seen} == {0, 1}
    assert {round(levels.input_db) for levels in seen if levels.route == 0} == {-6}
    assert {round(levels.input_db) for levels in seen if levels.route == 1} == {-18}


# --- channels -----------------------------------------------------------------------


def test_a_route_can_take_one_channel_of_its_input(qapp):
    p = engine((MIC_B, SPEAKERS))
    p.routes[0].input_channel = 1
    p.routes[0].effects_enabled = False
    p.start()
    left, right = tone(300.0), tone(1000.0)

    assert capturing(p, MIC_B).kwargs["channels"] == 2
    played = pump(p, {MIC_B: np.column_stack([left, right])})[SPEAKERS]

    assert dominant_frequency(played[-8192:]) == pytest.approx(1000.0, abs=1.0)
    assert rms(played[-8192:]) == pytest.approx(rms(right), rel=0.01)


def test_two_routes_can_take_different_channels_of_one_input(qapp):
    p = engine((MIC_B, SPEAKERS), (MIC_B, CABLE))
    p.routes[0].input_channel, p.routes[1].input_channel = 0, 1
    p.start()

    played = pump(p, {MIC_B: np.column_stack([tone(300.0), tone(1000.0)])})

    assert dominant_frequency(played[SPEAKERS][-8192:]) == pytest.approx(300.0, abs=1.0)
    assert dominant_frequency(played[CABLE][-8192:]) == pytest.approx(1000.0, abs=1.0)


def test_routes_can_end_on_single_channels_of_one_output(qapp):
    p = engine((MIC_A, MATRIX_OUT), (MIC_B, MATRIX_OUT))
    p.routes[0].output_channel, p.routes[1].output_channel = 2, 5
    p.start()

    assert len(p.streams) == 3
    assert playing(p, MATRIX_OUT).kwargs["channels"] == 8
    played = pump(p, {MIC_A: tone(300.0), MIC_B: tone(1000.0)})[MATRIX_OUT]

    assert dominant_frequency(played[-8192:, 2]) == pytest.approx(300.0, abs=1.0)
    assert dominant_frequency(played[-8192:, 5]) == pytest.approx(1000.0, abs=1.0)
    assert not played[:, [0, 1, 3, 4, 6, 7]].any()


def test_a_device_that_refuses_one_channel_is_opened_with_all_of_them(qapp):
    p = engine((MATRIX_IN, MATRIX_OUT))
    p.routes[0].effects_enabled = False
    p.start()

    assert capturing(p, MATRIX_IN).kwargs["channels"] == 8
    assert playing(p, MATRIX_OUT).kwargs["channels"] == 8
    x = np.zeros((48000, 8))
    x[:, 3] = tone(300.0, 0.8)
    played = pump(p, {MATRIX_IN: x})[MATRIX_OUT]

    # With no channel chosen, the channels of the input are averaged, and the result
    # is played on every channel of the output.
    assert rms(played[-8192:, 0]) == pytest.approx(rms(x[:, 3]) / 8, rel=0.01)
    assert np.array_equal(played, np.repeat(played[:, :1], 8, axis=1))


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda p: setattr(p.routes[0], "input_channel", 2), "Mic B has no input channel 3."),
        (lambda p: setattr(p.routes[0], "output_channel", 8), "Matrix Out has no output channel 9."),
    ],
)
def test_a_channel_the_device_does_not_have_is_refused(change, problem):
    p = engine((MIC_B, MATRIX_OUT))
    change(p)
    with pytest.raises(AudioStartError, match=f"^{problem}$"):
        p.start()
    assert p.streams == []


# --- failures -----------------------------------------------------------------------


def break_effects(route: Route) -> None:
    def broken(data):
        raise RuntimeError("filter blew up")

    route.effects.process = broken


def test_a_failure_on_one_route_silences_every_output_and_is_reported_once(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_B, SPEAKERS), (MIC_B, CABLE))
    p.start()
    errors = []
    p.error_occurred.connect(errors.append)
    x = tone(300.0, 0.5)
    assert pump(p, {MIC_A: x, MIC_B: x}, blocks=4)[SPEAKERS].any()

    break_effects(p.routes[2])
    played = pump(p, {MIC_A: x, MIC_B: x}, blocks=4)

    assert not played[SPEAKERS].any()
    assert not played[CABLE].any()
    assert errors == ["filter blew up"]
    assert p.failed


def test_restart_clears_a_failure(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    p.start()
    break_effects(p.routes[0])
    pump(p, {MIC_A: tone(300.0)}, blocks=2)
    del p.routes[0].effects.process

    p.start()

    assert not p.failed
    assert pump(p, {MIC_A: tone(300.0)}, blocks=4)[CABLE].any()


def test_outputs_are_silent_once_stopped(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    p.start()
    stream = playing(p, SPEAKERS)
    pump(p, {MIC_A: tone(300.0)}, blocks=4)

    p.running = False

    assert stream.pull(BLOCK) == bytes(2 * BLOCK)


# --- buffer sizes -------------------------------------------------------------------


def test_each_route_has_a_buffer_size_and_a_shared_device_gets_the_larger(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    p.routes[0].chunk_size = 256
    p.routes[1].chunk_size = 2048
    p.start()

    assert capturing(p, MIC_A).kwargs["frames_per_buffer"] == 2048
    assert playing(p, SPEAKERS).kwargs["frames_per_buffer"] == 256
    assert playing(p, CABLE).kwargs["frames_per_buffer"] == 2048
    assert p.routes[0].link.target == 2 * 2048  # sized for the larger end
    assert p.routes[1].link.target == 2 * 2048


def test_a_single_route_opens_its_stream_with_its_own_buffer_size():
    p = engine((MIC_A, SPEAKERS))
    p.routes[0].chunk_size = 512
    p.start()
    assert p.streams[0].kwargs["frames_per_buffer"] == 512


def test_audio_flows_between_ends_with_different_buffer_sizes(qapp):
    p = engine((MIC_A, SPEAKERS), (MIC_A, CABLE))
    p.routes[0].chunk_size = 256
    p.routes[1].chunk_size = 1024
    p.routes[0].effects_enabled = False
    p.start()
    x = tone(300.0)
    microphone, speakers = capturing(p, MIC_A), playing(p, SPEAKERS)

    heard = []
    for block in range(40):
        microphone.feed(to_pcm(x[block * 1024 : (block + 1) * 1024]).tobytes())
        for _ in range(4):
            heard.append(from_pcm(np.frombuffer(speakers.pull(256), dtype=np.int16)))
    played = np.concatenate(heard)

    settled = played[-8192:]
    assert dominant_frequency(settled) == pytest.approx(300.0, abs=1.0)
    assert rms(settled) == pytest.approx(rms(x), rel=0.01)
