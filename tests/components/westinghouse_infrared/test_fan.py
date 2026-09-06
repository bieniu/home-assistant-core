"""Tests for the Westinghouse Infrared fan platform."""

import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    DOMAIN as FAN_DOMAIN,
    SERVICE_SET_PERCENTAGE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    FanEntityFeature,
)
from homeassistant.components.infrared import InfraredReceivedSignal
from homeassistant.components.westinghouse_infrared.infrared_protocols.codes.westinghouse.fan import (
    _SPEED_1_TIMINGS,
    _SPEED_2_TIMINGS,
    _SPEED_3_TIMINGS,
    _TURN_OFF_TIMINGS,
    WestinghouseFanCode,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from tests.common import MockConfigEntry, snapshot_platform
from tests.components.common import assert_availability_follows_source_entity
from tests.components.infrared import EMITTER_ENTITY_ID, RECEIVER_ENTITY_ID
from tests.components.infrared.common import (
    MockInfraredEmitterEntity,
    MockInfraredReceiverEntity,
)

_CODE_TO_TIMINGS = {
    WestinghouseFanCode.TURN_OFF: _TURN_OFF_TIMINGS,
    WestinghouseFanCode.SPEED_1: _SPEED_1_TIMINGS,
    WestinghouseFanCode.SPEED_2: _SPEED_2_TIMINGS,
    WestinghouseFanCode.SPEED_3: _SPEED_3_TIMINGS,
}


@pytest.fixture
def platforms() -> list[Platform]:
    """Return platforms to set up."""
    return [Platform.FAN]


@pytest.mark.usefixtures("init_integration")
async def test_entities(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the fan entity is created with correct attributes and attached to a device."""
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)

    device_entry = device_registry.async_get_device_by_identifier(
        ("westinghouse_infrared", mock_config_entry.entry_id),
        mock_config_entry.entry_id,
    )
    assert device_entry
    entity_entries = er.async_entries_for_config_entry(
        entity_registry, mock_config_entry.entry_id
    )
    for entity_entry in entity_entries:
        assert entity_entry.device_id == device_entry.id


@pytest.mark.usefixtures("init_integration")
async def test_availability_follows_emitter(
    hass: HomeAssistant,
    fan_entity_id: str,
) -> None:
    """Test the fan becomes unavailable when the IR emitter is unavailable."""
    await assert_availability_follows_source_entity(
        hass, fan_entity_id, EMITTER_ENTITY_ID
    )


@pytest.mark.usefixtures("init_integration")
async def test_turn_on_without_percentage(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    fan_entity_id: str,
) -> None:
    """Test turning on without a percentage sends SPEED_1 and reports 33%."""
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: fan_entity_id},
        blocking=True,
    )

    assert mock_infrared_emitter_entity.send_command_calls == [
        WestinghouseFanCode.SPEED_1
    ]

    state = hass.states.get(fan_entity_id)
    assert state
    assert state.state == "on"
    assert state.attributes[ATTR_PERCENTAGE] == 33


@pytest.mark.usefixtures("init_integration")
async def test_turn_off(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    fan_entity_id: str,
) -> None:
    """Test turning off sends the TURN_OFF code."""
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: fan_entity_id},
        blocking=True,
    )
    mock_infrared_emitter_entity.send_command_calls.clear()

    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: fan_entity_id},
        blocking=True,
    )

    assert mock_infrared_emitter_entity.send_command_calls == [
        WestinghouseFanCode.TURN_OFF
    ]

    state = hass.states.get(fan_entity_id)
    assert state
    assert state.state == "off"


@pytest.mark.parametrize(
    ("percentage", "expected_code"),
    [
        pytest.param(0, WestinghouseFanCode.TURN_OFF, id="off"),
        pytest.param(33, WestinghouseFanCode.SPEED_1, id="speed_1"),
        pytest.param(50, WestinghouseFanCode.SPEED_2, id="speed_2"),
        pytest.param(100, WestinghouseFanCode.SPEED_3, id="speed_3"),
        pytest.param(20, WestinghouseFanCode.SPEED_1, id="speed_1_low"),
    ],
)
@pytest.mark.usefixtures("init_integration")
async def test_set_percentage(
    hass: HomeAssistant,
    mock_infrared_emitter_entity: MockInfraredEmitterEntity,
    fan_entity_id: str,
    percentage: int,
    expected_code: WestinghouseFanCode,
) -> None:
    """Test setting a percentage sends the correct Westinghouse fan code."""
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_SET_PERCENTAGE,
        {ATTR_ENTITY_ID: fan_entity_id, ATTR_PERCENTAGE: percentage},
        blocking=True,
    )

    assert mock_infrared_emitter_entity.send_command_calls == [expected_code]

    state = hass.states.get(fan_entity_id)
    assert state
    if percentage == 0:
        assert state.state == "off"
        assert state.attributes[ATTR_PERCENTAGE] == 0
    else:
        assert state.state == "on"
        assert state.attributes[ATTR_PERCENTAGE] == percentage


@pytest.mark.usefixtures("init_integration")
async def test_state_attributes(
    hass: HomeAssistant,
    fan_entity_id: str,
) -> None:
    """Test the fan exposes the expected state attributes."""
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: fan_entity_id, ATTR_PERCENTAGE: 66},
        blocking=True,
    )

    state = hass.states.get(fan_entity_id)
    assert state
    assert state.attributes[ATTR_PERCENTAGE] == 66
    assert (
        state.attributes["supported_features"]
        == FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
    )

    entity = hass.data[FAN_DOMAIN].get_entity(fan_entity_id)
    assert entity is not None
    assert entity.speed_count == 3


# --- Receiver tests ---


@pytest.mark.parametrize("has_receiver", [True])
@pytest.mark.usefixtures("init_integration")
async def test_receiver_updates_state_on_turn_off(
    hass: HomeAssistant,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    fan_entity_id: str,
) -> None:
    """Test a received turn-off signal sets the fan to off."""
    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: fan_entity_id},
        blocking=True,
    )
    state = hass.states.get(fan_entity_id)
    assert state is not None
    assert state.state == "on"

    mock_infrared_receiver_entity._handle_received_signal(
        InfraredReceivedSignal(timings=_TURN_OFF_TIMINGS)
    )
    await hass.async_block_till_done()

    state = hass.states.get(fan_entity_id)
    assert state is not None
    assert state.state == "off"
    assert state.attributes[ATTR_PERCENTAGE] == 0


@pytest.mark.parametrize("has_receiver", [True])
@pytest.mark.usefixtures("init_integration")
@pytest.mark.parametrize(
    ("code", "expected_percentage"),
    [
        pytest.param(WestinghouseFanCode.SPEED_1, 33, id="speed_1"),
        pytest.param(WestinghouseFanCode.SPEED_2, 66, id="speed_2"),
        pytest.param(WestinghouseFanCode.SPEED_3, 100, id="speed_3"),
    ],
)
async def test_receiver_updates_state_on_speeds(
    hass: HomeAssistant,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    fan_entity_id: str,
    code: WestinghouseFanCode,
    expected_percentage: int,
) -> None:
    """Test a received speed signal turns the fan on at the expected percentage."""
    mock_infrared_receiver_entity._handle_received_signal(
        InfraredReceivedSignal(timings=_CODE_TO_TIMINGS[code])
    )
    await hass.async_block_till_done()

    state = hass.states.get(fan_entity_id)
    assert state is not None
    assert state.state == "on"
    assert state.attributes[ATTR_PERCENTAGE] == expected_percentage


@pytest.mark.parametrize("has_receiver", [True])
@pytest.mark.usefixtures("init_integration")
async def test_receiver_ignores_unknown_signal(
    hass: HomeAssistant,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    fan_entity_id: str,
) -> None:
    """Test an unknown IR signal does not change fan state."""
    mock_infrared_receiver_entity._handle_received_signal(
        InfraredReceivedSignal(timings=[1, 2, 3, 4])
    )
    await hass.async_block_till_done()

    state = hass.states.get(fan_entity_id)
    assert state is not None
    assert state.state == "off"
    assert state.attributes[ATTR_PERCENTAGE] == 0


@pytest.mark.parametrize("has_receiver", [True])
@pytest.mark.usefixtures("init_integration")
async def test_receiver_resubscribes_after_unavailable(
    hass: HomeAssistant,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    fan_entity_id: str,
) -> None:
    """Test the fan resubscribes when the receiver becomes available again."""
    state = hass.states.get(fan_entity_id)
    assert state is not None
    assert state.state != STATE_UNAVAILABLE

    hass.states.async_set(RECEIVER_ENTITY_ID, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    state = hass.states.get(fan_entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE

    hass.states.async_set(RECEIVER_ENTITY_ID, "unknown")
    await hass.async_block_till_done()
    state = hass.states.get(fan_entity_id)
    assert state is not None
    assert state.state != STATE_UNAVAILABLE

    mock_infrared_receiver_entity._handle_received_signal(
        InfraredReceivedSignal(timings=_SPEED_2_TIMINGS)
    )
    await hass.async_block_till_done()

    state = hass.states.get(fan_entity_id)
    assert state is not None
    assert state.state == "on"
    assert state.attributes[ATTR_PERCENTAGE] == 66


@pytest.mark.parametrize("has_receiver", [True])
@pytest.mark.usefixtures("init_integration")
async def test_receiver_tolerance(
    hass: HomeAssistant,
    mock_infrared_receiver_entity: MockInfraredReceiverEntity,
    fan_entity_id: str,
) -> None:
    """Test the receiver decoder tolerates small timing offsets."""
    reference_timings = _SPEED_1_TIMINGS
    offset_timings = [t + 100 if t > 0 else t - 100 for t in reference_timings]

    mock_infrared_receiver_entity._handle_received_signal(
        InfraredReceivedSignal(timings=offset_timings)
    )
    await hass.async_block_till_done()

    state = hass.states.get(fan_entity_id)
    assert state is not None
    assert state.state == "on"
    assert state.attributes[ATTR_PERCENTAGE] == 33
