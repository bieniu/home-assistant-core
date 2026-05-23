"""Support for Shelly cameras."""

import contextlib
import logging
from typing import Any

from aioshelly.exceptions import DeviceConnectionError, InvalidAuthError, RpcCallError

from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
    RTCIceCandidateInit,
    WebRTCAnswer,
    WebRTCError,
    WebRTCSendMessage,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShellyConfigEntry, ShellyRpcCoordinator
from .entity import ShellyRpcEntity
from .utils import get_rpc_key_instances

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ShellyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Shelly camera entities."""
    if not config_entry.runtime_data.rpc:
        return
    coordinator = config_entry.runtime_data.rpc
    async_add_entities(
        ShellyCameraEntity(coordinator, key)
        for key in get_rpc_key_instances(coordinator.device.status, "camera")
    )


def _extract_sdp_field(sdp: str, prefix: str) -> str | None:
    """Extract the first matching field value from an SDP string."""
    for line in sdp.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


def _parse_sdp_sections(sdp: str) -> tuple[list[str], list[list[str]]]:
    """Split an SDP string into session-level lines and per-m-section line lists."""
    session: list[str] = []
    sections: list[list[str]] = []
    current: list[str] | None = None
    for line in sdp.splitlines():
        if line.startswith("m="):
            current = [line]
            sections.append(current)
        elif current is not None:
            current.append(line)
        else:
            session.append(line)
    return session, sections


def _adapt_shelly_sdp_as_frontend_answer(
    shelly_sdp: str, frontend_offer_sdp: str
) -> str:
    """Adapt Shelly's offer SDP to be sent as an answer to the frontend.

    Shelly is the WebRTC offerer; the HA frontend expects to be the offerer.
    This adapts Shelly's SDP offer to act as the answer back to the frontend.
    The setup attribute is changed to passive so the frontend (as DTLS client,
    active) connects to Shelly (as DTLS server, passive).

    The answer must have the same number of m-sections as the frontend offer.
    Shelly sections are matched to frontend offer sections by media type.
    Any frontend m-section without a matching Shelly section is rejected (port=0).
    """
    session_lines, shelly_sections = _parse_sdp_sections(shelly_sdp)
    _, frontend_sections = _parse_sdp_sections(frontend_offer_sdp)

    shelly_by_type: dict[str, list[str]] = {}
    for section in shelly_sections:
        mtype = section[0].split()[0][2:]  # "m=audio ..." -> "audio"
        if mtype not in shelly_by_type:
            shelly_by_type[mtype] = section

    answer_sections: list[list[str]] = []
    used_types: set[str] = set()
    for frontend_section in frontend_sections:
        mtype = frontend_section[0].split()[0][2:]
        if mtype in shelly_by_type and mtype not in used_types:
            answer_sections.append(shelly_by_type[mtype])
            used_types.add(mtype)
        else:
            m_parts = frontend_section[0].split()
            m_parts[1] = "0"
            answer_sections.append([" ".join(m_parts), "a=inactive"])

    def _adapt_line(line: str) -> str:
        if line.startswith("a=setup:"):
            return "a=setup:passive"
        return line

    result = [_adapt_line(line) for line in session_lines]
    for section in answer_sections:
        result.extend(_adapt_line(line) for line in section)
    return "\r\n".join(result)


_DIRECTION_FLIP: dict[str, str] = {
    "a=sendonly": "a=recvonly",
    "a=recvonly": "a=sendonly",
}


def _build_answer_sdp_for_shelly(
    shelly_offer_sdp: str,
    frontend_ufrag: str,
    frontend_pwd: str,
    frontend_fingerprint: str,
    candidates: list[str],
) -> str:
    """Build SDP answer to send to Shelly via Streamer.Answer.

    Uses Shelly's offer as a structural template for codec/media sections but
    substitutes the frontend's ICE credentials, fingerprint, and candidates.
    Media directions are flipped so the answer correctly mirrors the offer.
    """
    result = []
    candidates_inserted = False
    for line in shelly_offer_sdp.splitlines():
        if line.startswith("a=ice-ufrag:"):
            result.append(f"a=ice-ufrag:{frontend_ufrag}")
        elif line.startswith("a=ice-pwd:"):
            result.append(f"a=ice-pwd:{frontend_pwd}")
        elif line.startswith("a=fingerprint:"):
            result.append(f"a=fingerprint:{frontend_fingerprint}")
        elif line.startswith("a=setup:"):
            result.append("a=setup:active")
        elif line.startswith("a=candidate:"):
            if not candidates_inserted:
                result.extend(f"a=candidate:{cand}" for cand in candidates)
                candidates_inserted = True
        elif line == "a=end-of-candidates":
            if not candidates_inserted:
                result.extend(f"a=candidate:{cand}" for cand in candidates)
                candidates_inserted = True
            result.append(line)
        elif line in _DIRECTION_FLIP:
            result.append(_DIRECTION_FLIP[line])
        else:
            result.append(line)
    return "\r\n".join(result)


class ShellyCameraEntity(ShellyRpcEntity, Camera):
    """Shelly camera entity for RPC-based Gen2/Gen3 devices."""

    _attr_name = None
    _attr_supported_features = CameraEntityFeature.ON_OFF | CameraEntityFeature.STREAM

    def __init__(self, coordinator: ShellyRpcCoordinator, key: str) -> None:
        """Initialize Shelly camera entity."""
        ShellyRpcEntity.__init__(self, coordinator, key)
        Camera.__init__(self)
        self._camera_id: int = int(key.split(":")[1])
        self._webrtc_sessions: dict[str, dict[str, Any]] = {}

    @property
    def is_on(self) -> bool:
        """Return True if the camera is on (privacy mode disabled)."""
        return not self.coordinator.device.config[self.key]["privacy"]

    @property
    def is_recording(self) -> bool:
        """Return True if the camera is currently recording."""
        return bool(self.status.get("recordings"))

    @property
    def is_streaming(self) -> bool:
        """Return True if the camera is currently streaming."""
        return self.status["streams"] > 0

    @property
    def motion_detection_enabled(self) -> bool:
        """Return True if camera is armed (motion detection active)."""
        return self.coordinator.device.config[self.key]["arm"]

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return bytes of camera image; no local snapshot endpoint available."""
        return None

    async def async_turn_on(self) -> None:
        """Turn the camera on by disabling privacy mode."""
        await self.call_rpc(
            "Camera.SetConfig",
            {"id": self._camera_id, "config": {"privacy": False}},
        )

    async def async_turn_off(self) -> None:
        """Turn the camera off by enabling privacy mode."""
        await self.call_rpc(
            "Camera.SetConfig",
            {"id": self._camera_id, "config": {"privacy": True}},
        )

    async def async_enable_motion_detection(self) -> None:
        """Enable motion detection by arming the camera."""
        await self.call_rpc(
            "Camera.SetConfig",
            {"id": self._camera_id, "config": {"arm": True}},
        )

    async def async_disable_motion_detection(self) -> None:
        """Disable motion detection by disarming the camera."""
        await self.call_rpc(
            "Camera.SetConfig",
            {"id": self._camera_id, "config": {"arm": False}},
        )

    async def async_handle_async_webrtc_offer(
        self, offer_sdp: str, session_id: str, send_message: WebRTCSendMessage
    ) -> None:
        """Handle WebRTC offer from the frontend using the Shelly Streamer API.

        Shelly acts as the WebRTC offerer (non-trickle, all ICE candidates embedded
        in its SDP). The frontend expects to be the offerer. We bridge this mismatch:
        1. Extract the frontend's ICE credentials from its offer.
        2. Call Streamer.Offer on the Shelly device to get its complete SDP offer.
        3. Send Shelly's adapted SDP to the frontend as the WebRTC answer.
        4. Accumulate trickle ICE candidates from the frontend.
        5. On end-of-candidates, send Streamer.Answer to Shelly.
        The frontend then connects directly to the Shelly device using Shelly's
        ICE candidates; Shelly connects back using the frontend's ICE credentials.
        """
        frontend_ufrag = _extract_sdp_field(offer_sdp, "a=ice-ufrag:")
        frontend_pwd = _extract_sdp_field(offer_sdp, "a=ice-pwd:")
        frontend_fingerprint = _extract_sdp_field(offer_sdp, "a=fingerprint:")
        if not all([frontend_ufrag, frontend_pwd, frontend_fingerprint]):
            send_message(WebRTCError("shelly_webrtc_offer_failed", "Invalid SDP offer"))
            return

        try:
            result = await self.coordinator.device.call_rpc(
                "Streamer.Offer", {"ice_servers": []}
            )
        except DeviceConnectionError as err:
            send_message(WebRTCError("shelly_webrtc_offer_failed", str(err)))
            return
        except RpcCallError as err:
            send_message(WebRTCError("shelly_webrtc_offer_failed", str(err)))
            return
        except InvalidAuthError:
            await self.coordinator.async_shutdown_device_and_start_reauth()
            return

        shelly_session_id: str = result["session_id"]
        shelly_offer_sdp: str = result["sdp"]

        self._webrtc_sessions[session_id] = {
            "shelly_session_id": shelly_session_id,
            "send_message": send_message,
            "frontend_ufrag": frontend_ufrag,
            "frontend_pwd": frontend_pwd,
            "frontend_fingerprint": frontend_fingerprint,
            "shelly_offer_sdp": shelly_offer_sdp,
            "candidates": [],
            "answer_sent": False,
        }

        send_message(
            WebRTCAnswer(
                _adapt_shelly_sdp_as_frontend_answer(shelly_offer_sdp, offer_sdp)
            )
        )

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        """Handle trickle ICE candidate from the frontend.

        Accumulates candidates; triggers Streamer.Answer when end-of-candidates
        is signalled (empty candidate string).
        """
        session = self._webrtc_sessions.get(session_id)
        if session is None:
            return

        if candidate.candidate:
            session["candidates"].append(candidate.candidate)
        elif not session["answer_sent"]:
            await self._send_streamer_answer(session_id)

    async def _send_streamer_answer(self, session_id: str) -> None:
        """Send SDP answer to Shelly once all frontend ICE candidates are gathered."""
        session = self._webrtc_sessions.get(session_id)
        if session is None or session["answer_sent"]:
            return
        session["answer_sent"] = True

        answer_sdp = _build_answer_sdp_for_shelly(
            session["shelly_offer_sdp"],
            session["frontend_ufrag"],
            session["frontend_pwd"],
            session["frontend_fingerprint"],
            session["candidates"],
        )
        try:
            await self.coordinator.device.call_rpc(
                "Streamer.Answer",
                {
                    "session_id": session["shelly_session_id"],
                    "sdp": answer_sdp,
                    "end_of_candidates": True,
                    "candidates": [],
                },
            )
        except (DeviceConnectionError, RpcCallError) as err:
            send_message = session["send_message"]
            send_message(WebRTCError("shelly_webrtc_answer_failed", str(err)))
        except InvalidAuthError:
            await self.coordinator.async_shutdown_device_and_start_reauth()

    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        """Close a WebRTC session by stopping the stream on the Shelly device."""
        session = self._webrtc_sessions.pop(session_id, None)
        if session is None:
            return
        self.hass.async_create_task(
            self._async_stop_stream(session["shelly_session_id"])
        )

    async def _async_stop_stream(self, shelly_session_id: str) -> None:
        """Stop the Shelly WebRTC stream for a session."""
        with contextlib.suppress(DeviceConnectionError, RpcCallError, InvalidAuthError):
            await self.coordinator.device.call_rpc(
                "Streamer.StopStream",
                {"session_id": shelly_session_id},
            )

    async def async_will_remove_from_hass(self) -> None:
        """Clean up any open WebRTC sessions when entity is removed."""
        for session in list(self._webrtc_sessions.values()):
            with contextlib.suppress(
                DeviceConnectionError, RpcCallError, InvalidAuthError
            ):
                await self.coordinator.device.call_rpc(
                    "Streamer.StopStream",
                    {"session_id": session["shelly_session_id"]},
                )
        self._webrtc_sessions.clear()
