"""Test the Perplexity config flow."""

from unittest.mock import AsyncMock

from perplexity import AuthenticationError, PerplexityError
import pytest

from homeassistant.components.perplexity.const import CONF_PROMPT, DOMAIN
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_MODEL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import setup_integration

from tests.common import MockConfigEntry


async def test_full_flow(
    hass: HomeAssistant,
    mock_perplexity_client_config_flow: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test the full config flow."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert not result["errors"]
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "test_api_key"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: "test_api_key"}


@pytest.mark.parametrize(
    ("exception", "error"),
    [
        (
            AuthenticationError("Invalid API key", response=None, body=None),
            "invalid_auth",
        ),
        (PerplexityError("Connection error"), "cannot_connect"),
        (Exception, "unknown"),
    ],
)
async def test_form_errors(
    hass: HomeAssistant,
    mock_perplexity_client_config_flow: AsyncMock,
    mock_setup_entry: AsyncMock,
    exception: Exception,
    error: str,
) -> None:
    """Test we handle errors from the Perplexity API."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    mock_perplexity_client_config_flow.chat.completions.create.side_effect = exception

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: "test_api_key"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    mock_perplexity_client_config_flow.chat.completions.create.side_effect = None

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: "test_api_key"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_entry(
    hass: HomeAssistant,
    mock_perplexity_client_config_flow: AsyncMock,
    mock_setup_entry: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test aborting the flow if an entry already exists."""

    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert not result["errors"]
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: "test_api_key"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_create_conversation_agent(
    hass: HomeAssistant,
    mock_perplexity_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test creating a conversation agent."""
    await setup_integration(hass, mock_config_entry)

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, "conversation"),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_MODEL: "sonar-pro",
            CONF_PROMPT: "you are an assistant",
            CONF_LLM_HASS_API: ["assist"],
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_MODEL: "sonar-pro",
        CONF_PROMPT: "you are an assistant",
        CONF_LLM_HASS_API: ["assist"],
    }


async def test_create_conversation_agent_no_control(
    hass: HomeAssistant,
    mock_perplexity_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test creating a conversation agent without control over the LLM API."""
    await setup_integration(hass, mock_config_entry)

    result = await hass.config_entries.subentries.async_init(
        (mock_config_entry.entry_id, "conversation"),
        context={"source": SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            CONF_MODEL: "sonar",
            CONF_PROMPT: "you are an assistant",
            CONF_LLM_HASS_API: [],
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_MODEL: "sonar",
        CONF_PROMPT: "you are an assistant",
    }
