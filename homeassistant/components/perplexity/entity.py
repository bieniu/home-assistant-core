"""Base entity for Perplexity."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from perplexity import AsyncPerplexity, PerplexityError
from perplexity.types import StreamChunk

from homeassistant.components import conversation
from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import CONF_MODEL
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import Entity

from . import PerplexityConfigEntry
from .const import DOMAIN, LOGGER


def _convert_content_to_chat_message(
    content: conversation.Content,
) -> dict[str, Any] | None:
    """Convert any native chat message for this agent to the native format."""
    if content.role == "system" and content.content:
        return {"role": "system", "content": content.content}

    if content.role == "user" and content.content:
        return {"role": "user", "content": content.content}

    if content.role == "assistant":
        return {
            "role": "assistant",
            "content": content.content,
        }
    LOGGER.warning("Could not convert message to Perplexity API: %s", content)
    return None


async def _transform_response(
    response: StreamChunk,
) -> AsyncGenerator[conversation.AssistantContentDeltaDict]:
    """Transform the Perplexity response to a ChatLog format."""
    message = response.choices[0].message
    yield {
        "role": "assistant",
        "content": message.content if isinstance(message.content, str) else None,
    }


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
            "messages": [
                m
                for content in chat_log.content
                if (m := _convert_content_to_chat_message(content))
            ],
        }

        client: AsyncPerplexity = self.entry.runtime_data

        try:
            result = await client.chat.completions.create(**model_args)
        except PerplexityError as err:
            LOGGER.error("Error talking to Perplexity API: %s", err)
            raise HomeAssistantError("Error talking to Perplexity API") from err

        async for _content in chat_log.async_add_delta_content_stream(
            self.entity_id, _transform_response(result)
        ):
            pass
