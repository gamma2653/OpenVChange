"""The level meter widget."""

import pytest
from PySide6.QtGui import QColor

from openvchange.widgets import LevelMeter

TICK = 1 / 30


@pytest.fixture
def meter(qapp):
    m = LevelMeter()
    m.resize(260, 16)
    return m


def test_starts_silent(meter):
    assert meter.level_db == -60.0
    assert meter.peak_db == -60.0
    assert not meter.clipped
    assert meter.readout() == "< -60 dB"


def test_jumps_up_to_a_new_level(meter):
    meter.update_level(-10.0, False, TICK)
    assert meter.level_db == -10.0


def test_falls_back_at_a_steady_rate(meter):
    meter.update_level(-10.0, False, TICK)

    meter.update_level(-60.0, False, 0.5)
    assert meter.level_db == pytest.approx(-22.0)

    meter.update_level(-60.0, False, 0.5)
    assert meter.level_db == pytest.approx(-34.0)


def test_falling_stops_at_the_level_of_the_signal(meter):
    meter.update_level(-10.0, False, TICK)
    meter.update_level(-20.0, False, 1.0)
    assert meter.level_db == -20.0


def test_never_leaves_the_scale(meter):
    meter.update_level(-200.0, False, 10.0)
    assert meter.level_db == -60.0
    meter.update_level(9.0, False, TICK)
    assert meter.level_db == 0.0


def test_peak_is_held_then_released(meter):
    meter.update_level(-8.0, False, TICK)
    for _ in range(44):  # a little under a second and a half
        meter.update_level(-40.0, False, TICK)
    assert meter.peak_db == -8.0
    assert meter.readout() == "-8 dB"

    meter.update_level(-40.0, False, TICK)
    meter.update_level(-40.0, False, TICK)
    assert meter.peak_db == pytest.approx(-40.0, abs=1.0)


def test_a_higher_peak_replaces_the_held_one_at_once(meter):
    meter.update_level(-20.0, False, TICK)
    meter.update_level(-5.0, False, TICK)
    assert meter.peak_db == -5.0


def test_clip_light_stays_on_for_a_moment(meter):
    meter.update_level(-1.0, True, TICK)
    assert meter.clipped

    for _ in range(59):
        meter.update_level(-30.0, False, TICK)
    assert meter.clipped

    meter.update_level(-30.0, False, TICK)
    meter.update_level(-30.0, False, TICK)
    assert not meter.clipped


def test_clipping_again_restarts_the_wait(meter):
    meter.update_level(-1.0, True, TICK)
    meter.update_level(-30.0, False, 1.5)
    meter.update_level(-1.0, True, TICK)
    meter.update_level(-30.0, False, 1.5)
    assert meter.clipped


def test_reset_returns_to_silence(meter):
    meter.update_level(-1.0, True, TICK)
    meter.reset()
    assert (meter.level_db, meter.peak_db, meter.clipped) == (-60.0, -60.0, False)


@pytest.mark.parametrize(("level_db", "expected"), [(-60.0, 0.0), (-30.0, 0.5), (0.0, 1.0), (-90.0, 0.0), (6.0, 1.0)])
def test_scale_is_linear_in_db(meter, level_db, expected):
    assert meter.fraction(level_db) == pytest.approx(expected)


def colour_at(meter: LevelMeter, x: int) -> QColor:
    return meter.grab().toImage().pixelColor(x, meter.height() // 2)


def test_bar_is_drawn_as_far_as_the_level(meter):
    # The bar is 241 px wide: the widget less the clip light and the gap beside it.
    meter.update_level(-30.0, False, TICK)

    inside = colour_at(meter, 60)
    outside = colour_at(meter, 200)

    assert inside.green() > inside.red() and inside.green() > inside.blue()
    assert outside != inside


def test_bar_turns_red_near_full_scale(meter):
    meter.update_level(-1.0, False, TICK)
    low = colour_at(meter, 60)
    high = colour_at(meter, 228)
    assert low.green() > low.red()
    assert high.red() > high.green()


def test_clip_light_is_drawn_red_when_lit(meter):
    meter.update_level(-20.0, False, TICK)
    dark = colour_at(meter, 252)
    meter.update_level(-20.0, True, TICK)
    lit = colour_at(meter, 252)

    assert lit.red() > 200 and lit.green() < 80
    assert dark != lit


def test_draws_at_any_size(meter):
    for width in (1, 10, 40, 2000):
        meter.resize(width, 12)
        meter.update_level(-3.0, True, TICK)
        assert not meter.grab().isNull()
