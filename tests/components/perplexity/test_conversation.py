"""Tests for the Perplexity conversation integration."""

from unittest.mock import AsyncMock, patch

from freezegun import freeze_time
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components import conversation
from homeassistant.const import Platform
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import entity_registry as er, intent

from . import setup_integration

from tests.common import MockConfigEntry, snapshot_platform
from tests.components.conversation import MockChatLog, mock_chat_log  # noqa: F401


@pytest.fixture(autouse=True)
def freeze_the_time():
    """Freeze the time."""
    with freeze_time("2024-05-24 12:00:00", tz_offset=0):
        yield


@pytest.mark.parametrize("enable_assist", [True, False], ids=["assist", "no_assist"])
async def test_all_entities(
    hass: HomeAssistant,
    snapshot: SnapshotAssertion,
    mock_perplexity_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Test all entities."""
    with patch(
        "homeassistant.components.perplexity.PLATFORMS",
        [Platform.CONVERSATION],
    ):
        await setup_integration(hass, mock_config_entry)

    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_default_prompt(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
    mock_perplexity_client: AsyncMock,
    mock_chat_log: MockChatLog,  # noqa: F811
) -> None:
    """Test that the default prompt works."""
    await setup_integration(hass, mock_config_entry)
    result = await conversation.async_converse(
        hass,
        "hello",
        mock_chat_log.conversation_id,
        Context(),
        agent_id="conversation.sonar",
    )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    assert mock_chat_log.content[1:] == snapshot
    call = mock_perplexity_client.chat.completions.create.call_args_list[0][1]
    assert call["model"] == "sonar"


@pytest.mark.parametrize("enable_assist", [True])
async def test_function_call(
    hass: HomeAssistant,
    mock_chat_log: MockChatLog,  # noqa: F811
    mock_config_entry: MockConfigEntry,
    snapshot: SnapshotAssertion,
    mock_perplexity_client: AsyncMock,
) -> None:
    """Test function call from the assistant."""
    await setup_integration(hass, mock_config_entry)

    mock_chat_log.mock_tool_results(
        {
            "call_call_1": "value1",
            "call_call_2": "value2",
        }
    )

    async def completion_result(*args, messages, **kwargs):
        for message in messages:
            role = message["role"] if isinstance(message, dict) else message.role
            if role == "tool":
                mock_response = AsyncMock()
                mock_response.choices = [
                    AsyncMock(
                        message=AsyncMock(
                            content="I have successfully called the function",
                            role="assistant",
                            tool_calls=None,
                        )
                    )
                ]
                return mock_response

        mock_response = AsyncMock()
        mock_response.choices = [
            AsyncMock(
                message=AsyncMock(
                    content=None,
                    role="assistant",
                    tool_calls=[
                        AsyncMock(
                            id="call_call_1",
                            type="function",
                            function=AsyncMock(
                                name="test_tool",
                                arguments='{"param1":"call1"}',
                            ),
                        )
                    ],
                )
            )
        ]
        return mock_response

    mock_perplexity_client.chat.completions.create = completion_result

    result = await conversation.async_converse(
        hass,
        "Please call the test function",
        mock_chat_log.conversation_id,
        Context(),
        agent_id="conversation.sonar",
    )

    assert result.response.response_type == intent.IntentResponseType.ACTION_DONE
    # Don't test the prompt, as it's not deterministic
    assert mock_chat_log.content[1:] == snapshot
