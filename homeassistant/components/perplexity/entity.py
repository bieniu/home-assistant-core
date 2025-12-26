"""Base entity for Perplexity."""

from __future__ import annotations

from collections.abc import AsyncGenerator
import json
from typing import Any

from perplexity import AsyncPerplexity, PerplexityError
from perplexity.types import StreamChunk
from perplexity.types.chat.completion_create_params import Tool, ToolFunction
from voluptuous_openapi import convert

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MODEL
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, llm
from homeassistant.helpers.entity import Entity

from . import PerplexityConfigEntry
from .const import DOMAIN, LOGGER

# Max number of back and forth with the LLM to generate a response
MAX_TOOL_ITERATIONS = 10


def _format_tool(
    tool: llm.Tool,
    custom_serializer: Any,
) -> Tool:
    """Format tool specification."""
    parameters = convert(tool.parameters, custom_serializer=custom_serializer)
    return Tool(
        type="function",
        function=ToolFunction(
            name=tool.name,
            description=tool.description or "",
            parameters={
                "type": parameters.get("type", "object"),
                "properties": parameters.get("properties", {}),
                "required": parameters.get("required", []),
            },
        ),
    )


def _convert_content_to_chat_message(
    content: conversation.Content,
) -> dict[str, Any] | None:
    """Convert any native chat message for this agent to the native format."""
    if isinstance(content, conversation.ToolResultContent):
        return {
            "role": "tool",
            "tool_call_id": content.tool_call_id,
            "content": json.dumps(content.tool_result),
        }

    if content.role == "system" and content.content:
        return {"role": "system", "content": content.content}

    if content.role == "user" and content.content:
        return {"role": "user", "content": content.content}

    if content.role == "assistant":
        result: dict[str, Any] = {
            "role": "assistant",
            "content": content.content,
        }
        if isinstance(content, conversation.AssistantContent) and content.tool_calls:
            result["tool_calls"] = [
                {
                    "type": "function",
                    "id": tool_call.id,
                    "function": {
                        "name": tool_call.tool_name,
                        "arguments": json.dumps(tool_call.tool_args),
                    },
                }
                for tool_call in content.tool_calls
            ]
        return result
    LOGGER.warning("Could not convert message to Perplexity API: %s", content)
    return None


def _decode_tool_arguments(arguments: str) -> Any:
    """Decode tool call arguments."""
    try:
        return json.loads(arguments)
    except json.JSONDecodeError as err:
        raise HomeAssistantError(f"Unexpected tool argument response: {err}") from err


async def _transform_response(
    response: StreamChunk,
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    """Transform the Perplexity response to a ChatLog format."""
    message = response.choices[0].message
    data: conversation.AssistantContentDeltaDict = {
        "role": "assistant",
        "content": message.content if isinstance(message.content, str) else None,
    }
    if message.tool_calls:
        data["tool_calls"] = [
            llm.ToolInput(
                id=tool_call.id or "",
                tool_name=tool_call.function.name if tool_call.function else "",
                tool_args=(
                    _decode_tool_arguments(tool_call.function.arguments)
                    if tool_call.function and tool_call.function.arguments
                    else {}
                ),
            )
            for tool_call in message.tool_calls
            if tool_call.type == "function"
        ]
    yield data


class PerplexityEntity(Entity):
    """Base entity for Perplexity."""

    _attr_has_entity_name = True

    def __init__(self, entry: PerplexityConfigEntry, subentry: ConfigSubentry) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.subentry = subentry
        self.model = subentry.data[CONF_MODEL]
        self._attr_unique_id = subentry.subentry_id
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)},
            name=subentry.title,
            entry_type=dr.DeviceEntryType.SERVICE,
        )

    async def _async_handle_chat_log(
        self,
        chat_log: conversation.ChatLog,
    ) -> None:
        """Generate an answer for the chat log."""
        model_args: dict[str, Any] = {
            "model": self.model,
        }

        tools: list[Tool] | None = None
        if chat_log.llm_api:
            tools = [
                _format_tool(tool, chat_log.llm_api.custom_serializer)
                for tool in chat_log.llm_api.tools
            ]

        if tools:
            model_args["tools"] = tools

        model_args["messages"] = [
            m
            for content in chat_log.content
            if (m := _convert_content_to_chat_message(content))
        ]

        client: AsyncPerplexity = self.entry.runtime_data

        for _iteration in range(MAX_TOOL_ITERATIONS):
            try:
                result = await client.chat.completions.create(**model_args)
            except PerplexityError as err:
                LOGGER.error("Error talking to Perplexity API: %s", err)
                raise HomeAssistantError("Error talking to Perplexity API") from err

            model_args["messages"].extend(
                [
                    msg
                    async for content in chat_log.async_add_delta_content_stream(
                        self.entity_id, _transform_response(result)
                    )
                    if (msg := _convert_content_to_chat_message(content))
                ]
            )
            if not chat_log.unresponded_tool_results:
                break
