"""Tests for the Westinghouse infrared protocol codes and commands."""

import pytest

from homeassistant.components.westinghouse_infrared.infrared_protocols.codes.westinghouse.fan import (
    _SPEED_1_TIMINGS,
    _SPEED_2_TIMINGS,
    _SPEED_3_TIMINGS,
    _TURN_OFF_TIMINGS,
    WestinghouseFanCode,
)
from homeassistant.components.westinghouse_infrared.infrared_protocols.commands.westinghouse import (
    WestinghouseFanCommand,
)

_EXPECTED_TIMINGS = {
    WestinghouseFanCode.TURN_OFF: _TURN_OFF_TIMINGS,
    WestinghouseFanCode.SPEED_1: _SPEED_1_TIMINGS,
    WestinghouseFanCode.SPEED_2: _SPEED_2_TIMINGS,
    WestinghouseFanCode.SPEED_3: _SPEED_3_TIMINGS,
}


@pytest.mark.parametrize(
    "code",
    [
        WestinghouseFanCode.TURN_OFF,
        WestinghouseFanCode.SPEED_1,
        WestinghouseFanCode.SPEED_2,
        WestinghouseFanCode.SPEED_3,
    ],
)
def test_code_to_command_timings(code: WestinghouseFanCode) -> None:
    """Test each code maps to the expected raw timings and 38 kHz carrier."""
    command = code.to_command()

    assert isinstance(command, WestinghouseFanCommand)
    assert command.get_raw_timings() == _EXPECTED_TIMINGS[code]
    assert command.modulation == 38000
    assert command.repeat_count == 0


def test_command_repeat_count() -> None:
    """Test the command repeats the frame when repeat_count is set."""
    command = WestinghouseFanCode.SPEED_1.to_command(repeat_count=2)

    assert command.repeat_count == 2
    timings = command.get_raw_timings()
    frame = _SPEED_1_TIMINGS
    assert timings == frame + [-96000] + frame + [-96000] + frame


# --- from_raw_timings decoder tests ---


@pytest.mark.parametrize(
    ("code", "reference_timings"),
    [
        pytest.param(
            WestinghouseFanCode.TURN_OFF,
            _TURN_OFF_TIMINGS,
            id="turn_off",
        ),
        pytest.param(
            WestinghouseFanCode.SPEED_1,
            _SPEED_1_TIMINGS,
            id="speed_1",
        ),
        pytest.param(
            WestinghouseFanCode.SPEED_2,
            _SPEED_2_TIMINGS,
            id="speed_2",
        ),
        pytest.param(
            WestinghouseFanCode.SPEED_3,
            _SPEED_3_TIMINGS,
            id="speed_3",
        ),
    ],
)
def test_from_raw_timings_exact(
    code: WestinghouseFanCode,
    reference_timings: list[int],
) -> None:
    """Test from_raw_timings decodes a full frame exactly."""
    assert WestinghouseFanCode.from_raw_timings(reference_timings) == code


@pytest.mark.parametrize(
    ("code", "reference_timings"),
    [
        pytest.param(
            WestinghouseFanCode.TURN_OFF,
            _TURN_OFF_TIMINGS,
            id="turn_off",
        ),
        pytest.param(
            WestinghouseFanCode.SPEED_1,
            _SPEED_1_TIMINGS,
            id="speed_1",
        ),
        pytest.param(
            WestinghouseFanCode.SPEED_2,
            _SPEED_2_TIMINGS,
            id="speed_2",
        ),
        pytest.param(
            WestinghouseFanCode.SPEED_3,
            _SPEED_3_TIMINGS,
            id="speed_3",
        ),
    ],
)
def test_from_raw_timings_with_tolerance(
    code: WestinghouseFanCode,
    reference_timings: list[int],
) -> None:
    """Test from_raw_timings tolerates small timing offsets (+100 µs)."""
    offset_timings = [t + 100 if t > 0 else t - 100 for t in reference_timings]
    assert WestinghouseFanCode.from_raw_timings(offset_timings) == code


def test_from_raw_timings_unknown() -> None:
    """Test from_raw_timings returns None for unknown timings."""
    assert WestinghouseFanCode.from_raw_timings([1, 2, 3, 4]) is None


def test_from_raw_timings_empty() -> None:
    """Test from_raw_timings returns None for empty timings."""
    assert WestinghouseFanCode.from_raw_timings([]) is None
