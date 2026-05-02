"""The tractive integration."""

import asyncio
from dataclasses import dataclass, field, replace
import logging
from typing import TYPE_CHECKING, Any

import aiotractive

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ATTR_POWER_SAVING,
    CLIENT_ID,
    DOMAIN,
    RECONNECT_INTERVAL,
    SWITCH_KEY_MAP,
)
from .coordinator import Trackables, TractiveDataUpdateCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.DEVICE_TRACKER,
    Platform.SENSOR,
    Platform.SWITCH,
]


_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TractiveData:
    """Class for Tractive data."""

    client: TractiveClient
    coordinators: list[TractiveDataUpdateCoordinator]
    coordinators_by_tracker: dict[str, TractiveDataUpdateCoordinator] = field(
        default_factory=dict
    )
    coordinators_by_pet: dict[str, TractiveDataUpdateCoordinator] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        """Build coordinator lookup dicts."""
        for coordinator in self.coordinators:
            self.coordinators_by_tracker[coordinator.tracker_id] = coordinator
            self.coordinators_by_pet[coordinator.pet_id] = coordinator


type TractiveConfigEntry = ConfigEntry[TractiveData]


async def async_setup_entry(hass: HomeAssistant, entry: TractiveConfigEntry) -> bool:
    """Set up tractive from a config entry."""
    data = entry.data

    client = aiotractive.Tractive(
        data[CONF_EMAIL],
        data[CONF_PASSWORD],
        session=async_get_clientsession(hass),
        client_id=CLIENT_ID,
    )
    try:
        creds = await client.authenticate()
    except aiotractive.exceptions.UnauthorizedError as error:
        await client.close()
        raise ConfigEntryAuthFailed from error
    except aiotractive.exceptions.TractiveError as error:
        await client.close()
        raise ConfigEntryNotReady from error

    if TYPE_CHECKING:
        assert creds is not None

    tractive = TractiveClient(hass, client, creds["user_id"], entry)

    trackables = []
    try:
        for obj in await client.trackable_objects():
            # To avoid hitting Tractive API rate limits, we add a small
            # delay between requests to fetch trackable details.
            await asyncio.sleep(2)
            trackables.append(await _generate_trackables(client, obj))
    except aiotractive.exceptions.TractiveError as error:
        await client.close()
        raise ConfigEntryNotReady from error
    except ConfigEntryNotReady:
        await client.close()
        raise

    # When the pet defined in Tractive has no tracker linked we get None as `trackable`.
    # So we have to remove None values from trackables list.
    filtered_trackables = [item for item in trackables if item]

    coordinators = [
        TractiveDataUpdateCoordinator(hass, tractive, item, entry)
        for item in filtered_trackables
    ]

    entry.runtime_data = TractiveData(tractive, coordinators)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def cancel_listen_task(_: Event) -> None:
        await tractive.unsubscribe()

    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, cancel_listen_task)
    )
    entry.async_on_unload(tractive.unsubscribe)

    # Remove sensor entities that are no longer supported by the Tractive API
    entity_reg = er.async_get(hass)
    for item in filtered_trackables:
        for key in ("activity_label", "calories", "sleep_label"):
            if entity_id := entity_reg.async_get_entity_id(
                SENSOR_DOMAIN, DOMAIN, f"{item.trackable['_id']}_{key}"
            ):
                entity_reg.async_remove(entity_id)

    return True


async def _generate_trackables(
    client: aiotractive.Tractive,
    trackable: aiotractive.trackable_object.TrackableObject,
) -> Trackables | None:
    """Generate trackables."""
    trackable_data = await trackable.details()

    # Check that the pet has tracker linked.
    if not trackable_data.get("device_id"):
        return None

    if "details" not in trackable_data:
        _LOGGER.warning(
            "Tracker %s has no details and will be skipped. This happens for shared trackers",
            trackable_data["device_id"],
        )
        return None

    tracker = client.tracker(trackable_data["device_id"])
    trackable_pet = client.trackable_object(trackable_data["_id"])

    # Sequential fetching to prevent HTTP 429 Rate Limits
    tracker_details = await tracker.details()
    hw_info = await tracker.hw_info()
    pos_report = await tracker.pos_report()
    health_overview = await trackable_pet.health_overview()

    if not tracker_details.get("_id"):
        raise ConfigEntryNotReady(
            f"Tractive API returns incomplete data for tracker {trackable_data['device_id']}",
        )

    return Trackables(
        tracker, trackable_data, tracker_details, hw_info, pos_report, health_overview
    )


async def async_unload_entry(hass: HomeAssistant, entry: TractiveConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class TractiveClient:
    """A Tractive client."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: aiotractive.Tractive,
        user_id: str,
        config_entry: TractiveConfigEntry,
    ) -> None:
        """Initialize the client."""
        self._hass = hass
        self._client = client
        self._user_id = user_id
        self._last_hw_time = 0
        self._last_pos_time = 0
        self._listen_task: asyncio.Task | None = None
        self._config_entry = config_entry

    @property
    def user_id(self) -> str:
        """Return user id."""
        return self._user_id

    @property
    def subscribed(self) -> bool:
        """Return True if subscribed."""
        if self._listen_task is None:
            return False

        return not self._listen_task.cancelled()

    def subscribe(self) -> None:
        """Start event listener coroutine."""
        self._listen_task = asyncio.create_task(self._listen())

    async def unsubscribe(self) -> None:
        """Stop event listener coroutine."""
        if self._listen_task:
            self._listen_task.cancel()
        await self._client.close()

    async def _listen(self) -> None:
        server_was_unavailable = False
        while True:
            try:
                async for event in self._client.events():
                    _LOGGER.debug("Received event: %s", event)
                    if server_was_unavailable:
                        _LOGGER.debug("Tractive is back online")
                        server_was_unavailable = False
                    if event["message"] == "health_overview":
                        self.send_health_overview_update(event)
                        continue
                    if (
                        "hardware" in event
                        and self._last_hw_time != event["hardware"]["time"]
                    ):
                        self._last_hw_time = event["hardware"]["time"]
                        self._send_hardware_update(event)
                        self._send_switch_update(event)
                    if (
                        "position" in event
                        and self._last_pos_time != event["position"]["time"]
                    ):
                        self._last_pos_time = event["position"]["time"]
                        self._send_position_update(event)
                    # If any key belonging to the switch is present in the event,
                    # we send a switch status update
                    if bool(set(SWITCH_KEY_MAP.values()).intersection(event)):
                        self._send_switch_update(event)
            except aiotractive.exceptions.UnauthorizedError:
                self._config_entry.async_start_reauth(self._hass)
                await self.unsubscribe()
                _LOGGER.error(
                    "Authentication failed for %s, try reconfiguring device",
                    self._config_entry.data[CONF_EMAIL],
                )
                return
            except (KeyError, TypeError) as error:
                _LOGGER.error("Error while listening for events: %s", error)
                continue
            except aiotractive.exceptions.TractiveError:
                _LOGGER.debug(
                    (
                        "Tractive is not available. Internet connection is down?"
                        " Sleeping %i seconds and retrying"
                    ),
                    RECONNECT_INTERVAL.total_seconds(),
                )
                self._last_hw_time = 0
                self._last_pos_time = 0
                server_error = aiotractive.exceptions.TractiveError(
                    "Server unavailable"
                )
                for (
                    coordinator
                ) in self._config_entry.runtime_data.coordinators_by_tracker.values():
                    coordinator.async_set_update_error(server_error)
                await asyncio.sleep(RECONNECT_INTERVAL.total_seconds())
                server_was_unavailable = True
                continue

    def _send_hardware_update(self, event: dict[str, Any]) -> None:
        if coordinator := self._config_entry.runtime_data.coordinators_by_tracker.get(
            event["tracker_id"]
        ):
            coordinator.async_set_updated_data(
                replace(coordinator.data, hardware=event)
            )

    def _send_switch_update(self, event: dict[str, Any]) -> None:
        # Sometimes the event contains data for all switches, sometimes only for one.
        payload: dict[str, Any] = {}
        for switch, key in SWITCH_KEY_MAP.items():
            if switch_data := event.get(key):
                payload[switch] = switch_data["active"]
        if hardware := event.get("hardware", {}):
            payload[ATTR_POWER_SAVING] = (
                hardware.get("power_saving_zone_id") is not None
            )
        if payload:
            if (
                coordinator
                := self._config_entry.runtime_data.coordinators_by_tracker.get(
                    event["tracker_id"]
                )
            ):
                existing = coordinator.data.switches or {}
                coordinator.async_set_updated_data(
                    replace(coordinator.data, switches={**existing, **payload})
                )

    def send_health_overview_update(self, event: dict[str, Any]) -> None:
        """Handle health_overview events from Tractive API."""
        # The health_overview response can be at root level or wrapped in 'content'
        # Handle both structures for compatibility
        data = event.get("content", event)

        if coordinator := self._config_entry.runtime_data.coordinators_by_pet.get(
            data["petId"]
        ):
            coordinator.async_set_updated_data(
                replace(coordinator.data, health_overview=data)
            )

    def _send_position_update(self, event: dict[str, Any]) -> None:
        position = {
            "latitude": event["position"]["latlong"][0],
            "longitude": event["position"]["latlong"][1],
            "accuracy": event["position"]["accuracy"],
            "sensor_used": event["position"]["sensor_used"],
        }
        if coordinator := self._config_entry.runtime_data.coordinators_by_tracker.get(
            event["tracker_id"]
        ):
            coordinator.async_set_updated_data(
                replace(coordinator.data, position=position)
            )
