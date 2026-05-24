"""Tests for Shelly camera platform."""

from copy import deepcopy
from unittest.mock import Mock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.camera import (
    SERVICE_DISABLE_MOTION,
    SERVICE_ENABLE_MOTION,
    CameraState,
)
from homeassistant.components.camera.const import (
    DATA_COMPONENT,
    DOMAIN as CAMERA_DOMAIN,
)
from homeassistant.components.camera.helper import get_camera_from_entity_id
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import EntityRegistry

from . import MOCK_MAC, init_integration, patch_platforms

from tests.common import snapshot_platform
from tests.test_util.aiohttp import AiohttpClientMocker

CAMERA_ENTITY_ID = "camera.test_name"

MOCK_CAMERA_CONFIG = {
    "camera:0": {
        "id": 0,
        "privacy": False,
        "arm": True,
        "audio": {"enable": False},
        "night_vision": {"mode": "auto"},
        "video": {"quality": "medium"},
        "streams": [{"width": 1920, "height": 1080}],
    }
}

MOCK_CAMERA_STATUS = {
    "camera:0": {
        "id": 0,
        "streamer": "idle",
        "motion": False,
        "streams": 0,
        "recordings": None,
    }
}


@pytest.fixture(autouse=True)
def fixture_platforms() -> None:
    """Limit platforms under test."""
    with patch_platforms([Platform.CAMERA]):
        yield


@pytest.fixture
def mock_camera_rpc_device(
    monkeypatch: pytest.MonkeyPatch, mock_rpc_device: Mock
) -> Mock:
    """Set up mock RPC device with camera component data."""
    config = deepcopy(mock_rpc_device.config) | MOCK_CAMERA_CONFIG
    monkeypatch.setattr(mock_rpc_device, "config", config)
    status = deepcopy(mock_rpc_device.status) | MOCK_CAMERA_STATUS
    monkeypatch.setattr(mock_rpc_device, "status", status)
    return mock_rpc_device


async def test_camera_entity_setup(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    entity_registry: EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test camera entity is created with correct unique_id and initial state."""
    with patch("random.SystemRandom.getrandbits", return_value=123123123123):
        entry = await init_integration(hass, 3)

    assert hass.states.get(CAMERA_ENTITY_ID)
    await snapshot_platform(hass, entity_registry, snapshot, entry.entry_id)

    assert (er_entry := entity_registry.async_get(CAMERA_ENTITY_ID))
    assert er_entry.unique_id == f"{MOCK_MAC}-camera:0"


async def test_camera_state_streaming(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test camera state is streaming when streams > 0."""
    await init_integration(hass, 3)

    new_status = deepcopy(mock_camera_rpc_device.status)
    new_status["camera:0"]["streams"] = 1
    monkeypatch.setattr(mock_camera_rpc_device, "status", new_status)
    mock_camera_rpc_device.mock_update()
    await hass.async_block_till_done()

    assert (state := hass.states.get(CAMERA_ENTITY_ID))
    assert state.state == CameraState.STREAMING


async def test_camera_state_recording(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test camera state is recording when recordings is set."""
    await init_integration(hass, 3)

    new_status = deepcopy(mock_camera_rpc_device.status)
    new_status["camera:0"]["recordings"] = {"id": 1}
    monkeypatch.setattr(mock_camera_rpc_device, "status", new_status)
    mock_camera_rpc_device.mock_update()
    await hass.async_block_till_done()

    assert (state := hass.states.get(CAMERA_ENTITY_ID))
    assert state.state == CameraState.RECORDING


@pytest.mark.parametrize(
    ("service", "expected_privacy"),
    [
        pytest.param(SERVICE_TURN_OFF, True, id="turn_off_enables_privacy"),
        pytest.param(SERVICE_TURN_ON, False, id="turn_on_disables_privacy"),
    ],
)
async def test_camera_turn_on_off(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    service: str,
    expected_privacy: bool,
) -> None:
    """Test camera turn on/off maps to privacy mode."""
    await init_integration(hass, 3)

    await hass.services.async_call(
        CAMERA_DOMAIN,
        service,
        {ATTR_ENTITY_ID: CAMERA_ENTITY_ID},
        blocking=True,
    )

    mock_camera_rpc_device.call_rpc.assert_called_once_with(
        "Camera.SetConfig",
        {"id": 0, "config": {"privacy": expected_privacy}},
    )


@pytest.mark.parametrize(
    ("service", "expected_arm"),
    [
        pytest.param(SERVICE_ENABLE_MOTION, True, id="enable_motion_arms_camera"),
        pytest.param(SERVICE_DISABLE_MOTION, False, id="disable_motion_disarms_camera"),
    ],
)
async def test_camera_motion_detection(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    service: str,
    expected_arm: bool,
) -> None:
    """Test motion detection enable/disable maps to arm config."""
    await init_integration(hass, 3)

    await hass.services.async_call(
        CAMERA_DOMAIN,
        service,
        {ATTR_ENTITY_ID: CAMERA_ENTITY_ID},
        blocking=True,
    )

    mock_camera_rpc_device.call_rpc.assert_called_once_with(
        "Camera.SetConfig",
        {"id": 0, "config": {"arm": expected_arm}},
    )


async def test_camera_image_snapshot(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test async_camera_image fetches snapshot from the camera's HTTP endpoint."""
    await init_integration(hass, 3)

    aioclient_mock.get(
        "http://192.168.1.37:80/camera/0/snapshot",
        content=b"jpeg_data",
    )
    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    result = await camera.async_camera_image()
    assert result == b"jpeg_data"


async def test_camera_image_snapshot_error(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test async_camera_image returns None on HTTP error."""
    await init_integration(hass, 3)

    aioclient_mock.get(
        "http://192.168.1.37:80/camera/0/snapshot",
        status=500,
    )
    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    result = await camera.async_camera_image()
    assert result is None


async def test_camera_stream_source(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test stream_source returns WHEP URL for go2rtc."""
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    source = await camera.stream_source()
    assert source is not None
    assert source.startswith("webrtc:http://")
    assert "/camera/0/whep/0" in source


async def test_camera_off_when_privacy_enabled(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test camera is off when privacy mode is enabled in config."""
    config = deepcopy(mock_camera_rpc_device.config)
    config["camera:0"]["privacy"] = True
    monkeypatch.setattr(mock_camera_rpc_device, "config", config)

    await init_integration(hass, 3)

    camera = hass.data[DATA_COMPONENT].get_entity(CAMERA_ENTITY_ID)
    assert camera is not None
    assert camera.is_on is False


async def test_camera_motion_detection_enabled_reflects_config(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test motion_detection_enabled reflects arm config."""
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    assert camera.motion_detection_enabled is True

    config = deepcopy(mock_camera_rpc_device.config)
    config["camera:0"]["arm"] = False
    monkeypatch.setattr(mock_camera_rpc_device, "config", config)
    mock_camera_rpc_device.mock_update()
    await hass.async_block_till_done()

    assert camera.motion_detection_enabled is False
