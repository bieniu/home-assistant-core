"""Tests for the Perplexity conversation platform."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components import conversation
from homeassistant.components.perplexity.conversation import (
    ParsedAction,
    _parse_json_response,
)
from homeassistant.const import Platform
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er, intent

from tests.common import MockConfigEntry, async_fire_time_changed, snapshot_platform
from tests.components.conversation import mock_chat_log  # noqa: F401


@pytest.fixture(autouse=True)
def freeze_the_time():
    """Freeze the time."""
    with freeze_time("2024-05-24 12:00:00", tz_offset=0):
        yield


async def setup_integration(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Set up the integration for testing.

    Note: config_entry is already added to hass by the fixture.
    """
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


# The conversation entity ID is derived from the device name (subentry title),
# which is "Sonar Conversation" slugified to "sonar_conversation"
CONVERSATION_ENTITY_ID = "conversation.sonar_conversation"


def test_parse_json_valid_with_actions() -> None:
    """Test parsing valid JSON with actions."""
    response = json.dumps(
        {
            "response": "I'll turn on the light for you.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": {"brightness": 255},
                }
            ],
        }
    )

    result = _parse_json_response(response)

    assert result.content == "I'll turn on the light for you."
    assert len(result.actions) == 1
    assert result.actions[0].domain == "light"
    assert result.actions[0].service == "turn_on"
    assert result.actions[0].target == "light.living_room"
    assert result.actions[0].data == {"brightness": 255}


def test_parse_json_valid_without_actions() -> None:
    """Test parsing valid JSON without actions."""
    response = json.dumps({"response": "Hello! How can I help you?", "actions": None})

    result = _parse_json_response(response)

    assert result.content == "Hello! How can I help you?"
    assert len(result.actions) == 0


def test_parse_json_empty_actions() -> None:
    """Test parsing valid JSON with empty actions array."""
    response = json.dumps({"response": "The weather is nice today.", "actions": []})

    result = _parse_json_response(response)

    assert result.content == "The weather is nice today."
    assert len(result.actions) == 0


def test_parse_json_invalid_returns_raw_text() -> None:
    """Test that invalid JSON returns raw text."""
    response = "This is not JSON"

    result = _parse_json_response(response)

    assert result.content == "This is not JSON"
    assert len(result.actions) == 0


def test_parse_json_in_code_block() -> None:
    """Test parsing JSON wrapped in markdown code block."""
    response = """```json
{
    "response": "Turning on the light.",
    "actions": [
        {
            "domain": "light",
            "service": "turn_on",
            "target": "light.bedroom",
            "data": null
        }
    ]
}
```"""

    result = _parse_json_response(response)

    assert result.content == "Turning on the light."
    assert len(result.actions) == 1
    assert result.actions[0].target == "light.bedroom"


def test_parse_json_multiple_actions() -> None:
    """Test parsing response with multiple actions."""
    response = json.dumps(
        {
            "response": "I'll turn on the lights and set the thermostat.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": None,
                },
                {
                    "domain": "climate",
                    "service": "set_temperature",
                    "target": "climate.thermostat",
                    "data": {"temperature": 22},
                },
            ],
        }
    )

    result = _parse_json_response(response)

    assert result.content == "I'll turn on the lights and set the thermostat."
    assert len(result.actions) == 2
    assert result.actions[0].domain == "light"
    assert result.actions[1].domain == "climate"
    assert result.actions[1].data == {"temperature": 22}


def test_parse_json_action_with_missing_fields_skipped() -> None:
    """Test that actions with missing required fields are skipped."""
    response = json.dumps(
        {
            "response": "Processing...",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    # Missing target
                },
                {
                    "domain": "switch",
                    "service": "turn_off",
                    "target": "switch.fan",
                    "data": None,
                },
            ],
        }
    )

    result = _parse_json_response(response)

    assert len(result.actions) == 1
    assert result.actions[0].domain == "switch"


def test_parsed_action_str_representation() -> None:
    """Test string representation of ParsedAction."""
    action = ParsedAction(
        domain="light",
        service="turn_on",
        target="light.living_room",
        data={"brightness": 255},
    )

    assert "light.turn_on" in str(action)
    assert "light.living_room" in str(action)
    assert "brightness" in str(action)


def test_parsed_action_str_representation_empty_data() -> None:
    """Test string representation with empty data."""
    action = ParsedAction(
        domain="switch", service="turn_off", target="switch.fan", data={}
    )

    result = str(action)
    assert "switch.turn_off" in result
    assert "switch.fan" in result


@pytest.mark.parametrize("enable_assist", [True, False], ids=["assist", "no_assist"])
async def test_conversation_entity_setup(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test conversation entity is properly set up."""
    with (
        patch(
            "homeassistant.components.perplexity.PLATFORMS",
            [Platform.CONVERSATION],
        ),
        patch(
            "homeassistant.components.perplexity.AsyncPerplexity",
            return_value=mock_perplexity_client,
        ),
    ):
        await setup_integration(hass, mock_config_entry)

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_conversation_without_actions(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    mock_stream: MagicMock,
    mock_chat_log,  # noqa: F811
) -> None:
    """Test basic conversation without actions."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await setup_integration(hass, mock_config_entry)

    # Mock the streaming response
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream("Hello! How can I help you today?")
    )

    result = await conversation.async_converse(
        hass,
        "Hello",
        mock_chat_log.conversation_id,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE


@pytest.mark.parametrize("enable_assist", [True])
async def test_conversation_with_actions(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    mock_stream: MagicMock,
    mock_chat_log,  # noqa: F811
    service_calls: list,
) -> None:
    """Test conversation with action execution."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await setup_integration(hass, mock_config_entry)

    # Create a test light entity
    hass.states.async_set("light.living_room", "off")

    # Mock the streaming response with JSON containing an action
    json_response = json.dumps(
        {
            "response": "I've turned on the living room light for you.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": None,
                }
            ],
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    result = await conversation.async_converse(
        hass,
        "Turn on the living room light",
        mock_chat_log.conversation_id,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    # Verify the service was called
    assert len(service_calls) == 1
    assert service_calls[0].domain == "light"
    assert service_calls[0].service == "turn_on"
    assert service_calls[0].data.get("entity_id") == "light.living_room"

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    # Verify the response text was extracted from JSON
    assert "turned on" in result.response.speech["plain"]["speech"].lower()


@pytest.mark.parametrize("enable_assist", [True])
async def test_conversation_with_multiple_actions(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    mock_stream: MagicMock,
    mock_chat_log,  # noqa: F811
    service_calls: list,
) -> None:
    """Test conversation with multiple action execution."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await setup_integration(hass, mock_config_entry)

    # Create test entities
    hass.states.async_set("light.living_room", "off")
    hass.states.async_set("switch.fan", "off")

    # Mock the streaming response with JSON containing multiple actions
    json_response = json.dumps(
        {
            "response": "I've turned on the light and the fan.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": None,
                },
                {
                    "domain": "switch",
                    "service": "turn_on",
                    "target": "switch.fan",
                    "data": None,
                },
            ],
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    result = await conversation.async_converse(
        hass,
        "Turn on the light and fan",
        mock_chat_log.conversation_id,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    # Verify both services were called
    assert len(service_calls) == 2

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE


@pytest.mark.parametrize("enable_assist", [True])
async def test_conversation_action_with_data(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    mock_stream: MagicMock,
    mock_chat_log,  # noqa: F811
    service_calls: list,
) -> None:
    """Test conversation with action that includes data parameters."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await setup_integration(hass, mock_config_entry)

    # Create a test light entity
    hass.states.async_set("light.bedroom", "off")

    # Mock the streaming response with JSON containing action with data
    json_response = json.dumps(
        {
            "response": "I've set the bedroom light to 50% brightness.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.bedroom",
                    "data": {"brightness": 127},
                }
            ],
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    await conversation.async_converse(
        hass,
        "Set bedroom light to 50%",
        mock_chat_log.conversation_id,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    # Verify the service was called with correct data
    assert len(service_calls) == 1
    assert service_calls[0].domain == "light"
    assert service_calls[0].service == "turn_on"
    assert service_calls[0].data.get("entity_id") == "light.bedroom"
    assert service_calls[0].data.get("brightness") == 127


@pytest.mark.parametrize("enable_assist", [True])
async def test_conversation_action_service_error(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    mock_stream: MagicMock,
    mock_chat_log,  # noqa: F811
    service_calls: list,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test conversation handles service call errors gracefully."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await setup_integration(hass, mock_config_entry)

    # Mock the streaming response with JSON containing an action
    json_response = json.dumps(
        {
            "response": "I'll turn on the light.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.nonexistent",
                    "data": None,
                }
            ],
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    # Should not raise, just log warning (service_calls fixture will ignore unknown services)
    result = await conversation.async_converse(
        hass,
        "Turn on the light",
        mock_chat_log.conversation_id,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    # The service_calls fixture catches ServiceNotFound and logs it
    assert len(service_calls) == 1  # Call was attempted


async def test_conversation_supported_languages(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that conversation entity supports all languages."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await setup_integration(hass, mock_config_entry)

    state = hass.states.get(CONVERSATION_ENTITY_ID)
    assert state is not None

    # Get the agent via the agent manager using entity_id
    agent = conversation.agent_manager.async_get_agent(hass, CONVERSATION_ENTITY_ID)
    assert agent is not None
    assert agent.supported_languages == "*"


@pytest.mark.parametrize("enable_assist", [True])
async def test_conversation_control_feature(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that conversation entity has control feature when assist is enabled."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await setup_integration(hass, mock_config_entry)

    state = hass.states.get(CONVERSATION_ENTITY_ID)
    assert state is not None

    # Check the state attributes for supported_features
    assert (
        state.attributes.get("supported_features")
        == conversation.ConversationEntityFeature.CONTROL
    )


@pytest.mark.parametrize("enable_assist", [False])
async def test_conversation_no_control_feature_without_assist(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test that conversation entity has no control feature when assist is disabled."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await setup_integration(hass, mock_config_entry)

    state = hass.states.get(CONVERSATION_ENTITY_ID)
    assert state is not None

    # Check that supported_features is 0
    assert state.attributes.get("supported_features") == 0


def test_parsed_action_str_with_delay() -> None:
    """Test string representation of ParsedAction with delay."""
    action = ParsedAction(
        domain="light",
        service="turn_off",
        target="light.living_room",
        data={},
        delay_seconds=300.0,
    )

    result = str(action)
    assert "light.turn_off" in result
    assert "light.living_room" in result
    assert "delay=300.0s" in result


def test_parsed_action_str_without_delay() -> None:
    """Test string representation of ParsedAction without delay."""
    action = ParsedAction(
        domain="light",
        service="turn_on",
        target="light.living_room",
    )

    result = str(action)
    assert "delay=" not in result


def test_parse_json_with_delay() -> None:
    """Test parsing JSON response with delay_seconds."""
    response = json.dumps(
        {
            "response": "I'll turn on the light for 5 minutes.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": None,
                    "delay_seconds": None,
                },
                {
                    "domain": "light",
                    "service": "turn_off",
                    "target": "light.living_room",
                    "data": None,
                    "delay_seconds": 300,
                },
            ],
        }
    )

    result = _parse_json_response(response)

    assert len(result.actions) == 2
    assert result.actions[0].delay_seconds is None
    assert result.actions[0].service == "turn_on"
    assert result.actions[1].delay_seconds == 300.0
    assert result.actions[1].service == "turn_off"


def test_parse_json_with_zero_delay() -> None:
    """Test that zero delay is treated as no delay."""
    response = json.dumps(
        {
            "response": "Turning on the light.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": None,
                    "delay_seconds": 0,
                },
            ],
        }
    )

    result = _parse_json_response(response)

    assert len(result.actions) == 1
    assert result.actions[0].delay_seconds is None


def test_parse_json_with_negative_delay_ignored() -> None:
    """Test that negative delay is treated as no delay."""
    response = json.dumps(
        {
            "response": "Turning on.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": None,
                    "delay_seconds": -5,
                },
            ],
        }
    )

    result = _parse_json_response(response)

    assert len(result.actions) == 1
    assert result.actions[0].delay_seconds is None


def test_parse_json_with_invalid_delay_type() -> None:
    """Test that non-numeric delay is treated as no delay."""
    response = json.dumps(
        {
            "response": "Turning on.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": None,
                    "delay_seconds": "five minutes",
                },
            ],
        }
    )

    result = _parse_json_response(response)

    assert len(result.actions) == 1
    assert result.actions[0].delay_seconds is None


@pytest.mark.parametrize("enable_assist", [True])
async def test_conversation_with_delayed_action(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    mock_stream: MagicMock,
    mock_chat_log,  # noqa: F811
    service_calls: list,
) -> None:
    """Test conversation with immediate and delayed action execution."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await setup_integration(hass, mock_config_entry)

    hass.states.async_set("light.living_room", "off")

    # LLM response: turn on immediately, turn off after 300 seconds
    json_response = json.dumps(
        {
            "response": "I'll turn on the living room light for 5 minutes.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_on",
                    "target": "light.living_room",
                    "data": None,
                    "delay_seconds": None,
                },
                {
                    "domain": "light",
                    "service": "turn_off",
                    "target": "light.living_room",
                    "data": None,
                    "delay_seconds": 300,
                },
            ],
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    result = await conversation.async_converse(
        hass,
        "Turn on the living room light for 5 minutes",
        mock_chat_log.conversation_id,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE

    # Only the immediate action should have been called
    assert len(service_calls) == 1
    assert service_calls[0].domain == "light"
    assert service_calls[0].service == "turn_on"

    # Fire the timer to trigger the delayed action
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()

    # Now the delayed turn_off should have executed
    assert len(service_calls) == 2
    assert service_calls[1].domain == "light"
    assert service_calls[1].service == "turn_off"
    assert service_calls[1].data.get("entity_id") == "light.living_room"


@pytest.mark.parametrize("enable_assist", [True])
async def test_conversation_delayed_action_only(
    hass: HomeAssistant,
    mock_perplexity_client: MagicMock,
    mock_config_entry: MockConfigEntry,
    mock_stream: MagicMock,
    mock_chat_log,  # noqa: F811
    service_calls: list,
) -> None:
    """Test conversation with only a delayed action (no immediate)."""
    with patch(
        "homeassistant.components.perplexity.AsyncPerplexity",
        return_value=mock_perplexity_client,
    ):
        await setup_integration(hass, mock_config_entry)

    hass.states.async_set("light.bedroom", "on")

    json_response = json.dumps(
        {
            "response": "I'll turn off the bedroom light in 10 minutes.",
            "actions": [
                {
                    "domain": "light",
                    "service": "turn_off",
                    "target": "light.bedroom",
                    "data": None,
                    "delay_seconds": 600,
                },
            ],
        }
    )
    mock_perplexity_client.chat.completions.create = AsyncMock(
        return_value=mock_stream(json_response)
    )

    result = await conversation.async_converse(
        hass,
        "Turn off the bedroom light in 10 minutes",
        mock_chat_log.conversation_id,
        Context(),
        agent_id=CONVERSATION_ENTITY_ID,
    )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE

    # No immediate actions
    assert len(service_calls) == 0

    # Fire the timer
    async_fire_time_changed(hass, fire_all=True)
    await hass.async_block_till_done()

    # Delayed action executed
    assert len(service_calls) == 1
    assert service_calls[0].domain == "light"
    assert service_calls[0].service == "turn_off"
    assert service_calls[0].data.get("entity_id") == "light.bedroom"
