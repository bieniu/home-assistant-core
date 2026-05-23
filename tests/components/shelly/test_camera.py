"""Tests for Shelly camera platform."""

from copy import deepcopy
from unittest.mock import AsyncMock, Mock, patch

from aioshelly.exceptions import DeviceConnectionError, RpcCallError
import pytest
from syrupy.assertion import SnapshotAssertion
from webrtc_models import RTCIceCandidateInit

from homeassistant.components.camera import (
    SERVICE_DISABLE_MOTION,
    SERVICE_ENABLE_MOTION,
    CameraState,
    RTCIceCandidateInit,
    WebRTCAnswer,
    WebRTCError,
    WebRTCSendMessage,
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

MOCK_STREAMER_OFFER_RESPONSE = {
    "session_id": "abc123",
    "sdp": "\r\n".join(
        [
            "v=0",
            "o=- 12345 1 IN IP4 192.168.1.100",
            "s=-",
            "t=0 0",
            "m=video 9 UDP/TLS/RTP/SAVPF 96",
            "c=IN IP4 192.168.1.100",
            "a=rtpmap:96 H264/90000",
            "a=ice-ufrag:shelly_ufrag",
            "a=ice-pwd:shelly_long_password",
            "a=fingerprint:sha-256 AA:BB:CC:DD",
            "a=setup:actpass",
            "a=sendonly",
            "a=candidate:1 1 UDP 2130706431 192.168.1.100 10000 typ host",
            "a=end-of-candidates",
        ]
    ),
    "end_of_candidates": True,
    "candidates": [],
}

MOCK_FRONTEND_OFFER_SDP = "\r\n".join(
    [
        "v=0",
        "o=- 99999 1 IN IP4 0.0.0.0",
        "s=-",
        "t=0 0",
        "m=video 9 UDP/TLS/RTP/SAVPF 96",
        "c=IN IP4 0.0.0.0",
        "a=rtpmap:96 H264/90000",
        "a=ice-ufrag:frontend_ufrag",
        "a=ice-pwd:frontend_long_password",
        "a=fingerprint:sha-256 11:22:33:44",
        "a=setup:actpass",
        "a=recvonly",
    ]
)


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


async def test_camera_image_returns_none(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test async_camera_image returns None (no local snapshot endpoint)."""
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    result = await camera.async_camera_image()
    assert result is None


async def test_webrtc_offer_success(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test WebRTC offer handling returns Shelly SDP as answer to frontend."""
    mock_camera_rpc_device.call_rpc = AsyncMock(
        return_value=MOCK_STREAMER_OFFER_RESPONSE
    )
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    send_message = Mock(spec=WebRTCSendMessage)

    await camera.async_handle_async_webrtc_offer(
        MOCK_FRONTEND_OFFER_SDP, "session1", send_message
    )

    mock_camera_rpc_device.call_rpc.assert_called_once_with(
        "Streamer.Offer", {"ice_servers": []}
    )

    send_message.assert_called_once()
    message = send_message.call_args[0][0]
    assert isinstance(message, WebRTCAnswer)
    assert "a=setup:passive" in message.answer
    assert "shelly_ufrag" in message.answer


async def test_webrtc_offer_invalid_sdp(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test WebRTC offer with invalid SDP returns error."""
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    send_message = Mock(spec=WebRTCSendMessage)

    await camera.async_handle_async_webrtc_offer(
        "invalid sdp", "session1", send_message
    )

    send_message.assert_called_once()
    message = send_message.call_args[0][0]
    assert isinstance(message, WebRTCError)
    assert message.code == "shelly_webrtc_offer_failed"


async def test_webrtc_offer_rpc_error(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test WebRTC offer returns error when RPC call fails."""
    mock_camera_rpc_device.call_rpc = AsyncMock(
        side_effect=RpcCallError(500, "Internal error")
    )
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    send_message = Mock(spec=WebRTCSendMessage)

    await camera.async_handle_async_webrtc_offer(
        MOCK_FRONTEND_OFFER_SDP, "session1", send_message
    )

    send_message.assert_called_once()
    message = send_message.call_args[0][0]
    assert isinstance(message, WebRTCError)
    assert message.code == "shelly_webrtc_offer_failed"


async def test_webrtc_candidate_triggers_streamer_answer(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test that end-of-candidates triggers Streamer.Answer with frontend ICE credentials."""
    mock_camera_rpc_device.call_rpc = AsyncMock(
        return_value=MOCK_STREAMER_OFFER_RESPONSE
    )
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    send_message = Mock(spec=WebRTCSendMessage)

    await camera.async_handle_async_webrtc_offer(
        MOCK_FRONTEND_OFFER_SDP, "session1", send_message
    )
    mock_camera_rpc_device.call_rpc.reset_mock()

    await camera.async_on_webrtc_candidate(
        "session1",
        RTCIceCandidateInit(candidate="1 1 UDP 2130706431 10.0.0.1 54321 typ host"),
    )
    mock_camera_rpc_device.call_rpc.assert_not_called()

    await camera.async_on_webrtc_candidate(
        "session1",
        RTCIceCandidateInit(candidate=""),
    )

    mock_camera_rpc_device.call_rpc.assert_called_once()
    call_args = mock_camera_rpc_device.call_rpc.call_args
    assert call_args[0][0] == "Streamer.Answer"
    answer_params = call_args[0][1]
    assert answer_params["session_id"] == "abc123"
    assert "frontend_ufrag" in answer_params["sdp"]
    assert "frontend_long_password" in answer_params["sdp"]
    assert "sha-256 11:22:33:44" in answer_params["sdp"]
    assert answer_params["end_of_candidates"] is True


async def test_webrtc_candidate_end_of_candidates_only_once(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test Streamer.Answer is sent only once even if multiple end-of-candidates arrive."""
    mock_camera_rpc_device.call_rpc = AsyncMock(
        return_value=MOCK_STREAMER_OFFER_RESPONSE
    )
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    send_message = Mock(spec=WebRTCSendMessage)

    await camera.async_handle_async_webrtc_offer(
        MOCK_FRONTEND_OFFER_SDP, "session1", send_message
    )
    mock_camera_rpc_device.call_rpc.reset_mock()

    end_candidate = RTCIceCandidateInit(candidate="")
    await camera.async_on_webrtc_candidate("session1", end_candidate)
    await camera.async_on_webrtc_candidate("session1", end_candidate)

    assert mock_camera_rpc_device.call_rpc.call_count == 1


async def test_webrtc_close_session(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test closing WebRTC session calls Streamer.StopStream."""
    mock_camera_rpc_device.call_rpc = AsyncMock(
        return_value=MOCK_STREAMER_OFFER_RESPONSE
    )
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    send_message = Mock(spec=WebRTCSendMessage)

    await camera.async_handle_async_webrtc_offer(
        MOCK_FRONTEND_OFFER_SDP, "session1", send_message
    )
    mock_camera_rpc_device.call_rpc.reset_mock()

    camera.close_webrtc_session("session1")
    await hass.async_block_till_done()

    mock_camera_rpc_device.call_rpc.assert_called_once_with(
        "Streamer.StopStream", {"session_id": "abc123"}
    )


async def test_webrtc_close_unknown_session(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test closing an unknown WebRTC session is a no-op."""
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    camera.close_webrtc_session("unknown_session")
    await hass.async_block_till_done()

    mock_camera_rpc_device.call_rpc.assert_not_called()


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


async def test_webrtc_offer_connection_error(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
) -> None:
    """Test WebRTC offer returns error when device connection fails."""
    mock_camera_rpc_device.call_rpc = AsyncMock(
        side_effect=DeviceConnectionError("Connection refused")
    )
    await init_integration(hass, 3)

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    send_message = Mock(spec=WebRTCSendMessage)

    await camera.async_handle_async_webrtc_offer(
        MOCK_FRONTEND_OFFER_SDP, "session1", send_message
    )

    send_message.assert_called_once()
    message = send_message.call_args[0][0]
    assert isinstance(message, WebRTCError)
    assert message.code == "shelly_webrtc_offer_failed"


@pytest.mark.parametrize(
    (
        "shelly_extra_sections",
        "frontend_extra_sections",
        "expected_in_answer",
        "expected_not_in_answer",
    ),
    [
        pytest.param(
            [
                "m=audio 9 UDP/TLS/RTP/SAVPF 111",
                "a=rtpmap:111 opus/48000/2",
                "a=sendonly",
                "a=mid:1",
            ],
            [],
            ["shelly_ufrag", "a=setup:passive"],
            ["m=audio 0"],
            id="shelly_has_extra_audio_frontend_does_not",
        ),
        pytest.param(
            [],
            [
                "m=audio 9 UDP/TLS/RTP/SAVPF 111",
                "a=rtpmap:111 opus/48000/2",
                "a=recvonly",
                "a=mid:1",
            ],
            ["m=audio 0", "a=inactive"],
            ["m=audio 9"],
            id="frontend_has_extra_audio_shelly_does_not",
        ),
    ],
)
async def test_webrtc_answer_reconciles_mlines(
    hass: HomeAssistant,
    mock_camera_rpc_device: Mock,
    shelly_extra_sections: list[str],
    frontend_extra_sections: list[str],
    expected_in_answer: list[str],
    expected_not_in_answer: list[str],
) -> None:
    """Test that the SDP answer to the frontend always matches the frontend's m-line count."""
    shelly_sdp_lines = [
        "v=0",
        "o=- 12345 1 IN IP4 192.168.1.100",
        "s=-",
        "t=0 0",
        "m=video 9 UDP/TLS/RTP/SAVPF 96",
        "c=IN IP4 192.168.1.100",
        "a=rtpmap:96 H264/90000",
        "a=ice-ufrag:shelly_ufrag",
        "a=ice-pwd:shelly_long_password",
        "a=fingerprint:sha-256 AA:BB:CC:DD",
        "a=setup:actpass",
        "a=sendonly",
        *shelly_extra_sections,
    ]
    mock_camera_rpc_device.call_rpc = AsyncMock(
        return_value={
            "session_id": "abc123",
            "sdp": "\r\n".join(shelly_sdp_lines),
            "end_of_candidates": True,
            "candidates": [],
        }
    )
    await init_integration(hass, 3)

    frontend_offer_sdp = "\r\n".join(
        [
            "v=0",
            "o=- 99999 1 IN IP4 0.0.0.0",
            "s=-",
            "t=0 0",
            "m=video 9 UDP/TLS/RTP/SAVPF 96",
            "c=IN IP4 0.0.0.0",
            "a=rtpmap:96 H264/90000",
            "a=ice-ufrag:frontend_ufrag",
            "a=ice-pwd:frontend_long_password",
            "a=fingerprint:sha-256 11:22:33:44",
            "a=setup:actpass",
            "a=recvonly",
            *frontend_extra_sections,
        ]
    )

    camera = get_camera_from_entity_id(hass, CAMERA_ENTITY_ID)
    send_message = Mock(spec=WebRTCSendMessage)

    await camera.async_handle_async_webrtc_offer(
        frontend_offer_sdp, "session1", send_message
    )

    send_message.assert_called_once()
    message = send_message.call_args[0][0]
    assert isinstance(message, WebRTCAnswer)

    frontend_mline_count = sum(
        1 for line in frontend_offer_sdp.splitlines() if line.startswith("m=")
    )
    answer_mline_count = sum(
        1 for line in message.answer.splitlines() if line.startswith("m=")
    )
    assert answer_mline_count == frontend_mline_count

    for expected in expected_in_answer:
        assert expected in message.answer
    for not_expected in expected_not_in_answer:
        assert not_expected not in message.answer
