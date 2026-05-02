"""Coordinator for Tractive integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

import aiotractive

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from . import TractiveClient, TractiveConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass
class TractiveTrackerData:
    """Current data for a Tractive tracker."""

    hardware: dict[str, Any] | None = None
    position: dict[str, Any] | None = None
    switches: dict[str, Any] | None = None
    health_overview: dict[str, Any] | None = None


@dataclass
class Trackables:
    """A class that describes trackables."""

    tracker: aiotractive.tracker.Tracker
    trackable: dict[str, Any]
    tracker_details: dict[str, Any]
    hw_info: dict[str, Any]
    pos_report: dict[str, Any]
    health_overview: dict[str, Any]


class TractiveDataUpdateCoordinator(DataUpdateCoordinator[TractiveTrackerData]):
    """Coordinator for a single Tractive tracker."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: TractiveClient,
        item: Trackables,
        entry: TractiveConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Tractive {item.tracker_details['_id']}",
        )
        self.client = client
        self.trackable = item.trackable
        self.tracker_details = item.tracker_details
        self.tracker = item.tracker
        self.pet_id: str = item.trackable["_id"]
        self.tracker_id: str = item.tracker_details["_id"]
        self.data = _build_initial_coordinator_data(item)


def _build_initial_coordinator_data(item: Trackables) -> TractiveTrackerData:
    """Build initial coordinator data from a Trackables instance."""
    pos = item.pos_report
    position: dict[str, Any] | None = None
    if pos:
        position = {
            "latitude": pos["latlong"][0],
            "longitude": pos["latlong"][1],
            "accuracy": pos["pos_uncertainty"],
            "sensor_used": pos["sensor_used"],
        }

    health_overview: dict[str, Any] | None = None
    ho = item.health_overview
    if ho:
        health_overview = ho.get("content", ho)

    return TractiveTrackerData(
        hardware=None,
        position=position,
        switches=None,
        health_overview=health_overview,
    )
