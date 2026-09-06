"""Support for Westinghouse infrared fans."""

import logging
from typing import Any, override

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.components.infrared import (
    InfraredEmitterConsumerEntity,
    InfraredReceivedSignal,
    InfraredReceiverConsumerEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_INFRARED_EMITTER_ENTITY_ID,
    CONF_INFRARED_RECEIVER_ENTITY_ID,
    DOMAIN,
)
from .infrared_protocols.codes.westinghouse.fan import WestinghouseFanCode
from .infrared_protocols.commands.westinghouse import WestinghouseFanCommand

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Westinghouse infrared fan platform from a config entry."""
    infrared_emitter_entity_id = entry.data[CONF_INFRARED_EMITTER_ENTITY_ID]
    if receiver_id := entry.data.get(CONF_INFRARED_RECEIVER_ENTITY_ID):
        async_add_entities(
            [
                WestinghouseInfraredFanWithReceiver(
                    infrared_emitter_entity_id,
                    receiver_id,
                    entry.entry_id,
                    entry.title,
                )
            ]
        )
    else:
        async_add_entities(
            [
                WestinghouseInfraredFan(
                    infrared_emitter_entity_id, entry.entry_id, entry.title
                )
            ]
        )


class WestinghouseInfraredFan(InfraredEmitterConsumerEntity, FanEntity):
    """Representation of a Westinghouse infrared fan entity."""

    _attr_translation_key = "fan"
    _attr_has_entity_name = True
    _attr_speed_count = 3
    _attr_assumed_state = True
    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
    )

    def __init__(
        self, infrared_emitter_entity_id: str, unique_id: str, name: str
    ) -> None:
        """Initialize the Westinghouse infrared fan entity."""
        self._infrared_emitter_entity_id = infrared_emitter_entity_id

        self._attr_unique_id = unique_id
        self._attr_percentage = 0
        self._attr_is_on = False

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, unique_id)},
            name=name,
        )

    @property
    @override
    def is_on(self) -> bool:
        """Return true if the fan is on."""
        return self._attr_is_on or False

    def _percentage_to_code(self, percentage: int) -> WestinghouseFanCode:
        """Map a percentage to a Westinghouse fan code."""
        if percentage <= 33:
            return WestinghouseFanCode.SPEED_1
        if percentage <= 66:
            return WestinghouseFanCode.SPEED_2
        return WestinghouseFanCode.SPEED_3

    async def _send_westinghouse_code(self, code: WestinghouseFanCode) -> None:
        """Send a Westinghouse fan code through the infrared emitter."""
        command: WestinghouseFanCommand = code.to_command()
        await self._send_command(command)

    @override
    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the fan on."""
        if percentage is not None:
            await self.async_set_percentage(percentage)
            return

        await self._send_westinghouse_code(WestinghouseFanCode.SPEED_1)
        self._attr_is_on = True
        self._attr_percentage = 33
        self.async_write_ha_state()

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        await self._send_westinghouse_code(WestinghouseFanCode.TURN_OFF)
        self._attr_is_on = False
        self._attr_percentage = 0
        self.async_write_ha_state()

    @override
    async def async_set_percentage(self, percentage: int) -> None:
        """Set the fan speed percentage."""
        if percentage == 0:
            await self.async_turn_off()
            return

        code = self._percentage_to_code(percentage)
        await self._send_westinghouse_code(code)
        self._attr_percentage = percentage
        self._attr_is_on = True
        self.async_write_ha_state()


class WestinghouseInfraredFanWithReceiver(
    WestinghouseInfraredFan, InfraredReceiverConsumerEntity
):
    """Westinghouse infrared fan that also tracks a configured infrared receiver."""

    def __init__(
        self,
        infrared_emitter_entity_id: str,
        infrared_receiver_entity_id: str,
        unique_id: str,
        name: str,
    ) -> None:
        """Initialize the Westinghouse infrared fan with receiver."""
        super().__init__(infrared_emitter_entity_id, unique_id, name)
        self._infrared_receiver_entity_id = infrared_receiver_entity_id

    @callback
    @override
    def _handle_signal(self, signal: InfraredReceivedSignal) -> None:
        """Update state from a physical remote signal."""
        code = WestinghouseFanCode.from_raw_timings(signal.timings)
        if code is None:
            _LOGGER.debug(
                "Unrecognised IR timings from %s: %s",
                self._infrared_receiver_entity_id,
                signal.timings[:10],
            )
            return

        if code == WestinghouseFanCode.TURN_OFF:
            self._attr_is_on = False
            self._attr_percentage = 0
        elif code == WestinghouseFanCode.SPEED_1:
            self._attr_is_on = True
            self._attr_percentage = 33
        elif code == WestinghouseFanCode.SPEED_2:
            self._attr_is_on = True
            self._attr_percentage = 66
        elif code == WestinghouseFanCode.SPEED_3:
            self._attr_is_on = True
            self._attr_percentage = 100

        _LOGGER.debug(
            "Received IR code %s from %s, fan state: is_on=%s, percentage=%d",
            code.name,
            self._infrared_receiver_entity_id,
            self._attr_is_on,
            self._attr_percentage,
        )
        self.async_write_ha_state()
