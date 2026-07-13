"""Support for Shelly cameras."""

from dataclasses import dataclass
from typing import Final

from homeassistant.components.camera import (
    Camera,
    CameraEntityDescription,
    CameraEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShellyConfigEntry, ShellyRpcCoordinator
from .entity import (
    RpcEntityDescription,
    ShellyRpcAttributeEntity,
    async_setup_entry_rpc,
)

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
    _attr_brand = "Shelly"
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
        self._attr_model = self.coordinator.model

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

    async def stream_source(self) -> str | None:
        """Return the WHEP stream source URL for go2rtc."""
        return (
            f"whep://{self.coordinator.device.ip_address}:"
            f"{self.coordinator.device.port}/camera/{self._id}/whep/"
            f"{self.entity_description.stream}"
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera's HTTP snapshot endpoint."""
        try:
            return await self.coordinator.device.camera_get_image(self._id)
        except TimeoutError, ValueError:
            return None
