"""Test init of Tractive integration."""

from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock

from aiotractive import PetStatus, Trackable, TrackerStatus
from aiotractive.exceptions import TractiveError, UnauthorizedError
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.components.tractive.const import DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from . import init_integration

BATTERY_ENTITY_ID = "sensor.tracker_device_id_123_battery"
ACTIVITY_ENTITY_ID = "sensor.test_pet_activity_time"
NEW_PET_ID = "pet_id_456"
NEW_TRACKER_ID = "device_id_456"
NEW_TRACKER_ENTITY_ID = "device_tracker.tracker_device_id_456"
NEW_BATTERY_ENTITY_ID = "sensor.tracker_device_id_456_battery"
NEW_ACTIVITY_ENTITY_ID = "sensor.other_pet_activity_time"
NEW_REST_ENTITY_ID = "sensor.other_pet_rest_time"


def _add_new_trackable(client: AsyncMock) -> None:
    """Make the client return a new trackable and report its tracker status."""
    existing = client.async_fetch_trackables.return_value[0]
    pet_details = deepcopy(existing.pet_details)
    pet_details["_id"] = NEW_PET_ID
    pet_details["details"]["name"] = "Other Pet"
    tracker_details = {**existing.tracker_details, "_id": NEW_TRACKER_ID}
    trackable = Trackable(
        pet_id=NEW_PET_ID,
        tracker_id=NEW_TRACKER_ID,
        pet_details=pet_details,
        tracker_details=tracker_details,
    )
    client.async_fetch_trackables.return_value = [existing, trackable]
    client.status.trackers[NEW_TRACKER_ID] = TrackerStatus(battery_level=50)


async def test_setup_entry(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a successful setup entry."""
    await init_integration(hass, mock_config_entry)

    assert mock_config_entry.state is ConfigEntryState.LOADED
    mock_tractive_client.listen.assert_called_once()


async def test_unload_entry(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test successful unload of entry."""
    listener = hass.loop.create_future()

    async def listen() -> None:
        await listener

    mock_tractive_client.listen.side_effect = listen
    await init_integration(hass, mock_config_entry)

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED
    assert listener.cancelled()


@pytest.mark.parametrize(
    ("method", "exc", "entry_state"),
    [
        ("async_fetch_trackables", UnauthorizedError, ConfigEntryState.SETUP_ERROR),
        ("async_fetch_trackables", TractiveError, ConfigEntryState.SETUP_RETRY),
        ("async_fetch_status", UnauthorizedError, ConfigEntryState.SETUP_ERROR),
        ("async_fetch_status", TractiveError, ConfigEntryState.SETUP_RETRY),
    ],
)
async def test_setup_failed(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    method: str,
    exc: Exception,
    entry_state: ConfigEntryState,
) -> None:
    """Test for setup failure."""
    getattr(mock_tractive_client, method).side_effect = exc

    await init_integration(hass, mock_config_entry)

    assert mock_config_entry.state is entry_state


async def test_server_unavailable(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test entities become unavailable on a channel error and recover."""
    await init_integration(hass, mock_config_entry)

    # Initial value comes from the REST status
    assert hass.states.get(BATTERY_ENTITY_ID).state == "96"

    mock_tractive_client.send_error_event(TractiveError("Connection lost"))
    await hass.async_block_till_done()

    assert hass.states.get(BATTERY_ENTITY_ID).state == STATE_UNAVAILABLE
    assert "Error requesting Tractive data: Connection lost" in caplog.text

    mock_tractive_client.send_error_event(TractiveError("Still down"))
    await hass.async_block_till_done()

    assert hass.states.get(BATTERY_ENTITY_ID).state == STATE_UNAVAILABLE
    assert "Still down" not in caplog.text

    # The library notifies without an error once the channel reconnects
    mock_tractive_client.send_error_event(None)
    await hass.async_block_till_done()

    assert hass.states.get(BATTERY_ENTITY_ID).state == "96"
    assert "Fetching Tractive data recovered" in caplog.text

    mock_tractive_client.set_tracker_status(
        battery_level=88,
        tracker_state="operational",
        power_saving=True,
        battery_charging=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get(BATTERY_ENTITY_ID).state == "88"
    assert caplog.text.count("Fetching Tractive data recovered") == 1


async def test_pet_without_health_data(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test pet sensors are unknown until health data arrives."""
    mock_tractive_client.status.pets.clear()

    await init_integration(hass, mock_config_entry)

    assert hass.states.get(ACTIVITY_ENTITY_ID).state == STATE_UNKNOWN

    mock_tractive_client.set_pet_status(
        daily_goal=200,
        minutes_active=150,
        minutes_day_sleep=100,
        minutes_night_sleep=300,
        minutes_rest=122,
    )
    await hass.async_block_till_done()

    assert hass.states.get(ACTIVITY_ENTITY_ID).state == "150"


async def test_reauth_on_unauthorized(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a reauth flow is started when the channel reports an auth error."""
    await init_integration(hass, mock_config_entry)

    mock_tractive_client.send_error_event(UnauthorizedError())
    await hass.async_block_till_done()

    assert hass.states.get(BATTERY_ENTITY_ID).state == STATE_UNAVAILABLE
    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
    assert flows[0]["context"]["entry_id"] == mock_config_entry.entry_id


@pytest.mark.parametrize("sensor", ["activity_label", "calories", "sleep_label"])
async def test_remove_unsupported_sensor_entity(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    sensor: str,
) -> None:
    """Test removing unsupported sensor entity."""
    entity_id = f"sensor.test_pet_{sensor}"
    mock_config_entry.add_to_hass(hass)

    entity_registry.async_get_or_create(
        SENSOR_DOMAIN,
        DOMAIN,
        f"pet_id_123_{sensor}",
        suggested_object_id=entity_id.rsplit(".", maxsplit=1)[-1],
        config_entry=mock_config_entry,
    )

    await init_integration(hass, mock_config_entry)

    assert entity_registry.async_get(entity_id) is None


async def test_new_trackable_added(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Test entities are added when a push update reports a new tracker."""
    await init_integration(hass, mock_config_entry)

    assert hass.states.get(NEW_TRACKER_ENTITY_ID) is None

    _add_new_trackable(mock_tractive_client)
    mock_tractive_client.send_error_event(None)
    await hass.async_block_till_done()

    assert mock_tractive_client.async_fetch_trackables.call_count == 2
    tracker_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, NEW_TRACKER_ID), mock_config_entry.entry_id
    )
    assert tracker_device
    pet_device = device_registry.async_get_device_by_identifier(
        (DOMAIN, NEW_PET_ID), mock_config_entry.entry_id
    )
    assert pet_device
    assert pet_device.via_device_id == tracker_device.id
    assert hass.states.get(NEW_TRACKER_ENTITY_ID)
    assert hass.states.get(NEW_BATTERY_ENTITY_ID).state == "50"


async def test_new_trackable_health_sensors(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test health sensors of a new pet are added once it reports health data."""
    await init_integration(hass, mock_config_entry)

    _add_new_trackable(mock_tractive_client)
    mock_tractive_client.send_error_event(None)
    await hass.async_block_till_done()

    assert hass.states.get(NEW_BATTERY_ENTITY_ID)
    assert hass.states.get(NEW_ACTIVITY_ENTITY_ID) is None

    mock_tractive_client.status.pets[NEW_PET_ID] = PetStatus(minutes_active=10)
    mock_tractive_client.send_error_event(None)
    await hass.async_block_till_done()

    assert hass.states.get(NEW_ACTIVITY_ENTITY_ID).state == "10"
    assert hass.states.get(NEW_REST_ENTITY_ID) is None


async def test_unknown_tracker_checked_once(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a tracker that is not a trackable, e.g. a shared one, is fetched once."""
    await init_integration(hass, mock_config_entry)

    mock_tractive_client.status.trackers[NEW_TRACKER_ID] = TrackerStatus()
    mock_tractive_client.send_error_event(None)
    await hass.async_block_till_done()
    mock_tractive_client.send_error_event(None)
    await hass.async_block_till_done()

    assert mock_tractive_client.async_fetch_trackables.call_count == 2
    assert hass.states.get(NEW_TRACKER_ENTITY_ID) is None


async def test_new_trackable_fetch_error(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test fetching a new trackable is retried after the cooldown."""
    await init_integration(hass, mock_config_entry)

    _add_new_trackable(mock_tractive_client)
    trackables = mock_tractive_client.async_fetch_trackables.return_value
    mock_tractive_client.async_fetch_trackables.side_effect = TractiveError("Boom")
    mock_tractive_client.send_error_event(None)
    await hass.async_block_till_done()

    assert "Failed to fetch new Tractive trackables: Boom" in caplog.text
    assert hass.states.get(NEW_TRACKER_ENTITY_ID) is None

    mock_tractive_client.async_fetch_trackables.side_effect = None
    mock_tractive_client.async_fetch_trackables.return_value = trackables
    mock_tractive_client.send_error_event(None)
    await hass.async_block_till_done()

    assert mock_tractive_client.async_fetch_trackables.call_count == 2

    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_tractive_client.async_fetch_trackables.call_count == 3
    assert hass.states.get(NEW_TRACKER_ENTITY_ID)


async def test_new_trackable_fetch_unauthorized(
    hass: HomeAssistant,
    mock_tractive_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test a reauth flow is started when fetching new trackables is unauthorized."""
    await init_integration(hass, mock_config_entry)

    _add_new_trackable(mock_tractive_client)
    mock_tractive_client.async_fetch_trackables.side_effect = UnauthorizedError
    mock_tractive_client.send_error_event(None)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert len(flows) == 1
    assert flows[0]["context"]["source"] == SOURCE_REAUTH
