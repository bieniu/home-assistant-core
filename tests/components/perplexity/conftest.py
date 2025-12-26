"""Fixtures for Perplexity integration tests."""

from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.components.perplexity.const import CONF_PROMPT, DOMAIN
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component

from tests.common import MockConfigEntry


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.perplexity.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def enable_assist() -> bool:
    """Mock conversation subentry data."""
    return False


@pytest.fixture
def conversation_subentry_data(enable_assist: bool) -> dict[str, Any]:
    """Mock conversation subentry data."""
    res: dict[str, Any] = {
        CONF_MODEL: "sonar",
        CONF_PROMPT: "You are a helpful assistant.",
    }
    if enable_assist:
        res[CONF_LLM_HASS_API] = [llm.LLM_API_ASSIST]
    return res


@pytest.fixture
def mock_config_entry(
    hass: HomeAssistant,
    conversation_subentry_data: dict[str, Any],
) -> MockConfigEntry:
    """Mock a config entry."""
    return MockConfigEntry(
        title="Perplexity",
        domain=DOMAIN,
        data={
            CONF_API_KEY: "test_api_key",
        },
        subentries_data=[
            ConfigSubentryData(
                data=conversation_subentry_data,
                subentry_id="test_subentry_id",
                subentry_type="conversation",
                title="Sonar",
                unique_id=None,
            ),
        ],
    )


@pytest.fixture
async def mock_perplexity_client() -> AsyncGenerator[AsyncMock]:
    """Initialize integration."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity"
    ) as mock_client_class:
        client = mock_client_class.return_value
        mock_response = AsyncMock()
        mock_response.choices = [
            AsyncMock(
                message=AsyncMock(
                    content="Hello, how can I help you?",
                    role="assistant",
                    tool_calls=None,
                )
            )
        ]
        client.chat.completions.create = AsyncMock(return_value=mock_response)
        yield client


@pytest.fixture
async def mock_perplexity_client_config_flow() -> AsyncGenerator[AsyncMock]:
    """Initialize integration for config flow."""
    with patch(
        "homeassistant.components.perplexity.config_flow.AsyncPerplexity"
    ) as mock_client_class:
        client = mock_client_class.return_value
        mock_response = AsyncMock()
        mock_response.choices = [
            AsyncMock(
                message=AsyncMock(
                    content="pong",
                    role="assistant",
                    tool_calls=None,
                )
            )
        ]
        client.chat.completions.create = AsyncMock(return_value=mock_response)
        yield client


@pytest.fixture(autouse=True)
async def setup_ha(hass: HomeAssistant) -> None:
    """Set up Home Assistant."""
    assert await async_setup_component(hass, "homeassistant", {})
