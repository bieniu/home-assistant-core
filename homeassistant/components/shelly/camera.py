"""Support for Shelly cameras."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, override

import aiohttp
from aioshelly.exceptions import HttpCallError, InvalidAuthError

from homeassistant.components.camera import (
    Camera,
    CameraEntityDescription,
    CameraEntityFeature,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShellyConfigEntry, ShellyRpcCoordinator
from .entity import (
    RpcEntityDescription,
    ShellyRpcAttributeEntity,
    async_setup_entry_rpc,
)
from .utils import get_host

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

        self._attr_model = self.coordinator.model

    @override
    @property
    def available(self) -> bool:
        """Available."""
        available = super().available

        return available and not self.coordinator.device.config[self.key]["privacy"]

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
    async def stream_source(self) -> str | None:
        """Return the RTSP stream source for go2rtc."""
        host = get_host(self.coordinator.config_entry.data[CONF_HOST])
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
        except aiohttp.ClientError, TimeoutError, ValueError, HttpCallError:
            return None
        except InvalidAuthError:
            await self.coordinator.async_shutdown_device_and_start_reauth()
            return None
