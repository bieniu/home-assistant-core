"""Tests for the Westinghouse Infrared integration setup."""

from homeassistant.components.westinghouse_infrared.const import (
    CONF_INFRARED_EMITTER_ENTITY_ID,
    DOMAIN,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry
from tests.components.infrared import EMITTER_ENTITY_ID as MOCK_INFRARED_ENTITY_ID


async def test_setup_and_unload_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Test setting up and unloading a config entry."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_unique_id_uses_emitter_entity_id(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test the config entry unique_id is derived from the emitter entity id."""
    assert mock_config_entry.unique_id == f"fan_{MOCK_INFRARED_ENTITY_ID}"
    assert mock_config_entry.data == {
        CONF_INFRARED_EMITTER_ENTITY_ID: MOCK_INFRARED_ENTITY_ID,
    }
    assert mock_config_entry.domain == DOMAIN
