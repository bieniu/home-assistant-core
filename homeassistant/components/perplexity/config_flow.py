"""Config flow for Perplexity integration."""

from __future__ import annotations

import logging
from typing import Any

from perplexity import AsyncPerplexity, AuthenticationError, PerplexityError
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_API_KEY, CONF_LLM_HASS_API, CONF_MODEL
from homeassistant.core import callback
from homeassistant.helpers import llm
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
)

from .const import (
    CONF_PROMPT,
    DOMAIN,
    PERPLEXITY_MODELS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_CONVERSATION_OPTIONS,
)

_LOGGER = logging.getLogger(__name__)


class PerplexityConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Perplexity."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentries supported by this handler."""
        return {
            "conversation": PerplexityConversationFlowHandler,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._async_abort_entries_match(user_input)
            client = AsyncPerplexity(
                api_key=user_input[CONF_API_KEY],
                http_client=get_async_client(self.hass),
            )
            try:
                await client.chat.completions.create(
                    model="sonar",
                    messages=[{"role": "user", "content": "ping"}],
                )
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except PerplexityError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title="Perplexity",
                    data=user_input,
                )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): str,
                }
            ),
            errors=errors,
        )


class PerplexityConversationFlowHandler(ConfigSubentryFlow):
    """Handle subentry flow for Perplexity conversation."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """User flow to create a conversation subentry."""
        if user_input is not None:
            if not user_input.get(CONF_LLM_HASS_API):
                user_input.pop(CONF_LLM_HASS_API, None)
            return self.async_create_entry(
                title=user_input[CONF_MODEL], data=user_input
            )

        options = [
            SelectOptionDict(value=model, label=model) for model in PERPLEXITY_MODELS
        ]

        hass_apis: list[SelectOptionDict] = [
            SelectOptionDict(
                label=api.name,
                value=api.id,
            )
            for api in llm.async_get_apis(self.hass)
        ]
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MODEL, default=RECOMMENDED_CHAT_MODEL): (
                        SelectSelector(
                            SelectSelectorConfig(
                                options=options,
                                mode=SelectSelectorMode.DROPDOWN,
                            ),
                        )
                    ),
                    vol.Optional(
                        CONF_PROMPT,
                        description={
                            "suggested_value": RECOMMENDED_CONVERSATION_OPTIONS[
                                CONF_PROMPT
                            ]
                        },
                    ): TemplateSelector(),
                    vol.Optional(
                        CONF_LLM_HASS_API,
                        default=RECOMMENDED_CONVERSATION_OPTIONS[CONF_LLM_HASS_API],
                    ): SelectSelector(
                        SelectSelectorConfig(options=hass_apis, multiple=True)
                    ),
                }
            ),
        )
