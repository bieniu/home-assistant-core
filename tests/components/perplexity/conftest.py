"""Tests helpers for the Perplexity integration."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.perplexity.const import DOMAIN
from homeassistant.const import CONF_API_KEY, CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from tests.common import MockConfigEntry


@pytest.fixture(autouse=True)
async def setup_ha(hass: HomeAssistant) -> None:
    """Set up Home Assistant."""
    assert await async_setup_component(hass, "homeassistant", {})


@pytest.fixture
def mock_config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Mock a config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Perplexity",
        data={
            CONF_API_KEY: "test_api_key",
        },
        subentries_data=[
            {
                "data": {CONF_MODEL: "sonar"},
                "subentry_type": "ai_task_data",
                "title": "Sonar",
                "subentry_id": "ulid-ai-task",
                "unique_id": None,
            },
        ],
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_perplexity_client() -> Generator[MagicMock]:
    """Mock the Perplexity client."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity", autospec=True
    ) as mock_client:
        client = mock_client.return_value
        client.platform_headers = MagicMock(return_value={})
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=MagicMock())
        yield client


@pytest.fixture
async def mock_setup_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_perplexity_client: MagicMock,
) -> MockConfigEntry:
    """Set up the Perplexity integration for testing."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()
    return mock_config_entry
