"""Support for Shelly cameras."""

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Final

import aiohttp
from webrtc_models import RTCIceCandidateInit

from homeassistant.components.camera import (
    Camera,
    CameraEntityDescription,
    CameraEntityFeature,
    WebRTCAnswer,
    WebRTCError,
    WebRTCSendMessage,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CAMERA_WHEP_URL
from .coordinator import ShellyConfigEntry, ShellyRpcCoordinator
from .entity import (
    RpcEntityDescription,
    ShellyRpcAttributeEntity,
    async_setup_entry_rpc,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class RpcCameraEntityDescription(RpcEntityDescription, CameraEntityDescription):
    """Class to describe a Shelly RPC camera entity."""

    stream: int = 0


RPC_CAMERA_ENTITIES: Final = {
    "stream_0": RpcCameraEntityDescription(
        key="camera",
        stream=0,
        translation_key="stream",
        translation_placeholders={"stream_id": "0"},
    ),
    "stream_1": RpcCameraEntityDescription(
        key="camera",
        stream=1,
        translation_key="stream",
        translation_placeholders={"stream_id": "1"},
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ShellyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Shelly camera entities."""
    if not config_entry.runtime_data.rpc:
        return
    async_setup_entry_rpc(
        hass,
        config_entry,
        async_add_entities,
        RPC_CAMERA_ENTITIES,
        ShellyCameraEntity,
    )


class ShellyCameraEntity(ShellyRpcAttributeEntity, Camera):
    """Shelly camera entity for RPC devices."""

    _attr_supported_features = CameraEntityFeature.STREAM
    entity_description: RpcCameraEntityDescription

    def __init__(
        self,
        coordinator: ShellyRpcCoordinator,
        key: str,
        attribute: str,
        description: RpcCameraEntityDescription,
    ) -> None:
        """Initialize Shelly camera entity."""
        ShellyRpcAttributeEntity.__init__(
            self, coordinator, key, attribute, description
        )
        Camera.__init__(self)
        self._whep_sessions: dict[str, str] = {}
        self._offer_ice_credentials: dict[str, tuple[str, str]] = {}
        self._host = f"{coordinator.device.ip_address}:{coordinator.device.port}"

    @property
    def available(self) -> bool:
        """Available."""
        available = super().available

        return available and not self.coordinator.device.config[self.key]["privacy"]

    @property
    def is_on(self) -> bool:
        """Return True if the camera is running."""
        if not self.coordinator.device.initialized:
            return False

        return bool(self.status["streamer"] == "running")

    @property
    def is_recording(self) -> bool:
        """Return True if the camera is currently recording."""
        return bool(self.status.get("recordings"))

    @property
    def is_streaming(self) -> bool:
        """Return True if the camera is currently streaming."""
        return bool(self.status["streams"] > 0)

    @property
    def use_stream_for_stills(self) -> bool:
        """Use direct HTTP snapshot instead of stream for still images."""
        return False

    async def async_handle_async_webrtc_offer(
        self, offer_sdp: str, session_id: str, send_message: WebRTCSendMessage
    ) -> None:
        """Handle WebRTC offer by proxying to Shelly's WHEP endpoint."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                CAMERA_WHEP_URL.format(
                    host=self._host,
                    camera_id=self._id,
                    stream_id=self.entity_description.stream,
                ),
                data=offer_sdp,
                headers={"Content-Type": "application/sdp"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 201:
                    send_message(
                        WebRTCError(
                            "shelly_webrtc_offer_failed",
                            f"WHEP endpoint returned HTTP {resp.status}",
                        )
                    )
                    return
                answer_sdp = await resp.text()
                location = resp.headers.get("Location", "")
        except (aiohttp.ClientError, TimeoutError) as err:
            send_message(WebRTCError("shelly_webrtc_offer_failed", str(err)))
            return

        if location:
            full_location = (
                f"http://{self._host}{location}"
                if location.startswith("/")
                else location
            )
            self._whep_sessions[session_id] = full_location
        self._offer_ice_credentials[session_id] = _parse_sdp_ice_credentials(offer_sdp)
        send_message(WebRTCAnswer(answer_sdp))

    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        """Forward ICE candidate to Shelly via WHEP trickle ICE."""
        session_url = self._whep_sessions.get(session_id)
        if not session_url or not candidate.candidate:
            return
        ufrag, pwd = self._offer_ice_credentials.get(session_id, ("", ""))
        mid = candidate.sdp_mid or "0"
        candidate_value = candidate.candidate.removeprefix("a=")
        body = (
            f"a=ice-ufrag:{ufrag}\r\n"
            f"a=ice-pwd:{pwd}\r\n"
            f"m=video 9 RTP/AVP 0\r\n"
            f"a=mid:{mid}\r\n"
            f"a=candidate:{candidate_value}\r\n"
        )
        http_session = async_get_clientsession(self.hass)
        try:
            await http_session.patch(
                session_url,
                data=body,
                headers={"Content-Type": "application/trickle-ice-sdpfrag"},
                timeout=aiohttp.ClientTimeout(total=5),
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOGGER.debug("Failed to send ICE candidate to Shelly: %s", err)

    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        """Close the WHEP session on Shelly."""
        self._offer_ice_credentials.pop(session_id, None)
        if session_url := self._whep_sessions.pop(session_id, None):

            async def _delete_session() -> None:
                http_session = async_get_clientsession(self.hass)
                try:
                    await http_session.delete(
                        session_url,
                        timeout=aiohttp.ClientTimeout(total=5),
                    )
                except (aiohttp.ClientError, TimeoutError) as err:
                    _LOGGER.debug("Failed to delete WHEP session: %s", err)

            self.hass.async_create_task(_delete_session())
        super().close_webrtc_session(session_id)

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera's HTTP snapshot endpoint."""
        if TYPE_CHECKING:
            assert self._id is not None

        try:
            return await self.coordinator.device.camera_get_image(self._id)
        except aiohttp.ClientError, TimeoutError:
            return None


def _parse_sdp_ice_credentials(sdp: str) -> tuple[str, str]:
    """Extract ice-ufrag and ice-pwd from an SDP string."""
    ufrag = ""
    pwd = ""
    for line in sdp.splitlines():
        if line.startswith("a=ice-ufrag:"):
            ufrag = line[12:]
        elif line.startswith("a=ice-pwd:"):
            pwd = line[10:]
    return ufrag, pwd
