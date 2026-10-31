"""Test the BraviaTV coordinator."""

from datetime import timedelta
from unittest.mock import AsyncMock

from freezegun.api import FrozenDateTimeFactory
from pybravia import (
    BraviaConnectionError,
    BraviaConnectionTimeout,
    BraviaError,
    BraviaNotFound,
    BraviaTurnedOff,
)
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant.typing import WebSocketGenerator

from homeassistant.components.braviatv.const import (
    CONF_NICKNAME,
    CONF_USE_PSK,
    DOMAIN,
    LEGACY_CLIENT_ID,
    NICKNAME_PREFIX,
)
from homeassistant.components.braviatv.coordinator import SCAN_INTERVAL
from homeassistant.components.media_player import ATTR_INPUT_SOURCE_LIST
from homeassistant.const import (
    CONF_CLIENT_ID,
    CONF_HOST,
    CONF_MAC,
    CONF_PIN,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant

from . import init_integration

ENTITY_ID = "media_player.bravia_tv_model"


@pytest.mark.parametrize(
    ("extra_data", "client_id", "nickname"),
    [
        (
            {CONF_CLIENT_ID: "client-id", CONF_NICKNAME: "nickname"},
            "client-id",
            "nickname",
        ),
        ({}, LEGACY_CLIENT_ID, NICKNAME_PREFIX),
    ],
)
async def test_connect_with_pin(
    hass: HomeAssistant,
    mock_braviatv_client: AsyncMock,
    extra_data: dict[str, str],
    client_id: str,
    nickname: str,
) -> None:
    """Test connecting with a PIN."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="BRAVIA TV-Model",
        unique_id="very_unique_string",
        data={
            CONF_HOST: "bravia-host",
            CONF_MAC: "AA:BB:CC:DD:EE:FF",
            CONF_PIN: "1234",
            CONF_USE_PSK: False,
            **extra_data,
        },
    )

    await init_integration(hass, entry)

    mock_braviatv_client.connect.assert_called_once_with(
        pin="1234", clientid=client_id, nickname=nickname
    )


async def test_connect_with_psk_once(
    hass: HomeAssistant,
    mock_braviatv_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test connecting with a PSK only once while the connection is kept."""
    await init_integration(hass, mock_config_entry)

    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_braviatv_client.get_power_status.call_count == 2
    mock_braviatv_client.connect.assert_called_once_with(psk="12345qwerty")


async def test_standby(
    hass: HomeAssistant,
    mock_braviatv_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test the update interval and fetched data follow the power status."""
    mock_braviatv_client.get_power_status.return_value = "standby"
    await init_integration(hass, mock_config_entry)

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_OFF
    mock_braviatv_client.get_volume_info.assert_not_called()
    mock_braviatv_client.get_playing_info.assert_not_called()

    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_braviatv_client.get_power_status.call_count == 1

    mock_braviatv_client.get_power_status.return_value = "active"
    freezer.tick(timedelta(seconds=110))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_braviatv_client.get_power_status.call_count == 2
    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON
    mock_braviatv_client.get_volume_info.assert_called_once()
    mock_braviatv_client.get_playing_info.assert_called_once()

    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_braviatv_client.get_power_status.call_count == 3


async def test_api_reloading(
    hass: HomeAssistant,
    mock_braviatv_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test updates are skipped while the API service reloads, then fail."""
    await init_integration(hass, mock_config_entry)
    mock_braviatv_client.get_power_status.side_effect = BraviaNotFound

    for _ in range(10):
        freezer.tick(SCAN_INTERVAL)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON
    # Every skipped update drops the connection, so the following ones reconnect
    assert mock_braviatv_client.connect.call_count == 10

    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_UNAVAILABLE

    mock_braviatv_client.get_power_status.side_effect = None
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON


@pytest.mark.parametrize(
    "exception", [BraviaConnectionError, BraviaConnectionTimeout, BraviaTurnedOff]
)
async def test_tv_turned_off(
    hass: HomeAssistant,
    mock_braviatv_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
    exception: type[Exception],
) -> None:
    """Test the TV is reported off when it is unreachable."""
    await init_integration(hass, mock_config_entry)
    mock_braviatv_client.get_power_status.side_effect = exception

    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_OFF

    mock_braviatv_client.get_power_status.side_effect = None
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_braviatv_client.connect.call_count == 2
    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON


async def test_update_error(
    hass: HomeAssistant,
    mock_braviatv_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Test a generic error makes entities unavailable until the next update."""
    await init_integration(hass, mock_config_entry)
    mock_braviatv_client.get_power_status.side_effect = BraviaError

    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_UNAVAILABLE

    mock_braviatv_client.get_power_status.side_effect = None
    freezer.tick(SCAN_INTERVAL)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert mock_braviatv_client.connect.call_count == 2
    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.state == STATE_ON


async def test_source_list_skips_invalid_items(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    mock_braviatv_client: AsyncMock,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Test updating sources skips incomplete items and duplicates."""
    mock_braviatv_client.get_external_status.return_value = [
        {"uri": "extInput:hdmi?port=1", "title": "HDMI 1"},
        {"uri": "extInput:hdmi?port=2", "title": "HDMI 1"},
        {"uri": "extInput:hdmi?port=3", "title": ""},
        {"title": "HDMI 4"},
    ]
    mock_braviatv_client.get_app_list.return_value = [
        {"uri": "com.sony.dtv.youtube", "title": "YouTube"},
        {"uri": "com.sony.dtv.netflix", "title": "Netflix"},
        {"title": "Broken"},
    ]
    mock_braviatv_client.get_content_list_all.return_value = [
        {"uri": "tv:dvbt?srvName=TVP1", "title": "TVP 1", "dispNum": "001"},
        {"uri": "tv:dvbt?srvName=None"},
    ]
    await init_integration(hass, mock_config_entry)
    client = await hass_ws_client(hass)

    state = hass.states.get(ENTITY_ID)
    assert state
    assert state.attributes[ATTR_INPUT_SOURCE_LIST] == ["HDMI 1"]

    await client.send_json_auto_id(
        {
            "type": "media_player/browse_media",
            "entity_id": ENTITY_ID,
            "media_content_type": "apps",
            "media_content_id": "apps",
        }
    )
    response = await client.receive_json()
    assert response["success"]
    assert [child["media_content_id"] for child in response["result"]["children"]] == [
        "com.sony.dtv.netflix",
        "com.sony.dtv.youtube",
    ]

    await client.send_json_auto_id(
        {
            "type": "media_player/browse_media",
            "entity_id": ENTITY_ID,
            "media_content_type": "channels",
            "media_content_id": "channels",
        }
    )
    response = await client.receive_json()
    assert response["success"]
    assert [child["media_content_id"] for child in response["result"]["children"]] == [
        "tv:dvbt?srvName=TVP1"
    ]
