"""Support for Tractive switches."""

from dataclasses import dataclass, replace

import logging
from typing import Any, Literal

from aiotractive.exceptions import TractiveError

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import TractiveConfigEntry
from .const import ATTR_BUZZER, ATTR_LED, ATTR_LIVE_TRACKING, ATTR_POWER_SAVING
from .coordinator import TractiveDataUpdateCoordinator
from .entity import TractiveEntity

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class TractiveSwitchEntityDescription(SwitchEntityDescription):
    """Class describing Tractive switch entities."""

    method: Literal["async_set_buzzer", "async_set_led", "async_set_live_tracking"]


SWITCH_TYPES: tuple[TractiveSwitchEntityDescription, ...] = (
    TractiveSwitchEntityDescription(
        key=ATTR_BUZZER,
        translation_key="tracker_buzzer",
        method="async_set_buzzer",
        entity_category=EntityCategory.CONFIG,
    ),
    TractiveSwitchEntityDescription(
        key=ATTR_LED,
        translation_key="tracker_led",
        method="async_set_led",
        entity_category=EntityCategory.CONFIG,
    ),
    TractiveSwitchEntityDescription(
        key=ATTR_LIVE_TRACKING,
        translation_key="live_tracking",
        method="async_set_live_tracking",
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TractiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tractive switches."""
    coordinators = entry.runtime_data.coordinators

    entities = [
        TractiveSwitch(coordinator, description)
        for description in SWITCH_TYPES
        for coordinator in coordinators
    ]

    async_add_entities(entities)


class TractiveSwitch(TractiveEntity, SwitchEntity):
    """Tractive switch."""

    entity_description: TractiveSwitchEntityDescription

    def __init__(
        self,
        coordinator: TractiveDataUpdateCoordinator,
        description: TractiveSwitchEntityDescription,
    ) -> None:
        """Initialize switch entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.pet_id}_{description.key}"
        self.entity_description = description
        self._method = getattr(self, description.method)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available or self.coordinator.data.switches is None:
            return False
        return not self.coordinator.data.switches.get(ATTR_POWER_SAVING, False)

    @property
    def is_on(self) -> bool | None:
        """Return True if switch is on."""
        if self.coordinator.data.switches is None:
            return None
        return self.coordinator.data.switches.get(self.entity_description.key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on a switch."""
        try:
            result = await self._method(True)
        except TractiveError as error:
            _LOGGER.error(error)
            return
        # Write state back to avoid switch flips with a slow response
        if result["pending"]:
            switches = {
                **(self.coordinator.data.switches or {}),
                self.entity_description.key: True,
            }
            self.coordinator.async_set_updated_data(
                replace(self.coordinator.data, switches=switches)
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off a switch."""
        try:
            result = await self._method(False)
        except TractiveError as error:
            _LOGGER.error(error)
            return
        # Write state back to avoid switch flips with a slow response
        if result["pending"]:
            switches = {
                **(self.coordinator.data.switches or {}),
                self.entity_description.key: False,
            }
            self.coordinator.async_set_updated_data(
                replace(self.coordinator.data, switches=switches)
            )

    async def async_set_buzzer(self, active: bool) -> dict[str, Any]:
        """Set the buzzer on/off."""
        return await self.coordinator.tracker.set_buzzer_active(active)

    async def async_set_led(self, active: bool) -> dict[str, Any]:
        """Set the LED on/off."""
        return await self.coordinator.tracker.set_led_active(active)

    async def async_set_live_tracking(self, active: bool) -> dict[str, Any]:
        """Set the live tracking on/off."""
        return await self.coordinator.tracker.set_live_tracking_active(active)
