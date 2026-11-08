"""Coordinator for the Tractive integration."""

import logging
from typing import override

from aiotractive import Trackable, Tractive, TractiveStatus
from aiotractive.exceptions import TractiveError, UnauthorizedError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

NEW_TRACKABLES_COOLDOWN = 300

type TractiveConfigEntry = ConfigEntry[TractiveCoordinator]


class TractiveCoordinator(DataUpdateCoordinator[TractiveStatus]):
    """Coordinator for Tractive data."""

    config_entry: TractiveConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: TractiveConfigEntry,
        client: Tractive,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Tractive",
            update_interval=None,
        )
        self.client = client
        self.trackables: list[Trackable] = []
        self._checked_tracker_ids: set[str] = set()
        self._new_trackables_debouncer = Debouncer(
            hass,
            _LOGGER,
            cooldown=NEW_TRACKABLES_COOLDOWN,
            immediate=True,
            function=self._async_add_new_trackables,
            background=True,
        )

    @override
    async def _async_setup(self) -> None:
        """Fetch the trackables and subscribe to push updates."""
        try:
            self.trackables = await self.client.async_fetch_trackables()
        except UnauthorizedError as error:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_error",
            ) from error
        except TractiveError as error:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(error)},
            ) from error
        self._async_register_devices(self.trackables)
        self._checked_tracker_ids = {t.tracker_id for t in self.trackables}
        self.client.subscribe_updates(self._async_handle_update)

    @override
    async def _async_update_data(self) -> TractiveStatus:
        """Fetch the current status via REST."""
        try:
            return await self.client.async_fetch_status()
        except UnauthorizedError as error:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="authentication_error",
            ) from error
        except TractiveError as error:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={"error": str(error)},
            ) from error

    @callback
    def _async_handle_update(self, error: Exception | None) -> None:
        """Handle a push update or a channel error from the Tractive API."""
        if error is None:
            if not self.last_update_success:
                _LOGGER.info("Fetching %s data recovered", self.name)
            self.async_set_updated_data(self.client.status)
            self._async_check_new_trackers()
            return
        if isinstance(error, UnauthorizedError):
            self.config_entry.async_start_reauth(self.hass)
        self.async_set_update_error(error)

    @callback
    def _async_register_devices(self, trackables: list[Trackable]) -> None:
        """Register the tracker devices before the entities linking to them."""
        device_registry = dr.async_get(self.hass)
        for trackable in trackables:
            device_registry.async_get_or_create(
                config_entry_id=self.config_entry.entry_id,
                configuration_url="https://my.tractive.com/",
                identifiers={(DOMAIN, trackable.tracker_id)},
                translation_key="tracker",
                translation_placeholders={"id": trackable.tracker_id},
                manufacturer="Tractive GmbH",
                sw_version=trackable.tracker_details["fw_version"],
                model_id=trackable.tracker_details["model_number"],
            )

    @callback
    def _async_check_new_trackers(self) -> None:
        """Fetch the trackables when a push update reports an unknown tracker."""
        if not (
            new_ids := self.client.status.trackers.keys() - self._checked_tracker_ids
        ):
            return
        # Shared trackers are never added, so each tracker is checked only once.
        self._checked_tracker_ids.update(new_ids)
        self._new_trackables_debouncer.async_schedule_call()

    async def _async_add_new_trackables(self) -> None:
        """Fetch the trackables and add the new ones."""
        try:
            trackables = await self.client.async_fetch_trackables()
        except UnauthorizedError:
            self.config_entry.async_start_reauth(self.hass)
            return
        except TractiveError as error:
            _LOGGER.warning("Failed to fetch new Tractive trackables: %s", error)
            # Retry on a later push update, rate limited by the debouncer
            self._checked_tracker_ids = {t.tracker_id for t in self.trackables}
            return
        known_pet_ids = {t.pet_id for t in self.trackables}
        self.trackables = trackables
        if new_trackables := [t for t in trackables if t.pet_id not in known_pet_ids]:
            self._async_register_devices(new_trackables)
            self.async_update_listeners()

    @override
    async def async_shutdown(self) -> None:
        """Cancel the pending fetch of new trackables."""
        await super().async_shutdown()
        self._new_trackables_debouncer.async_shutdown()
