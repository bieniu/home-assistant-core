"""Tests for Shelly camera platform."""

from collections.abc import Generator
from copy import deepcopy
from unittest.mock import AsyncMock, Mock, patch

from aioshelly.const import MODEL_CAMERA
from aioshelly.exceptions import RpcCallError
import pytest
from syrupy.assertion import SnapshotAssertion
from webrtc_models import RTCIceCandidateInit

from homeassistant.components.camera import (
    DATA_COMPONENT,
    CameraState,
    WebRTCAnswer,
    WebRTCError,
    get_camera_from_entity_id,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import EntityRegistry

from . import MOCK_MAC, init_integration, patch_platforms

from tests.common import snapshot_platform

CAMERA_ENTITY_ID = "camera.test_name_stream_0"


@pytest.fixture(autouse=True)
def fixture_platforms() -> Generator[None]:
    """Limit platforms under test."""
    with patch_platforms([Platform.CAMERA]):
        yield


async def test_camera_entity_setup(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    entity_registry: EntityRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test camera entity is created with correct unique_id and initial state."""
    with patch("random.SystemRandom.getrandbits", return_value=123123123123):
        entry = await init_integration(hass, 3, model=MODEL_CAMERA)

    assert hass.states.get(CAMERA_ENTITY_ID)
    await snapshot_platform(hass, entity_registry, snapshot, entry.entry_id)

    assert (er_entry := entity_registry.async_get(CAMERA_ENTITY_ID))
    assert er_entry.unique_id == f"{MOCK_MAC}-camera:0-stream_0"


async def test_camera_state_streaming(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test camera state is streaming when streams > 0."""
    await init_integration(hass, 3, model=MODEL_CAMERA)

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
    await init_integration(hass, 3, model=MODEL_CAMERA)

    new_status = deepcopy(mock_camera_rpc_device.status)
    new_status["camera:0"]["recordings"] = {"id": 1}
    monkeypatch.setattr(mock_camera_rpc_device, "status", new_status)
    mock_camera_rpc_device.mock_update()
    await hass.async_block_till_done()

    assert (state := hass.states.get(CAMERA_ENTITY_ID))
    assert state.state == CameraState.RECORDING


async def test_camera_image_snapshot(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test async_camera_image fetches snapshot from the camera's HTTP endpoint."""
    await init_integration(hass, 3, model=MODEL_CAMERA)

    mock_camera_rpc_device.camera_get_image = AsyncMock(return_value=b"jpeg_data")

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    result = await camera.async_camera_image()
    assert result == b"jpeg_data"


async def test_camera_image_snapshot_error(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test async_camera_image returns None on HTTP error."""
    await init_integration(hass, 3, model=MODEL_CAMERA)

    mock_camera_rpc_device.camera_get_image = AsyncMock(return_value=None)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    result = await camera.async_camera_image()
    assert result is None


async def test_camera_webrtc_offer(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test async_handle_async_webrtc_offer proxies SDP to Shelly's WHEP endpoint."""
    await init_integration(hass, 3, model=MODEL_CAMERA)

    offer_sdp = "v=0\r\na=ice-ufrag:testufrag\r\na=ice-pwd:testpwd\r\n"
    answer_sdp = "v=0\r\na=ice-ufrag:remote\r\na=ice-pwd:remotepwd\r\n"
    mock_camera_rpc_device.camera_start_webrtc_session = AsyncMock(
        return_value=(
            answer_sdp,
            "http://192.168.1.37:80/camera/0/whep/0/sess1",
            ("testufrag", "testpwd"),
        )
    )

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    messages: list[WebRTCAnswer | WebRTCError] = []

    def send_message(message: WebRTCAnswer | WebRTCError) -> None:
        messages.append(message)

    await camera.async_handle_async_webrtc_offer(offer_sdp, "session1", send_message)

    assert len(messages) == 1
    assert isinstance(messages[0], WebRTCAnswer)
    assert messages[0].answer == answer_sdp
    mock_camera_rpc_device.camera_start_webrtc_session.assert_awaited_once_with(
        0,
        0,
        offer_sdp,
    )


async def test_camera_webrtc_offer_error(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test async_handle_async_webrtc_offer sends WebRTCError on WHEP failure."""
    await init_integration(hass, 3, model=MODEL_CAMERA)

    mock_camera_rpc_device.camera_start_webrtc_session = AsyncMock(
        side_effect=RpcCallError(500, "WHEP endpoint returned HTTP 500")
    )

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    messages: list[WebRTCAnswer | WebRTCError] = []

    def send_message(message: WebRTCAnswer | WebRTCError) -> None:
        messages.append(message)

    await camera.async_handle_async_webrtc_offer("v=0\r\n", "session1", send_message)

    assert len(messages) == 1
    assert isinstance(messages[0], WebRTCError)


async def test_camera_webrtc_candidate(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test async_on_webrtc_candidate forwards candidate via device method."""
    await init_integration(hass, 3, model=MODEL_CAMERA)

    offer_sdp = "v=0\r\na=ice-ufrag:testufrag\r\na=ice-pwd:testpwd\r\n"
    mock_camera_rpc_device.camera_start_webrtc_session = AsyncMock(
        return_value=(
            "v=0\r\n",
            "http://192.168.1.37:80/camera/0/whep/0/sess1",
            ("testufrag", "testpwd"),
        )
    )
    mock_camera_rpc_device.camera_send_webrtc_candidate = AsyncMock()

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    await camera.async_handle_async_webrtc_offer(offer_sdp, "session1", lambda _: None)
    await camera.async_on_webrtc_candidate(
        "session1", RTCIceCandidateInit("candidate", sdp_mid="1")
    )

    mock_camera_rpc_device.camera_send_webrtc_candidate.assert_awaited_once_with(
        "http://192.168.1.37:80/camera/0/whep/0/sess1",
        ("testufrag", "testpwd"),
        "candidate",
        "1",
    )


async def test_camera_stream_source(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test stream_source returns the RTSP URL for go2rtc."""
    await init_integration(hass, 3, model=MODEL_CAMERA)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    result = await camera.stream_source()
    assert result == "rtsp://192.168.1.37/stream/0"


async def test_camera_stream_source_stream_1(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test stream_source returns correct RTSP URL for stream 1."""
    await init_integration(hass, 3, model=MODEL_CAMERA)

    camera = get_camera_from_entity_id(hass, "camera.test_name_stream_1")
    result = await camera.stream_source()
    assert result == "rtsp://192.168.1.37/stream/1"


async def test_camera_close_webrtc_session(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test close_webrtc_session closes the session via device method."""
    await init_integration(hass, 3, model=MODEL_CAMERA)

    mock_camera_rpc_device.camera_start_webrtc_session = AsyncMock(
        return_value=(
            "v=0\r\n",
            "http://192.168.1.37:80/camera/0/whep/0/sess1",
            ("testufrag", "testpwd"),
        )
    )
    mock_camera_rpc_device.camera_close_webrtc_session = AsyncMock()

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    await camera.async_handle_async_webrtc_offer("v=0\r\n", "session1", lambda _: None)

    camera.close_webrtc_session("session1")
    await hass.async_block_till_done()

    mock_camera_rpc_device.camera_close_webrtc_session.assert_awaited_once_with(
        "http://192.168.1.37:80/camera/0/whep/0/sess1"
    )


async def test_camera_off_when_streamer_stopped(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test camera is off when the streamer is not running."""
    status = deepcopy(mock_camera_rpc_device.status)
    status["camera:0"]["streamer"] = "stopped"
    monkeypatch.setattr(mock_camera_rpc_device, "status", status)

    await init_integration(hass, 3, model=MODEL_CAMERA)

    camera = hass.data[DATA_COMPONENT].get_entity(CAMERA_ENTITY_ID)
    assert camera is not None
    assert camera.is_on is False


async def test_camera_properties_when_device_not_initialized(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test camera properties return safe values when the device is not initialized."""
    await init_integration(hass, 3, model=MODEL_CAMERA)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)

    monkeypatch.setattr(mock_camera_rpc_device, "initialized", False)

    assert camera.is_on is False
