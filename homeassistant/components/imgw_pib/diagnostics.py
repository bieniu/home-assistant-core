"""Diagnostics support for IMGW-PIB."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ImgwPibDataUpdateCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: ImgwPibDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        "config_entry_data": entry.as_dict(),
        "hydrological_data": asdict(coordinator.data),
    }
