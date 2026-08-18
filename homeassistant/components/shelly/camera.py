"""Support for Shelly cameras."""

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Final, override
from urllib.parse import quote

import aiohttp
from aioshelly.exceptions import RpcCallError
from webrtc_models import RTCIceCandidateInit

from homeassistant.components.camera import (
    Camera,
    CameraEntityDescription,
    CameraEntityFeature,
    WebRTCAnswer,
    WebRTCError,
    WebRTCSendMessage,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShellyConfigEntry, ShellyRpcCoordinator
from .entity import (
    RpcEntityDescription,
    ShellyRpcAttributeEntity,
    async_setup_entry_rpc,
)
from .utils import get_host

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
        entity_registry_enabled_default=False,
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

    _attr_brand = "Shelly"
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
        super().__init__(coordinator, key, attribute, description)
        Camera.__init__(self)

        self._whep_sessions: dict[str, str] = {}
        self._offer_ice_credentials: dict[str, tuple[str, str]] = {}
        self._attr_model = self.coordinator.model

    @override
    @property
    def available(self) -> bool:
        """Available."""
        available = super().available
        if not available:
            return False

        config = self.coordinator.device.config[self.key]
        return not self.status["privacy"] and config["rtsp"]["enable"]

    @override
    @property
    def is_on(self) -> bool:
        """Return True if the camera is running."""
        if not self.coordinator.device.initialized:
            return False

        return bool(self.status["streamer"] == "running")

    @override
    @property
    def is_recording(self) -> bool:
        """Return True if the camera is currently recording."""
        return bool(self.status.get("recordings"))

    @override
    @property
    def is_streaming(self) -> bool:
        """Return True if the camera is currently streaming."""
        return bool(self.status["streams"] > 0)

    @override
    async def async_handle_async_webrtc_offer(
        self, offer_sdp: str, session_id: str, send_message: WebRTCSendMessage
    ) -> None:
        """Handle WebRTC offer by proxying to Shelly's WHEP endpoint."""
        if TYPE_CHECKING:
            assert self._id is not None

        try:
            (
                answer_sdp,
                session_url,
                offer_ice_credentials,
            ) = await self.coordinator.device.camera_start_webrtc_session(
                self._id,
                self.entity_description.stream,
                offer_sdp,
            )
        except (aiohttp.ClientError, TimeoutError, RpcCallError, ValueError) as err:
            send_message(WebRTCError("shelly_webrtc_offer_failed", str(err)))
            return

        if session_url:
            self._whep_sessions[session_id] = session_url
        else:
            self._whep_sessions.pop(session_id, None)

        self._offer_ice_credentials[session_id] = offer_ice_credentials
        send_message(WebRTCAnswer(answer_sdp))

    @override
    async def async_on_webrtc_candidate(
        self, session_id: str, candidate: RTCIceCandidateInit
    ) -> None:
        """Forward ICE candidate to Shelly via WHEP trickle ICE."""
        session_url = self._whep_sessions.get(session_id)
        if not session_url or not candidate.candidate:
            return
        offer_ice_credentials = self._offer_ice_credentials.get(session_id, ("", ""))
        try:
            await self.coordinator.device.camera_send_webrtc_candidate(
                session_url,
                offer_ice_credentials,
                candidate.candidate,
                candidate.sdp_mid,
            )
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Failed to send ICE candidate to Shelly: %s", err)

    @override
    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        """Close the WHEP session on Shelly."""
        self._offer_ice_credentials.pop(session_id, None)
        if session_url := self._whep_sessions.pop(session_id, None):

            async def _close_session() -> None:
                try:
                    await self.coordinator.device.camera_close_webrtc_session(
                        session_url
                    )
                except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                    _LOGGER.debug("Failed to close WHEP session: %s", err)

            self.hass.async_create_task(_close_session())
        super().close_webrtc_session(session_id)

    @override
    async def stream_source(self) -> str | None:
        """Return the RTSP stream source for go2rtc."""
        username = self.coordinator.config_entry.data.get(CONF_USERNAME)
        password = self.coordinator.config_entry.data.get(CONF_PASSWORD)
        host = get_host(self.coordinator.config_entry.data[CONF_HOST])

        if username and password:
            return (
                f"rtsp://{quote(username, safe='')}:{quote(password, safe='')}@{host}"
                f"/stream/{self.entity_description.stream}"
            )

        return f"rtsp://{host}/stream/{self.entity_description.stream}"

    @override
    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera's HTTP snapshot endpoint."""
        if TYPE_CHECKING:
            assert self._id is not None

        try:
            return await self.coordinator.device.camera_get_image(self._id)
        except aiohttp.ClientError, TimeoutError, ValueError:
            return None
