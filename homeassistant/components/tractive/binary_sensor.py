"""Support for Tractive binary sensors."""

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import ATTR_BATTERY_CHARGING, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TractiveConfigEntry, TractiveCoordinator
from .const import ATTR_POWER_SAVING
from .entity import TractiveEntity


class TractiveBinarySensor(TractiveEntity, BinarySensorEntity):
    """Tractive sensor."""

    entity_description: TractiveBinarySensorEntityDescription

    def __init__(
        self,
        coordinator: TractiveCoordinator,
        description: TractiveBinarySensorEntityDescription,
    ) -> None:
        """Initialize sensor entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.pet_id}_{description.key}"
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.coordinator.data.hardware is not None

    @property
    def is_on(self) -> bool | None:
        """Return the state of the binary sensor."""
        if self.coordinator.data.hardware is None:
            return None
        return self.coordinator.data.hardware.get(self.entity_description.key)


@dataclass(frozen=True, kw_only=True)
class TractiveBinarySensorEntityDescription(BinarySensorEntityDescription):
    """Class describing Tractive binary sensor entities."""

    supported: Callable[[dict], bool] = lambda _: True


SENSOR_TYPES = [
    TractiveBinarySensorEntityDescription(
        key=ATTR_BATTERY_CHARGING,
        translation_key="tracker_battery_charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        entity_category=EntityCategory.DIAGNOSTIC,
        supported=lambda details: details.get("charging_state") is not None,
    ),
    TractiveBinarySensorEntityDescription(
        key=ATTR_POWER_SAVING,
        translation_key="tracker_power_saving",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TractiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tractive device trackers."""
    coordinators = entry.runtime_data.coordinators

    entities = [
        TractiveBinarySensor(coordinator, description)
        for description in SENSOR_TYPES
        for coordinator in coordinators
        if description.supported(coordinator.tracker_details)
    ]

    async_add_entities(entities)
