"""Support for Tractive device trackers."""

from typing import override

from homeassistant.components.device_tracker import SourceType, TrackerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import Trackables, TractiveConfigEntry, TractiveCoordinator
from .entity import TractiveEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TractiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tractive device trackers."""
    coordinator = entry.runtime_data.coordinator
    trackables = entry.runtime_data.trackables

    entities = [TractiveDeviceTracker(coordinator, item) for item in trackables]

    async_add_entities(entities)


class TractiveDeviceTracker(TractiveEntity, TrackerEntity):
    """Tractive device tracker."""

    _attr_translation_key = "tracker"
    _attr_name = None

    def __init__(self, coordinator: TractiveCoordinator, item: Trackables) -> None:
        """Initialize tracker entity."""
        super().__init__(
            coordinator,
            item.trackable,
            item.tracker_details,
        )

        self._attr_latitude = item.pos_report["latlong"][0]
        self._attr_longitude = item.pos_report["latlong"][1]
        self._attr_location_accuracy: float = item.pos_report["pos_uncertainty"]
        self._source_type: str = item.pos_report["sensor_used"]
        self._attr_unique_id = item.trackable["_id"]

    @property
    @override
    def source_type(self) -> SourceType:
        """Return the source type of the device."""
        if self._source_type == "PHONE":
            return SourceType.BLUETOOTH
        return SourceType.GPS

    @callback
    @override
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        status = self._tracker_status
        if status.latitude is not None:
            self._attr_latitude = status.latitude
        if status.longitude is not None:
            self._attr_longitude = status.longitude
        if status.accuracy is not None:
            self._attr_location_accuracy = status.accuracy
        if status.sensor_used is not None:
            self._source_type = status.sensor_used
        super()._handle_coordinator_update()
