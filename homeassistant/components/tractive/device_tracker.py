"""Support for Tractive device trackers."""

from typing import override

from aiotractive import Trackable

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import TractiveConfigEntry, TractiveCoordinator
from .entity import TractiveEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TractiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tractive device trackers."""
    coordinator = entry.runtime_data

    known_pet_ids: set[str] = set()

    @callback
    def _async_add_new_trackables() -> None:
        new_trackables = [
            trackable
            for trackable in coordinator.trackables
            if trackable.pet_id not in known_pet_ids
        ]
        if not new_trackables:
            return
        known_pet_ids.update(trackable.pet_id for trackable in new_trackables)
        async_add_entities(
            TractiveDeviceTracker(coordinator, trackable)
            for trackable in new_trackables
        )

    _async_add_new_trackables()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_trackables))


class TractiveDeviceTracker(TractiveEntity, TrackerEntity):
    """Tractive device tracker."""

    _attr_translation_key = "tracker"
    _attr_name = None

    def __init__(self, coordinator: TractiveCoordinator, trackable: Trackable) -> None:
        """Initialize tracker entity."""
        super().__init__(coordinator, trackable)

        self._attr_unique_id = trackable.pet_id

    @property
    @override
    def latitude(self) -> float | None:
        """Return latitude value of the device."""
        return self._tracker_status.latitude

    @property
    @override
    def longitude(self) -> float | None:
        """Return longitude value of the device."""
        return self._tracker_status.longitude

    @property
    @override
    def location_accuracy(self) -> float:
        """Return the location accuracy of the device."""
        return self._tracker_status.accuracy or 0

    @property
    @override
    def source_type(self) -> SourceType:
        """Return the source type of the device."""
        if self._tracker_status.sensor_used == "PHONE":
            return SourceType.BLUETOOTH

        return SourceType.GPS
