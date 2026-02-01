"""Test NextDNS diagnostics."""

from unittest.mock import AsyncMock

from syrupy.assertion import SnapshotAssertion

from homeassistant.core import HomeAssistant

from . import init_integration

from tests.common import MockConfigEntry
from tests.components.diagnostics import get_diagnostics_for_config_entry
from tests.typing import ClientSessionGenerator


async def test_entry_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    snapshot: SnapshotAssertion,
    mock_config_entry: MockConfigEntry,
    mock_nextdns_client: AsyncMock,
) -> None:
    """Test config entry diagnostics."""
    await init_integration(hass, mock_config_entry)

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    # The subentry_id and profiles dict keys are dynamically generated,
    # so we verify the structure without the dynamic IDs
    assert "config_entry" in result
    assert "profiles" in result
    assert len(result["profiles"]) == 1

    # Get the single profile's data (regardless of its dynamic ID)
    profile_data = next(iter(result["profiles"].values()))

    assert "dnssec_coordinator_data" in profile_data
    assert "encryption_coordinator_data" in profile_data
    assert "ip_versions_coordinator_data" in profile_data
    assert "protocols_coordinator_data" in profile_data
    assert "settings_coordinator_data" in profile_data
    assert "status_coordinator_data" in profile_data
