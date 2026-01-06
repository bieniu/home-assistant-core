"""Constants for the Perplexity integration."""

import logging

from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.helpers import llm

DOMAIN = "perplexity"
LOGGER = logging.getLogger(__package__)

CONF_PROMPT = "prompt"
CONF_RECOMMENDED = "recommended"

RECOMMENDED_CHAT_MODEL = "Sonar"

RECOMMENDED_CONVERSATION_OPTIONS = {
    CONF_RECOMMENDED: True,
    CONF_LLM_HASS_API: [llm.LLM_API_ASSIST],
    CONF_PROMPT: llm.DEFAULT_INSTRUCTIONS_PROMPT,
}

PERPLEXITY_MODELS = {
    "Sonar": "sonar",
    "Sonar Pro": "sonar-pro",
    "Sonar Reasoning": "sonar-reasoning",
    "Sonar Reasoning Pro": "sonar-reasoning-pro",
}
