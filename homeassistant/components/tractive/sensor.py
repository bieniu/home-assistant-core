"""Support for Tractive sensors."""

from dataclasses import dataclass
from typing import override

from aiotractive import Trackable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    ATTR_BATTERY_LEVEL,
    PERCENTAGE,
    EntityCategory,
    UnitOfMass,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    ATTR_DAILY_GOAL,
    ATTR_MINUTES_ACTIVE,
    ATTR_MINUTES_DAY_SLEEP,
    ATTR_MINUTES_NIGHT_SLEEP,
    ATTR_MINUTES_REST,
    ATTR_TRACKER_STATE,
)
from .coordinator import TractiveConfigEntry, TractiveCoordinator
from .entity import TractiveEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class TractiveSensorEntityDescription(SensorEntityDescription):
    """Class describing Tractive sensor entities."""

    hardware_sensor: bool = False
    health_sensor: bool = False


class TractiveSensor(TractiveEntity, SensorEntity):
    """Tractive sensor."""

    entity_description: TractiveSensorEntityDescription

    def __init__(
        self,
        coordinator: TractiveCoordinator,
        trackable: Trackable,
        description: TractiveSensorEntityDescription,
    ) -> None:
        """Initialize sensor entity."""
        super().__init__(coordinator, trackable, description.hardware_sensor)

        self._attr_unique_id = f"{trackable.pet_id}_{description.key}"
        self.entity_description = description

    @property
    @override
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        status = (
            self._tracker_status
            if self.entity_description.hardware_sensor
            else self._pet_status
        )
        value: StateType = getattr(status, self.entity_description.key)
        return value


SENSOR_TYPES: tuple[TractiveSensorEntityDescription, ...] = (
    TractiveSensorEntityDescription(
        key=ATTR_BATTERY_LEVEL,
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        hardware_sensor=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    TractiveSensorEntityDescription(
        key=ATTR_TRACKER_STATE,
        translation_key="tracker_state",
        hardware_sensor=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.ENUM,
        options=[
            "inaccurate_position",
            "not_reporting",
            "operational",
            "system_shutdown_user",
            "system_startup",
        ],
    ),
    TractiveSensorEntityDescription(
        key=ATTR_MINUTES_ACTIVE,
        translation_key="activity_time",
        health_sensor=True,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
    ),
    TractiveSensorEntityDescription(
        key=ATTR_MINUTES_REST,
        translation_key="rest_time",
        health_sensor=True,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
    ),
    TractiveSensorEntityDescription(
        key=ATTR_DAILY_GOAL,
        translation_key="daily_goal",
        health_sensor=True,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
    ),
    TractiveSensorEntityDescription(
        key=ATTR_MINUTES_DAY_SLEEP,
        translation_key="minutes_day_sleep",
        health_sensor=True,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
    ),
    TractiveSensorEntityDescription(
        key=ATTR_MINUTES_NIGHT_SLEEP,
        translation_key="minutes_night_sleep",
        health_sensor=True,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
    ),
    TractiveSensorEntityDescription(
        key="weight",
        native_unit_of_measurement=UnitOfMass.GRAMS,
        suggested_unit_of_measurement=UnitOfMass.KILOGRAMS,
        suggested_display_precision=1,
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
)


def _is_supported(
    coordinator: TractiveCoordinator,
    trackable: Trackable,
    description: TractiveSensorEntityDescription,
) -> bool:
    """Return if the sensor is supported, health sensors once health data arrives."""
    if not description.health_sensor or trackable.health_available:
        return True
    pet_status = coordinator.data.pets.get(trackable.pet_id)
    return getattr(pet_status, description.key, None) is not None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TractiveConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Tractive sensors."""
    coordinator = entry.runtime_data

    known_sensors: set[tuple[str, str]] = set()

    @callback
    def _async_add_new_sensors() -> None:
        new_sensors = [
            (trackable, description)
            for trackable in coordinator.trackables
            for description in SENSOR_TYPES
            if (trackable.pet_id, description.key) not in known_sensors
            and _is_supported(coordinator, trackable, description)
        ]
        if not new_sensors:
            return
        known_sensors.update(
            (trackable.pet_id, description.key)
            for trackable, description in new_sensors
        )
        async_add_entities(
            TractiveSensor(coordinator, trackable, description)
            for trackable, description in new_sensors
        )

    _async_add_new_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_new_sensors))
