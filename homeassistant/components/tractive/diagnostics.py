"""Diagnostics support for Tractive."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import TractiveConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_EMAIL, "title", "_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: TractiveConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinators = config_entry.runtime_data.coordinators

    return async_redact_data(
        {
            "config_entry": config_entry.as_dict(),
            "trackables": [coordinator.trackable for coordinator in coordinators],
        },
        TO_REDACT,
    )
