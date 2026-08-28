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
from homeassistant.components.westinghouse_infrared.infrared_protocols.codes.westinghouse.fan import (
    WestinghouseFanCode,
)
from homeassistant.const import ATTR_ENTITY_ID, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from tests.common import MockConfigEntry, snapshot_platform
from tests.components.common import assert_availability_follows_source_entity
from tests.components.infrared import EMITTER_ENTITY_ID
from tests.components.infrared.common import MockInfraredEmitterEntity


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
