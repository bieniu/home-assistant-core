"""Common fixtures for the Westinghouse Infrared tests."""

from collections.abc import Generator
from unittest.mock import patch

import pytest

from homeassistant.components.westinghouse_infrared import PLATFORMS
from homeassistant.components.westinghouse_infrared.const import (
    CONF_INFRARED_EMITTER_ENTITY_ID,
    DOMAIN,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from tests.common import MockConfigEntry
from tests.components.infrared import EMITTER_ENTITY_ID as MOCK_INFRARED_ENTITY_ID

ENTRY_ID = "01JTEST0000000000000000000"


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry for the Westinghouse fan."""
    return MockConfigEntry(
        domain=DOMAIN,
        entry_id=ENTRY_ID,
        title="Westinghouse Fan via Test IR emitter",
        data={CONF_INFRARED_EMITTER_ENTITY_ID: MOCK_INFRARED_ENTITY_ID},
        unique_id=f"fan_{MOCK_INFRARED_ENTITY_ID}",
    )


@pytest.fixture
def platforms() -> list[Platform]:
    """Return platforms to set up."""
    return PLATFORMS


@pytest.fixture
def mock_westinghouse_code_to_command() -> Generator[None]:
    """Patch WestinghouseFanCode.to_command to return the code directly.

    This allows tests to assert on the high-level code enum value
    rather than the raw Westinghouse timings.
    """
    with patch(
        "homeassistant.components.westinghouse_infrared.infrared_protocols.codes.westinghouse.fan.WestinghouseFanCode.to_command",
        autospec=True,
        side_effect=lambda self, **kwargs: self,
    ):
        yield


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_infrared_emitter_entity,
    mock_westinghouse_code_to_command: None,
    platforms: list[Platform],
) -> MockConfigEntry:
    """Set up the Westinghouse Infrared integration for testing."""
    mock_config_entry.add_to_hass(hass)

    with patch("homeassistant.components.westinghouse_infrared.PLATFORMS", platforms):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    return mock_config_entry


@pytest.fixture
def fan_entity_id(
    entity_registry: er.EntityRegistry,
    init_integration: MockConfigEntry,
) -> str:
    """Return the entity_id of the Westinghouse fan entity for the test entry."""
    entries = er.async_entries_for_config_entry(
        entity_registry, init_integration.entry_id
    )
    assert len(entries) == 1
    return entries[0].entity_id
