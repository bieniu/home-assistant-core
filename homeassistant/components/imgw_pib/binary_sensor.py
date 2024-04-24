"""IMGW-PIB binary sensor platform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from imgw_pib.model import HydrologicalData

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN
from .coordinator import ImgwPibDataUpdateCoordinator

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class ImgwPibBinarySensorEntityDescription(BinarySensorEntityDescription):
    """IMGW-PIB sensor entity description."""

    value: Callable[[HydrologicalData], bool | None]
    attrs: Callable[[HydrologicalData], dict[str, Any]]


BINARY_SENSOR_TYPES: tuple[ImgwPibBinarySensorEntityDescription, ...] = (
    ImgwPibBinarySensorEntityDescription(
        key="flood_warning",
        translation_key="flood_warning",
        device_class=BinarySensorDeviceClass.SAFETY,
        value=lambda data: data.flood_warning,
        attrs=lambda data: {"warning_level": data.flood_warning_level.value},
    ),
    ImgwPibBinarySensorEntityDescription(
        key="flood_alarm",
        translation_key="flood_alarm",
        device_class=BinarySensorDeviceClass.SAFETY,
        value=lambda data: data.flood_alarm,
        attrs=lambda data: {"alarm_level": data.flood_alarm_level.value},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add a IMGW-PIB binary sensor entity from a config_entry."""
    coordinator: ImgwPibDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [
            ImgwPibBinarySensorEntity(coordinator, description)
            for description in BINARY_SENSOR_TYPES
            if getattr(coordinator.data, description.key) is not None
        ]
    )


class ImgwPibBinarySensorEntity(
    CoordinatorEntity[ImgwPibDataUpdateCoordinator], BinarySensorEntity
):
    """Define IMGW-PIB binary sensor entity."""

    _attr_has_entity_name = True
    entity_description: ImgwPibBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: ImgwPibDataUpdateCoordinator,
        description: ImgwPibBinarySensorEntityDescription,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)

        self._attr_unique_id = f"{coordinator.station_id}_{description.key}"
        self._attr_device_info = coordinator.device_info
        self._attr_attribution = ATTRIBUTION
        self._attr_is_on = description.value(coordinator.data)
        self._attr_extra_state_attributes = description.attrs(coordinator.data)
        self.entity_description = description

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_is_on = self.entity_description.value(self.coordinator.data)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        binary_sensor_value = self.entity_description.value(self.coordinator.data)
        return super().available and binary_sensor_value is not None
