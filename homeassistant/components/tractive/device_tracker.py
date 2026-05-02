"""Support for Tractive device trackers."""

from typing import cast

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TractiveConfigEntry
from .coordinator import TractiveDataUpdateCoordinator
from .entity import TractiveEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TractiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tractive device trackers."""
    coordinators = entry.runtime_data.coordinators

    entities = [TractiveDeviceTracker(coordinator) for coordinator in coordinators]

    async_add_entities(entities)


class TractiveDeviceTracker(TractiveEntity, TrackerEntity):
    """Tractive device tracker."""

    _attr_translation_key = "tracker"

    def __init__(self, coordinator: TractiveDataUpdateCoordinator) -> None:
        """Initialize tracker entity."""
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.pet_id

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return super().available and self.coordinator.data.position is not None

    @property
    def battery_level(self) -> int | None:
        """Return the battery level of the device."""
        if self.coordinator.data.hardware is None:
            return None
        return self.coordinator.data.hardware["hardware"].get("battery_level")

    @property
    def source_type(self) -> SourceType:
        """Return the source type of the device."""
        if (
            self.coordinator.data.position is not None
            and self.coordinator.data.position["sensor_used"] == "PHONE"
        ):
            return SourceType.BLUETOOTH
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        if self.coordinator.data.position is None:
            return None
        return cast(float, self.coordinator.data.position["latitude"])

    @property
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        if self.coordinator.data.position is None:
            return None
        return cast(float, self.coordinator.data.position["longitude"])

    @property
    def location_accuracy(self) -> int:
        """Return the gps accuracy of the device."""
        if self.coordinator.data.position is None:
            return 0
        return cast(int, self.coordinator.data.position["accuracy"])
