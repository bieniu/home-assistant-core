"""A entity class for Tractive integration."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TractiveDataUpdateCoordinator


class TractiveEntity(CoordinatorEntity[TractiveDataUpdateCoordinator]):
    """Tractive entity class."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TractiveDataUpdateCoordinator) -> None:
        """Initialize tracker entity."""
        super().__init__(coordinator)
        self._attr_device_info = DeviceInfo(
            configuration_url="https://my.tractive.com/",
            identifiers={(DOMAIN, coordinator.tracker_details["_id"])},
            name=coordinator.trackable["details"]["name"],
            manufacturer="Tractive GmbH",
            sw_version=coordinator.tracker_details["fw_version"],
            model=coordinator.tracker_details["model_number"],
        )

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if not self.coordinator.client.subscribed:
            self.coordinator.client.subscribe()
